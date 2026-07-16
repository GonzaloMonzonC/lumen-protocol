//! DdpHost — Host backed by DDP-preloaded data for WASM.
//!
//! Precarga ^GLOBALes via JavaScript (DDP pull), ejecuta M localmente,
//! y devuelve los writes para que JavaScript los pushee al servidor.
//!
//! ## Flow
//! 1. JS: ddp_pull(ns) → decompress LUMEN → JSON
//! 2. JS: m_execute_ddp(compiled, json, writable_ns)
//! 3. JS: ddp_push(writes) → compress LUMEN → send

use wasm_bindgen::prelude::*;
use crate::{Host, MemoryHost, Vm, Program, Value, Subscript};

/// Execute M code with preloaded ^GLOBAL data from a DDP server.
///
/// `compiled`: output of `m_compile` (Uint8Array)
/// `globals_json`: JSON with preloaded ^GLOBALes from ddp_pull
/// `writable_ns`: comma-separated namespaces allowed for writing
///
/// Returns JSON: `{"ok":bool, "output":"...", "writes":[...], "error":null}`
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
    
    let writable: Vec<&str> = writable_ns.split(',').filter(|s| !s.is_empty()).collect();
    
    let mut host = MemoryHost::from_entries(globals);
    
    // Snapshot pre-execution to detect writes
    let before: std::collections::HashSet<(String, Vec<Subscript>)> = host.entries()
        .iter()
        .map(|e| (e.ns.clone(), e.subs.clone()))
        .collect();
    
    let mut vm = Vm::new(program, &mut host);
    vm.run();
    
    let output = vm.state.output.clone();
    let error = vm.state.error.as_ref().map(|e| e.zerror.clone());
    
    // Detect new or modified entries in writable namespaces
    let mut writes = Vec::new();
    for entry in host.entries() {
        if !writable.contains(&entry.ns.as_str()) {
            continue;
        }
        let key = (entry.ns.clone(), entry.subs.clone());
        if !before.contains(&key) {
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
