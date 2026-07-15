use lumen_mlight::{Host, Subscript, Value};
use serde_json::{json, Value as JsonValue};
use std::collections::VecDeque;
use std::ffi::{c_char, c_void, CString};

pub type HostCallback = unsafe extern "C" fn(
    context: *mut c_void,
    request: *const c_char,
    output: *mut u8,
    capacity: usize,
) -> isize;

#[derive(Clone, Copy)]
pub struct CallbackBridge {
    callback: HostCallback,
    context: *mut c_void,
}

// The Python binding keeps the callback and context alive until shutdown. All
// invocations are serialized on the scheduler thread.
unsafe impl Send for CallbackBridge {}
unsafe impl Sync for CallbackBridge {}

impl CallbackBridge {
    pub fn new(callback: HostCallback, context: *mut c_void) -> Self {
        Self { callback, context }
    }

    pub fn call(&self, operation: &str, payload: JsonValue) -> Result<JsonValue, String> {
        let request = CString::new(json!({"op": operation, "args": payload}).to_string())
            .map_err(|_| "callback request contains NUL".to_string())?;
        // The binding executes on the probe and caches those exact bytes; the
        // second call only copies them. Stateful operations therefore run once
        // without a fixed oversized allocation on every global access.
        let required =
            unsafe { (self.callback)(self.context, request.as_ptr(), std::ptr::null_mut(), 0) };
        if required < 0 {
            return Err(format!("PDB callback {operation} failed ({required})"));
        }
        let mut output = vec![0_u8; required as usize + 1];
        let written = unsafe {
            (self.callback)(
                self.context,
                request.as_ptr(),
                output.as_mut_ptr(),
                output.len(),
            )
        };
        if written < 0 {
            return Err(format!("PDB callback {operation} failed ({written})"));
        }
        let response: JsonValue = serde_json::from_slice(&output[..written as usize])
            .map_err(|error| format!("invalid PDB callback response: {error}"))?;
        if response.get("success").and_then(JsonValue::as_bool) == Some(false) {
            return Err(response
                .get("error")
                .and_then(JsonValue::as_str)
                .unwrap_or("PDB callback failed")
                .to_string());
        }
        Ok(response)
    }
}

pub struct LiveHost {
    pub bridge: CallbackBridge,
    pub pid: i64,
    transaction_level: usize,
    input: VecDeque<String>,
    pub empty_read: bool,
}

impl LiveHost {
    pub fn new(bridge: CallbackBridge, pid: i64) -> Self {
        Self {
            bridge,
            pid,
            transaction_level: 0,
            input: VecDeque::new(),
            empty_read: false,
        }
    }

    pub fn push_input(&mut self, value: String) {
        self.input.push_back(value);
    }
}

impl Host for LiveHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        let result = self
            .bridge
            .call("get", json!({"pid": self.pid, "ns": ns, "subs": subs}))?;
        if result.get("found").and_then(JsonValue::as_bool) == Some(false) {
            Ok(None)
        } else {
            Ok(result.get("value").cloned().map(Value::from_json))
        }
    }

    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        self.bridge.call(
            "set",
            json!({"pid": self.pid, "ns": ns, "subs": subs, "value": value.to_json()}),
        )?;
        Ok(())
    }

    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        let result = self
            .bridge
            .call("kill", json!({"pid": self.pid, "ns": ns, "subs": subs}))?;
        Ok(result
            .get("killed")
            .and_then(JsonValue::as_u64)
            .unwrap_or(0))
    }

    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        let result = self
            .bridge
            .call("data", json!({"pid": self.pid, "ns": ns, "subs": subs}))?;
        Ok(result.get("value").and_then(JsonValue::as_u64).unwrap_or(0) as u8)
    }

    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        let mut subs = parent.to_vec();
        subs.push(
            current
                .cloned()
                .unwrap_or_else(|| Subscript::String(String::new())),
        );
        let result = self.bridge.call(
            "order",
            json!({"pid": self.pid, "ns": ns, "subs": subs, "direction": direction}),
        )?;
        Ok(result.get("value").cloned().and_then(|value| {
            if value.is_null() {
                None
            } else {
                serde_json::from_value(value).ok()
            }
        }))
    }

    fn transaction_start(&mut self) -> Result<(), String> {
        self.bridge
            .call("transaction_start", json!({"pid": self.pid}))?;
        self.transaction_level += 1;
        Ok(())
    }

    fn transaction_commit(&mut self) -> Result<(), String> {
        if self.transaction_level == 0 {
            return Err("TCOMMIT without TSTART".to_string());
        }
        self.bridge
            .call("transaction_commit", json!({"pid": self.pid}))?;
        self.transaction_level -= 1;
        Ok(())
    }

    fn transaction_rollback(&mut self) -> Result<(), String> {
        if self.transaction_level == 0 {
            return Err("TROLLBACK without TSTART".to_string());
        }
        self.bridge
            .call("transaction_rollback", json!({"pid": self.pid}))?;
        self.transaction_level -= 1;
        Ok(())
    }

    fn transaction_level(&self) -> usize {
        self.transaction_level
    }

    fn routine(&self, name: &str) -> Result<Option<String>, String> {
        let result = self
            .bridge
            .call("routine", json!({"pid": self.pid, "name": name}))?;
        Ok(result
            .get("source")
            .and_then(JsonValue::as_str)
            .map(str::to_string))
    }

    fn read(&mut self) -> Result<String, String> {
        if let Some(value) = self.input.pop_front() {
            return Ok(value);
        }
        self.empty_read = true;
        Ok(String::new())
    }

    fn read_would_block(&self) -> bool {
        self.empty_read
    }
}
