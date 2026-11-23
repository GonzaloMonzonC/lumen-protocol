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
        .map(|(id, p, m, s, sys)| {
            serde_json::json!([id, p, m, s, sys])
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

/// Ejecuta bytecode M con GLOBALS y RUTINAS.
///
/// `routines_json` es `{"NOMBRE":"source M", ...}`. Sin esto el navegador solo
/// puede ejecutar código inline: `D ETIQUETA^RUTINA` da MROUTINE porque
/// `from_entries()` no carga rutinas.
///
/// Devuelve el mismo JSON de estado que `m_execute`.
#[wasm_bindgen]
pub fn m_execute_routines(
    compiled: &[u8],
    globals_json: &str,
    routines_json: &str,
) -> Result<String, JsValue> {
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;

    let globals: Vec<GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals JSON: {}", e)))?
    };

    let routines: std::collections::HashMap<String, String> =
        if routines_json.is_empty() || routines_json == "{}" {
            std::collections::HashMap::new()
        } else {
            serde_json::from_str(routines_json)
                .map_err(|e| JsValue::from_str(&format!("Parse routines JSON: {}", e)))?
        };

    let mut host = MemoryHost::from_entries(globals);
    for (nombre, src) in routines {
        host.set_routine(&nombre.to_uppercase(), &src);
    }
    let mut vm = Vm::new(program, &mut host);
    vm.state.rng_state = next_rng_seed();
    vm.run();
    store_rng_state(vm.state.rng_state);
    if let Some(error) = &vm.state.error {
        return Err(JsValue::from_str(&format!(
            "M runtime error: {} at line {}", error.ecode, error.line
        )));
    }
    Ok(serde_json::to_string(&vm.state).unwrap_or_default())
}

/// Ejecuta bytecode M con GLOBALS + RUTINAS y devuelve `{state, globals}`.
///
/// `globals` es el array de `GlobalEntry` resultante: el JS debe guardarlo y
/// pasarlo como `globals_json` en la siguiente llamada. Sin esto la PDB del
/// navegador no persiste entre ejecuciones (cada `m_execute*` crea host nuevo).
///
/// Uso desde JS:
///   let { state, globals } = JSON.parse(m.m_execute_routines_out(prog, g, r));
///   // ... siguiente llamada con JSON.stringify(globals)
#[wasm_bindgen]
pub fn m_execute_routines_out(
    compiled: &[u8],
    globals_json: &str,
    routines_json: &str,
) -> Result<String, JsValue> {
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;

    let globals: Vec<GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals JSON: {}", e)))?
    };

    let routines: std::collections::HashMap<String, String> =
        if routines_json.is_empty() || routines_json == "{}" {
            std::collections::HashMap::new()
        } else {
            serde_json::from_str(routines_json)
                .map_err(|e| JsValue::from_str(&format!("Parse routines JSON: {}", e)))?
        };

    let mut host = MemoryHost::from_entries(globals);
    for (nombre, src) in routines {
        host.set_routine(&nombre.to_uppercase(), &src);
    }
    let mut vm = Vm::new(program, &mut host);
    vm.state.rng_state = next_rng_seed();
    vm.run();
    store_rng_state(vm.state.rng_state);

    let err = vm.state.error.as_ref().map(|e| format!("{} at line {}", e.ecode, e.line));
    let state_json = serde_json::to_string(&vm.state).unwrap_or_default();
    drop(vm);

    // Los globals se leen del host, que sigue vivo (Vm solo lo presta).
    let salida_globals = serde_json::to_string(&host.entries()).unwrap_or_else(|_| "[]".into());
    let payload = format!(
        "{{\"state\":{},\"globals\":{},\"error\":{}}}",
        state_json,
        salida_globals,
        match err {
            Some(e) => serde_json::to_string(&e).unwrap_or_else(|_| "null".into()),
            None => "null".to_string(),
        }
    );
    Ok(payload)
}

/// Reanuda una ejecución cedida, con RUTINAS cargadas, y devuelve
/// `{state, globals, error}`.
///
/// `m_execute_resume` no acepta rutinas: al retomar un agente que hace
/// `D ETIQUETA^RUTINA` daría MROUTINE. Esta versión cierra el ciclo completo
/// del navegador: ejecutar -> cede (llm:call) -> m_llm_inject -> reanudar.
#[wasm_bindgen]
pub fn m_execute_resume_routines(
    compiled: &[u8],
    globals_json: &str,
    routines_json: &str,
    state_json: &str,
) -> Result<String, JsValue> {
    let program: Program = serde_json::from_slice(compiled)
        .map_err(|e| JsValue::from_str(&format!("Deserialize bytecode: {}", e)))?;

    let globals: Vec<GlobalEntry> = if globals_json.is_empty() || globals_json == "[]" {
        Vec::new()
    } else {
        serde_json::from_str(globals_json)
            .map_err(|e| JsValue::from_str(&format!("Parse globals JSON: {}", e)))?
    };

    let routines: std::collections::HashMap<String, String> =
        if routines_json.is_empty() || routines_json == "{}" {
            std::collections::HashMap::new()
        } else {
            serde_json::from_str(routines_json)
                .map_err(|e| JsValue::from_str(&format!("Parse routines JSON: {}", e)))?
        };

    let state: crate::vm::VmState = serde_json::from_str(state_json)
        .map_err(|e| JsValue::from_str(&format!("Parse state JSON: {}", e)))?;

    let mut host = MemoryHost::from_entries(globals);
    for (nombre, src) in routines {
        host.set_routine(&nombre.to_uppercase(), &src);
    }
    let mut vm = Vm::resume(program, state, &mut host)
        .map_err(|e| JsValue::from_str(&format!("Resume: {:?}", e)))?;
    vm.run_slice(vm.state.gas_limit);
    store_rng_state(vm.state.rng_state);

    let err = vm.state.error.as_ref().map(|e| format!("{} at line {}", e.ecode, e.line));
    let state_out = serde_json::to_string(&vm.state).unwrap_or_default();
    drop(vm);

    let globals_out = serde_json::to_string(&host.entries()).unwrap_or_else(|_| "[]".into());
    Ok(format!(
        "{{\"state\":{},\"globals\":{},\"error\":{}}}",
        state_out,
        globals_out,
        match err {
            Some(e) => serde_json::to_string(&e).unwrap_or_else(|_| "null".into()),
            None => "null".to_string(),
        }
    ))
}


// ─────────────────────────────────────────────────────────────────────────
// Fachada ASYNC (22-nov-2026)
// ─────────────────────────────────────────────────────────────────────────
//
// QUÉ ES: `m_execute_async` ejecuta M y, cuando el motor cede esperando un
// LLM o una respuesta del usuario, hace el `await` por ti y reanuda. El
// consumidor JS escribe una línea:
//
//     const out = await mvm.run(src, { llm, routines });
//
// QUÉ NO ES: no convierte el VM en async. El motor sigue cediendo como
// siempre; lo que cambia es que el bucle vive aquí en vez de en el JS.
// `vm.rs` no se toca.
//
// CÓMO: `wasm_bindgen_futures::future_to_promise` + `JsFuture`. La función
// devuelve una Promise y va resolviendo turno a turno. El JS que la llama
// puede hacer `await` normal.
//
// LÍMITE: si en el futuro hay `$FIBER` en el navegador, esto NO lo resuelve
// (eso necesita hilos reales). Aquí los fibers siguen dando error limpio.

#[cfg(feature = "wasm")]
use wasm_bindgen::prelude::*;
#[cfg(feature = "wasm")]
use wasm_bindgen_futures::JsFuture;

/// Ejecuta M y resuelve todas las esperas (LLM y usuario) por sí sola.
///
/// Parámetros:
///   - `compiled`: bytecode de `m_compile`.
///   - `globals_json`: globals de la ejecución anterior (`[]` la primera vez).
///   - `routines_json`: mapa `{"NOMBRE": "fuente M"}` o `{}`.
///   - `llm_cb`: `async (id, provider, model, prompt, system) => string`.
///     Si es `null`, cualquier `llm:call` devuelve un error M en vez de colgar.
///   - `user_cb`: `async (id, pregunta) => string`. Opcional.
///
/// Devuelve el JSON `{state, globals, error}` de la última reanudación, o sea
/// el mismo contrato que `m_execute_routines_out` — así el consumidor no
/// cambia nada más.
#[cfg(feature = "wasm")]
#[wasm_bindgen]
pub fn m_execute_async(
    compiled: &[u8],
    globals_json: &str,
    routines_json: &str,
    llm_cb: Option<js_sys::Function>,
    user_cb: Option<js_sys::Function>,
) -> js_sys::Promise {
    let compiled = compiled.to_vec();
    let mut globals = globals_json.to_string();
    let routines = routines_json.to_string();

    wasm_bindgen_futures::future_to_promise(async move {
        // Primer turno: ejecutar desde cero.
        let mut out = m_execute_routines_out(&compiled, &globals, &routines)
            .map_err(|e| e)?;

        // Bucle: mientras ceda, resolver las esperas y reanudar.
        // Tope de vueltas para que un bucle infinito de yields no cuelgue la
        // pestaña: 200 turnos es muchísimo para un agente real.
        let mut vueltas = 0;
        loop {
            vueltas += 1;
            if vueltas > 200 {
                return Err(JsValue::from_str(
                    "m_execute_async: demasiados turnos (¿bucle sin salida?)",
                ));
            }

            let parsed: serde_json::Value = serde_json::from_str(&out)
                .map_err(|e| JsValue::from_str(&format!("JSON de salida: {e}")))?;

            // Guardar globals para el siguiente turno.
            if let Some(g) = parsed.get("globals") {
                globals = g.to_string();
            }

            // ¿Terminó?
            //
            // OJO (medido 22-nov-2026): en WASM `llm:call` NO cede — encola el
            // job con wasm_llm_fork y sigue ejecutando. `execution` puede venir
            // `undefined`, no "yielded". Por eso no basta con mirar execution:
            // hay que procesar los pendientes SIEMPRE que existan, ceda o no.
            let execution = parsed.get("execution").and_then(|v| v.as_str()).unwrap_or("").to_string();

            // ── Jobs de LLM pendientes ────────────────────────────────
            let pendientes = m_llm_pending();
            let jobs: Vec<serde_json::Value> = serde_json::from_str(&pendientes)
                .unwrap_or_else(|_| Vec::new());

            for job in &jobs {
                let id = job.get(0).and_then(|v| v.as_f64()).unwrap_or(0.0);
                let prov = job.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string();
                let model = job.get(2).and_then(|v| v.as_str()).unwrap_or("").to_string();
                let prompt = job.get(3).and_then(|v| v.as_str()).unwrap_or("").to_string();
                let system = job.get(4).and_then(|v| v.as_str()).unwrap_or("").to_string();

                let texto = match &llm_cb {
                    Some(cb) => {
                        let args = js_sys::Array::new();
                        args.push(&JsValue::from_f64(id));
                        args.push(&JsValue::from_str(&prov));
                        args.push(&JsValue::from_str(&model));
                        args.push(&JsValue::from_str(&prompt));
                        args.push(&JsValue::from_str(&system));
                        let p = cb.apply(&JsValue::NULL, &args)
                            .map_err(|e| JsValue::from_str(&format!("llm_cb lanzó: {e:?}")))?;
                        if p.is_null() || p.is_undefined() {
                            String::from("LLM_ERROR: llm_cb no devolvió nada")
                        } else {
                            let v = JsFuture::from(js_sys::Promise::resolve(&p)).await?;
                            v.as_string().unwrap_or_else(|| String::from("LLM_ERROR: respuesta no textual"))
                        }
                    }
                    None => String::from("LLM_ERROR: sin llm_cb (no hay a quién preguntar)"),
                };
                m_llm_inject(id, &texto);
            }

            // ── Jobs de USER pendientes ───────────────────────────────
            let pu = m_user_pending();
            let ujobs: Vec<serde_json::Value> = serde_json::from_str(&pu)
                .unwrap_or_else(|_| Vec::new());
            for job in &ujobs {
                let id = job.get(0).and_then(|v| v.as_f64()).unwrap_or(0.0);
                let pregunta = job.get(1).and_then(|v| v.as_str()).unwrap_or("").to_string();
                let resp = match &user_cb {
                    Some(cb) => {
                        let args = js_sys::Array::new();
                        args.push(&JsValue::from_f64(id));
                        args.push(&JsValue::from_str(&pregunta));
                        let p = cb.apply(&JsValue::NULL, &args)
                            .map_err(|e| JsValue::from_str(&format!("user_cb lanzó: {e:?}")))?;
                        let v = JsFuture::from(js_sys::Promise::resolve(&p)).await?;
                        v.as_string().unwrap_or_default()
                    }
                    None => String::new(),
                };
                m_user_inject(id as u64, &resp);
            }

            // Si no había nada pendiente, no tiene sentido reanudar: el motor
            // cedería por lo mismo otra vez y entraríamos en bucle.
            if jobs.is_empty() && ujobs.is_empty() {
                return Ok(JsValue::from_str(&out));
            }

            // ── Reanudar desde el estado del motor ────────────────────
            //
            // El device llm:call YA hace el ciclo bien: hace poll y, si no hay
            // resultado, marca yield_requested y guarda el id en yield_future.
            // O sea que el motor SÍ cede — lo que no hay que hacer es
            // re-ejecutar desde cero, porque se perdería ese id y volvería a
            // encolar otro job (medido: 7+ llamadas en bucle al llm_cb).
            let state = parsed.get("state").map(|v| v.to_string()).unwrap_or_default();
            out = m_execute_resume_routines(&compiled, &globals, &routines, &state)?;
        }
    })
}
