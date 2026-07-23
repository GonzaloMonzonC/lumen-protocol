//! Stable JSON C ABI for Python and other language bindings.

use crate::{Compiler, Execution, GlobalEntry, MemoryHost, Program, Value, Vm, VmState};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::ffi::{CStr, CString};
use std::os::raw::c_char;
use std::panic::{catch_unwind, AssertUnwindSafe};

#[derive(Debug, Deserialize)]
pub struct ExecuteRequest {
    #[serde(default)]
    pub source: Option<String>,
    #[serde(default)]
    pub program: Option<Program>,
    #[serde(default)]
    pub state: Option<VmState>,
    #[serde(default)]
    pub vars: BTreeMap<String, Value>,
    #[serde(default)]
    pub job_id: Option<i64>,
    #[serde(default)]
    pub globals: Vec<GlobalEntry>,
    #[serde(default)]
    pub routines: BTreeMap<String, String>,
    #[serde(default)]
    pub input: Vec<String>,
    #[serde(default)]
    pub gas_limit: Option<u64>,
    #[serde(default)]
    pub gas_budget: Option<u64>,
    #[serde(default)]
    pub slice_gas: Option<u64>,
    #[serde(default)]
    pub llm_api_keys: HashMap<String, String>,
    #[serde(default)]
    pub sqlite_path: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct ExecuteResponse {
    pub ok: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub execution: Option<Execution>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub program: Option<Program>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub state: Option<VmState>,
    pub globals: Vec<GlobalEntry>,
}

impl ExecuteResponse {
    fn error(message: impl Into<String>) -> Self {
        Self {
            ok: false,
            error: Some(message.into()),
            execution: None,
            program: None,
            state: None,
            globals: Vec::new(),
        }
    }
}

pub fn compile_json(source: &str) -> String {
    match Compiler::compile(source) {
        Ok(program) => serde_json::to_string(&program),
        Err(error) => Err(serde_json::Error::io(std::io::Error::other(error))),
    }
    .unwrap_or_else(|error| format!(r#"{{"error":{}}}"#, json_string(&error.to_string())))
}

pub fn execute_json(request_json: &str) -> String {
    let response = match serde_json::from_str::<ExecuteRequest>(request_json) {
        Ok(request) => execute(request),
        Err(error) => ExecuteResponse::error(format!("invalid request: {error}")),
    };
    serde_json::to_string(&response).unwrap_or_else(|error| {
        format!(
            r#"{{"ok":false,"error":{}}}"#,
            json_string(&error.to_string())
        )
    })
}

fn execute(request: ExecuteRequest) -> ExecuteResponse {
    let program = match request.program {
        Some(program) => program,
        None => match request.source {
            Some(source) => match Compiler::compile(&source) {
                Ok(program) => program,
                Err(error) => return ExecuteResponse::error(error),
            },
            None => return ExecuteResponse::error("source or program is required"),
        },
    };

    let mut host = if let Some(ref db_path) = request.sqlite_path {
        match MemoryHost::from_sqlite(db_path) {
            Ok(h) => h,
            Err(e) => return ExecuteResponse::error(format!("SqliteHost: {e}")),
        }
    } else {
        MemoryHost::from_entries(request.globals)
    };
    for (name, source) in request.routines {
        host.add_routine(name, source);
    }
    for value in request.input {
        host.push_input(value);
    }
    // Set LLM API keys as env vars so the thread pool can read them
    for (provider, key) in &request.llm_api_keys {
        let var_name = format!("{}_API_KEY", provider.to_uppercase());
        std::env::set_var(&var_name, key);
    }

    let (execution, state) = {
        let mut vm = match request.state {
            Some(state) => match Vm::resume(program.clone(), state, &mut host) {
                Ok(vm) => vm,
                Err(error) => return ExecuteResponse::error(error.zerror),
            },
            None => {
                let mut vm = Vm::new(program.clone(), &mut host);
                vm.state.vars = request.vars;
                vm.state.job_id = request.job_id.unwrap_or_default();
                vm
            }
        };
        if let Some(limit) = request.gas_limit {
            vm.state.gas_limit = limit.max(1);
        }
        if let Some(budget) = request.gas_budget {
            vm.state.gas_budget = budget;
        }
        let execution = vm.run_slice(request.slice_gas.unwrap_or(vm.state.gas_limit));
        (execution, vm.state)
    };

    ExecuteResponse {
        ok: !matches!(execution, Execution::Error),
        error: state.error.as_ref().map(|error| error.zerror.clone()),
        execution: Some(execution),
        program: Some(program),
        state: Some(state),
        globals: host.entries(),
    }
}

fn json_string(value: &str) -> String {
    serde_json::to_string(value).unwrap_or_else(|_| "\"serialization error\"".to_string())
}

fn into_c_string(value: String) -> *mut c_char {
    CString::new(value)
        .unwrap_or_else(|_| CString::new(r#"{"ok":false,"error":"embedded NUL"}"#).unwrap())
        .into_raw()
}

/// Compile UTF-8 M-Light source and return an owned JSON string.
///
/// # Safety
/// `source` must point to a valid NUL-terminated C string. The returned pointer
/// must be released exactly once with [`lm_string_free`].
#[no_mangle]
pub unsafe extern "C" fn lm_compile_json(source: *const c_char) -> *mut c_char {
    if source.is_null() {
        return into_c_string(r#"{"error":"null source"}"#.to_string());
    }
    let source = CStr::from_ptr(source);
    match source.to_str() {
        Ok(source) => match catch_unwind(AssertUnwindSafe(|| compile_json(source))) {
            Ok(response) => into_c_string(response),
            Err(_) => into_c_string(r#"{"error":"panic in Rust compiler"}"#.to_string()),
        },
        Err(error) => into_c_string(format!(
            r#"{{"error":{}}}"#,
            json_string(&error.to_string())
        )),
    }
}

/// Execute a UTF-8 JSON request and return an owned JSON response.
///
/// # Safety
/// `request` must point to a valid NUL-terminated C string. The returned pointer
/// must be released exactly once with [`lm_string_free`].
#[no_mangle]
pub unsafe extern "C" fn lm_execute_json(request: *const c_char) -> *mut c_char {
    if request.is_null() {
        return into_c_string(r#"{"ok":false,"error":"null request"}"#.to_string());
    }
    let request = CStr::from_ptr(request);
    match request.to_str() {
        Ok(request) => match catch_unwind(AssertUnwindSafe(|| execute_json(request))) {
            Ok(response) => into_c_string(response),
            Err(_) => into_c_string(r#"{"ok":false,"error":"panic in Rust VM"}"#.to_string()),
        },
        Err(error) => into_c_string(format!(
            r#"{{"ok":false,"error":{}}}"#,
            json_string(&error.to_string())
        )),
    }
}

/// Release a string returned by this library.
///
/// # Safety
/// `value` must be null or a pointer returned by this library that has not
/// already been freed.
#[no_mangle]
pub unsafe extern "C" fn lm_string_free(value: *mut c_char) {
    if !value.is_null() {
        drop(CString::from_raw(value));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn json_api_executes_and_returns_state() {
        let response: serde_json::Value =
            serde_json::from_str(&execute_json(r#"{"source":"S x=2+3 W x","gas_limit":100}"#))
                .unwrap();
        assert_eq!(response["ok"], true);
        assert_eq!(response["execution"], "completed");
        assert_eq!(response["state"]["vars"]["x"], 5.0);
        assert_eq!(response["state"]["output"], "5");
    }
}
