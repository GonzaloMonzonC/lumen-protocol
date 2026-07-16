//! WASM bindings for M-Light VM — compile with `wasm-pack build --features wasm`
//!
//! Exposes `m_compile` and `m_execute` to JavaScript via wasm-bindgen.
//! Uses `MemoryHost` for in-memory ^GLOBALes (no filesystem, no SQLite).
//!
//! ## Build
//! ```bash
//! wasm-pack build --target web --features wasm
//! ```
//!
//! ## Usage from JS
//! ```javascript
//! import init, { m_compile, m_execute, m_execute_raw, m_version } from "./pkg/lumen_mlight.js";
//! await init();
//! const compiled = m_compile('S x=42 W x Q');
//! const output = m_execute(compiled, "[]");
//! console.log(output); // "42"
//! ```

use wasm_bindgen::prelude::*;
use crate::{Compiler, MemoryHost, Vm, GlobalEntry, Program};

// ── Public WASM API ────────────────────────────────────────────────────────

/// Version string.
#[wasm_bindgen]
pub fn m_version() -> String {
    env!("CARGO_PKG_VERSION").to_string()
}

/// Compile M code into an opaque binary bytecode (JSON-serialized Program).
/// Returns a `Uint8Array` that you pass to `m_execute`.
/// Throws a JS error if compilation fails.
#[wasm_bindgen]
pub fn m_compile(code: &str) -> Result<Vec<u8>, JsValue> {
    let program = Compiler::compile(code)
        .map_err(|e| JsValue::from_str(&format!("M compile error: {}", e)))?;
    serde_json::to_vec(&program)
        .map_err(|e| JsValue::from_str(&format!("Serialize error: {}", e)))
}

/// Execute compiled bytecode against in-memory ^GLOBALes.
///
/// `compiled`: output of `m_compile` (Uint8Array)
/// `globals_json`: JSON array of global entries to preload, e.g.
///   `[{"ns":"VENTAS","subs":["total"],"value":5000}]`
///
/// Returns the M `WRITE` output as a string.
#[wasm_bindgen]
pub fn m_execute(compiled: &[u8], globals_json: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;
    
    let globals: Vec<GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals JSON: {}", e)))?
    };
    
    let mut host = MemoryHost::from_entries(globals);
    let mut vm = Vm::new(program, &mut host);
    vm.run();
    if let Some(error) = &vm.state.error {
        return Err(JsValue::from_str(&format!(
            "M runtime error: {} at line {}", error.ecode, error.line
        )));
    }
    
    Ok(vm.state.output.clone())
}

/// Execute and return full result: output + all variables + ^GLOBAL state.
/// Returns JSON: `{"output": "...", "vars": {...}, "globals": [...]}`
#[wasm_bindgen]
pub fn m_execute_raw(compiled: &[u8], globals_json: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;
    
    let globals: Vec<GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals JSON: {}", e)))?
    };
    
    let mut host = MemoryHost::from_entries(globals);
    let mut vm = Vm::new(program, &mut host);
    vm.run();
    if let Some(error) = &vm.state.error {
        return Err(JsValue::from_str(&format!(
            "M runtime error: {} at line {}", error.ecode, error.line
        )));
    }
    
    let vars: std::collections::BTreeMap<String, String> = vm.state.vars
        .iter()
        .map(|(k, v)| (k.clone(), format!("{:?}", v)))
        .collect();
    
    let output = vm.state.output.clone();
    let error = vm.state.error.as_ref().map(|e| e.zerror.clone());
    drop(vm); // release borrow on host
    
    let result = serde_json::json!({
        "ok": true,
        "output": output,
        "vars": vars,
        "globals": host.entries(),
        "error": error,
    });
    
    serde_json::to_string(&result)
        .map_err(|e| JsValue::from_str(&format!("Serialize result: {}", e)))
}
