//! Device `fiber:await` — espera BLOQUEANDO en el host, con timeout.
//!
//! # Por que hace falta
//!
//! `$FIBER("join", id)` hace **yield** cuando el fiber no ha terminado: el VM
//! entero se suspende y devuelve el control al host, que debe llamar a
//! `resume`. Eso encaja en un notebook (hay bucle de resume) o en el servidor
//! MCP (que ya lo implementa), pero **una rutina M no puede "reintentar"**: no
//! hay hilo donde esperar. El control ya salio del VM.
//!
//! Resultado: el pipeline de Smith escrito en M puro no puede recoger los
//! resultados de sus fibers con `$FIBER("join")`.
//!
//! # Por que es seguro bloquear aqui
//!
//! Los fibers corren en **threads propios** (`thread::spawn` dentro de
//! `FiberBgPool`), no en el hilo del VM. Bloquear el hilo del host mientras
//! espera NO impide que los workers resuelvan: son hilos independientes. Lo
//! unico que se detiene es este llamante, que es justo lo que quiere.
//!
//! # Contrato
//!
//! ```text
//! $DEVICE("fiber:await", id, [timeout_ms])
//!   -> el resultado del fiber (string)
//!   -> "" si vence el plazo (el llamante decide que hacer)
//!   -> error si el fiber no existe
//! ```
//!
//! El sondeo es con espera creciente (1ms -> 50ms) para no quemar CPU en
//! esperas cortas ni penalizar las largas.

use crate::host::{Host, MemoryHost};

/// Espera a que un fiber termine. Devuelve `Ok(Some(v))` con el resultado,
/// `Ok(None)` si vence el plazo, o `Err` si el id no existe.
pub fn await_fiber(
    host: &MemoryHost,
    id: u64,
    timeout_ms: u64,
) -> Result<Option<String>, String> {
    if id == 0 {
        return Err("fiber:await necesita un id valido (0 no lo es)".to_string());
    }
    if !host.fiber_bg_exists(id)? {
        return Err(format!("fiber {id} no existe (¿ya se recogio o nunca se lanzo?)"));
    }

    let deadline = std::time::Instant::now() + std::time::Duration::from_millis(timeout_ms);
    let mut espera = 1u64;

    loop {
        if let Some(v) = host.fiber_bg_poll(id)? {
            return Ok(Some(v));
        }
        if std::time::Instant::now() >= deadline {
            return Ok(None);
        }
        let restante = deadline.saturating_duration_since(std::time::Instant::now());
        let dormir = std::time::Duration::from_millis(espera).min(restante);
        dormir_ms(dormir);
        // Backoff: 1,2,4,8,16,32,50,50,...
        espera = (espera * 2).min(50);
    }
}

/// Recoge TODOS los fibers de una lista, devolviendo un JSON
/// `[{"id":N,"ok":bool,"value":"..."}]` en el mismo orden.
///
/// Es la operacion que necesita Smith: lanzar N asesores y recogerlos. El
/// tiempo total se acota por el plazo POR fiber, no por el conjunto: si el
/// primero tarda, los demas ya estan resueltos cuando se llega a ellos.
pub fn await_many(
    host: &MemoryHost,
    ids: &[u64],
    timeout_ms: u64,
) -> Result<String, String> {
    let mut out: Vec<serde_json::Value> = Vec::with_capacity(ids.len());
    for &id in ids {
        match await_fiber(host, id, timeout_ms) {
            Ok(Some(v)) => out.push(serde_json::json!({"id": id, "ok": true, "value": v})),
            Ok(None) => out.push(serde_json::json!({
                "id": id, "ok": false, "value": "", "error": "timeout"
            })),
            Err(e) => out.push(serde_json::json!({
                "id": id, "ok": false, "value": "", "error": e
            })),
        }
    }
    Ok(serde_json::json!({"ok": true, "fibers": out}).to_string())
}

/// Duerme `d` en nativo. En wasm32 no hay hilos: la espera usa un bucle de
/// reloj acotado para no colgar el hilo del navegador (el motor cede por
/// `yield_requested`, no por sleep real).
#[cfg(not(target_arch = "wasm32"))]
fn dormir_ms(d: std::time::Duration) {
    std::thread::sleep(d);
}

#[cfg(target_arch = "wasm32")]
fn dormir_ms(d: std::time::Duration) {
    // En navegador no se bloquea: se deja pasar el tiempo con un spin corto y
    // acotado. El sondeo real lo hace el host JS con m_llm_pending().
    let limite = std::time::Instant::now() + d.min(std::time::Duration::from_millis(2));
    while std::time::Instant::now() < limite {
        std::hint::spin_loop();
    }
}
