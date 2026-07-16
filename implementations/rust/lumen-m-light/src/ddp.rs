//! DdpHost — Host backed by DDP-preloaded data for WASM.

use wasm_bindgen::prelude::*;
use crate::{MemoryHost, Vm, Program, Value, Subscript};

/// Execute M code with preloaded ^GLOBAL data from a DDP server.
/// Detects writes by comparing before/after snapshots.
#[wasm_bindgen]
pub fn m_execute_ddp(compiled: &[u8], globals_json: &str, writable_ns: &str) -> Result<String, JsValue> {
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;
    
    let globals: Vec<crate::GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals: {}", e)))?
    };
    
    let all_writable = writable_ns == "*";
    let writable: Vec<&str> = if all_writable { vec![] } else { writable_ns.split(',').filter(|s| !s.is_empty()).collect() };
    
    let mut host = MemoryHost::from_entries(globals);
    
    // Snapshot pre-execution: store keys AND values
    let before: std::collections::HashMap<(String, Vec<Subscript>), Value> = host.entries()
        .iter()
        .map(|e| ((e.ns.clone(), e.subs.clone()), e.value.clone()))
        .collect();

    let mut vm = Vm::new(program, &mut host);
    vm.run();

    let output = vm.state.output.clone();
    let error = vm.state.error.as_ref().map(|e| e.zerror.clone());
    
    // Detect writes: new entry OR value changed
    let mut writes = Vec::new();
    for entry in host.entries() {
        if !all_writable && !writable.contains(&entry.ns.as_str()) {
            continue;
        }
        let key = (entry.ns.clone(), entry.subs.clone());
        if !before.contains_key(&key) || before.get(&key) != Some(&entry.value) {
            writes.push(serde_json::json!({
                "ns": entry.ns,
                "subs": entry.subs,
                "value": entry.value,
            }));
        }
    }
    
    let result = serde_json::json!({
        "ok": error.is_none(),
        "output": output,
        "writes": writes,
        "error": error,
    });
    
    serde_json::to_string(&result)
        .map_err(|e| JsValue::from_str(&format!("Serialize: {}", e)))
}
