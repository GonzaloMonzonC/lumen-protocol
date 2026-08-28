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

// ── RNG global entre ejecuciones (fix 2026-08-28) ─────────────────────────
// El WASM devuelve `state` SOLO cuando hay yield (LLM). Los ticks SIN yield
// reciben state=null → la siguiente llamada hace Vm::new → rng_state se
// re-sembraba por reloj (mismo nanosegundo) → $R(n) devolvía SIEMPRE el
// mismo valor → en el pueblo siempre iniciaba el mismo habitante.
// Este contador global mantiene la secuencia del RNG entre llamadas: cada
// VM nuevo se siembra desde él y al terminar lo actualiza.
static GLOBAL_RNG: std::sync::atomic::AtomicU64 =
    std::sync::atomic::AtomicU64::new(0x9E3779B97F4A7C15);

fn next_rng_seed() -> u64 {
    GLOBAL_RNG.fetch_add(0x9E3779B97F4A7C15, std::sync::atomic::Ordering::Relaxed)
}

fn store_rng_state(state: u64) {
    GLOBAL_RNG.store(state, std::sync::atomic::Ordering::Relaxed);
}

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
    vm.state.rng_state = next_rng_seed();
    vm.run();
    store_rng_state(vm.state.rng_state);
    if let Some(error) = &vm.state.error {
        return Err(JsValue::from_str(&format!(
            "M runtime error: {} at line {}", error.ecode, error.line
        )));
    }
    
    Ok(vm.state.output.clone())
}

/// Jobs LLM pendientes que el JS debe procesar (device WASM sin threads).
/// Devuelve JSON: [[id, provider, model, prompt, system], ...] y los marca como enviados.
#[wasm_bindgen]
pub fn m_llm_pending() -> String {
    let jobs = crate::host::wasm_llm_pending();
    let arr: Vec<serde_json::Value> = jobs
        .into_iter()
        .map(|(id, p, m, s)| {
            serde_json::json!([id, p, m, s])
        })
        .collect();
    serde_json::to_string(&arr).unwrap_or_else(|_| "[]".to_string())
}

/// Jobs USER pendientes: $DEVICE("user:ask", pregunta) → el JS debe mostrar
/// la pregunta al humano. JSON: [[id, pregunta], ...]
#[wasm_bindgen]
pub fn m_user_pending() -> String {
    let jobs = crate::host::wasm_user_pending();
    let arr: Vec<serde_json::Value> = jobs
        .into_iter()
        .map(|(id, p)| serde_json::json!([id, p]))
        .collect();
    serde_json::to_string(&arr).unwrap_or_else(|_| "[]".to_string())
}

/// Inyecta la respuesta del humano al job user id.
#[wasm_bindgen]
pub fn m_user_inject(id: u64, answer: &str) {
    crate::host::wasm_user_inject(id, answer);
}

/// Ejecuta (o REANAUDA con `state_json`) hasta yield o fin. Para el device
/// $DEVICE("llm:call") en WASM: cuando el M pide LLM, run_slice devuelve
/// Yielded; el JS procesa el job con el gateway e inyecta el resultado, luego
/// vuelve a llamar con el state devuelto. Devuelve JSON:
/// {"ok":bool,"yielded":bool,"state":{...}|null,"output":"...","globals":[...],"error":null}
#[wasm_bindgen]
pub fn m_execute_resume(
    compiled: &[u8],
    globals_json: &str,
    state_json: Option<String>,
) -> Result<String, JsValue> {
    use crate::{MemoryHost, Vm};
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;
    let globals: Vec<GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals JSON: {}", e)))?
    };
    let mut host = MemoryHost::from_entries(globals);

    let mut vm = if let Some(state_json) = state_json {
        if state_json.is_empty() || state_json == "null" {
            let mut v = Vm::new(program, &mut host);
            // Fix 2026-08-28: sembrar desde el RNG global → cada tick SIN
            // state obtiene una semilla distinta (antes: reloj → repetía)
            v.state.rng_state = next_rng_seed();
            v
        } else {
            let state: crate::VmState = serde_json::from_str(&state_json)
                .map_err(|e| JsValue::from_str(&format!("Parse state JSON: {}", e)))?;
            Vm::resume(program, state, &mut host)
                .map_err(|e| JsValue::from_str(&format!("Resume error: {}", e.zerror)))?
        }
    } else {
        let mut v = Vm::new(program, &mut host);
        v.state.rng_state = next_rng_seed();
        v
    };

    let execution = vm.run_slice(if vm.state.gas_limit > 0 { vm.state.gas_limit } else { 1_000_000 });
    let yielded = matches!(execution, crate::Execution::Yielded);
    if let Some(error) = &vm.state.error {
        return Err(JsValue::from_str(&format!(
            "M runtime error: {} at line {}", error.ecode, error.line
        )));
    }
    // Fix 2026-08-28: persistir el RNG del VM en el global → el siguiente
    // tick continúa la secuencia aunque no haya yield (state=null).
    store_rng_state(vm.state.rng_state);
    let output = vm.state.output.clone();
    let state = if yielded { Some(serde_json::to_string(&vm.state).unwrap_or_default()) } else { None };
    let vars: std::collections::BTreeMap<String, String> = vm.state.vars
        .iter()
        .map(|(k, v)| (k.clone(), format!("{:?}", v)))
        .collect();
    drop(vm);
    let result = serde_json::json!({
        "ok": true,
        "yielded": yielded,
        "state": state,
        "output": output,
        "vars": vars,
        "globals": host.entries(),
        "error": null,
    });
    serde_json::to_string(&result).map_err(|e| JsValue::from_str(&format!("Serialize result: {}", e)))
}

/// Inyecta el resultado de un job LLM (lo llama el JS tras llamar al gateway).
/// El id se acepta como f64 (JS Number) para evitar BigInt en el glue.
#[wasm_bindgen]
pub fn m_llm_inject(id: f64, result: &str) {
    crate::host::wasm_llm_inject(id as u64, result);
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
    vm.state.rng_state = next_rng_seed();
    vm.run();
    store_rng_state(vm.state.rng_state);
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
