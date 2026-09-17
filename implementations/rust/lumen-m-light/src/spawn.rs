//! Device spawn:run (18-sep-2026) — el nodo se lanza a SÍ MISMO en subproceso.
//!
//! `$DEVICE("spawn:run", "<codigo M>", [timeout_s=10])`
//! - Ejecuta el código en un proceso hijo del MISMO binario (`-e`), con la
//!   misma PDB y rutinas (vía ^SYSINFO("pdb"/"routines_dir")).
//! - **Timeout duro**: si el hijo no termina, se le MATA y se devuelve
//!   `TIMEOUT: ...` — el cuelgue (bucle infinito del código generado) deja de
//!   ser un problema: el sandbox lo caza y el resultado es feedback.
//! - Salida: `exit=0\n<salida>` o `exit!=0\n<salida+stderr>` o `TIMEOUT: ...`.
//! - Seguridad: mismo dominio de confianza que el nodo (su propio código),
//!   pero AISLADO en proceso → sin estado corrupto, sin cuelgues del padre.
//!
//! Feature `spawn` (nativo, fuera de WASM).

use std::process::Command;
use std::time::{Duration, Instant};

use crate::host::MemoryHost;
use crate::value::{Subscript, Value};

pub fn spawn_device(host: &mut MemoryHost, action: &str, args: &[Value]) -> Result<Value, String> {
    match action {
        "run" => spawn_run(host, args),
        _ => Err(format!("[SPAWN] acción desconocida: {action} (usa \"run\")")),
    }
}

fn sysinfo_str(host: &MemoryHost, key: &str) -> String {
    host.values
        .get(&(
            "SYSINFO".to_string(),
            vec![Subscript::String(key.to_string())],
        ))
        .map(|v| v.as_string())
        .unwrap_or_default()
}

fn spawn_run(host: &mut MemoryHost, args: &[Value]) -> Result<Value, String> {
    let code = args.first().map(|v| v.as_string()).unwrap_or_default();
    if code.trim().is_empty() {
        return Err("[SPAWN] uso: $DEVICE(\"spawn:run\",\"<codigo M>\",[timeout_s])".to_string());
    }
    let timeout = args
        .get(1)
        .map(|v| v.as_number())
        .filter(|n| *n > 0.0) // arg vacío (""→0) ⇒ usar default, no 1s
        .unwrap_or(10.0)
        .clamp(1.0, 120.0);
    let exe = std::env::current_exe().map_err(|e| format!("[SPAWN] current_exe: {e}"))?;
    let pdb = sysinfo_str(host, "pdb");
    let dir = sysinfo_str(host, "routines_dir");
    if pdb.is_empty() || dir.is_empty() {
        return Err("[SPAWN] sin ^SYSINFO(\"pdb\"/\"routines_dir\") — ¿arrancado con -p/-r?".to_string());
    }
    let base = std::path::Path::new(&dir).parent().map(|p| p.to_path_buf());
    let mut cmd = Command::new(&exe);
    cmd.arg("-p")
        .arg(&pdb)
        .arg("-r")
        .arg(&dir)
        .arg("-e")
        .arg(&code)
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped());
    // Con rutas relativas (las típicas: -p mini-pdb.db -r routines) la "base"
    // queda vacía → NO tocar current_dir: el hijo hereda el cwd del padre
    // (que ya es la carpeta del nodo). Fix 18-sep: antes error 123 en Windows.
    if let Some(b) = base.filter(|b| !b.as_os_str().is_empty()) {
        cmd.current_dir(b);
    }
    let mut child = cmd
        .spawn()
        .map_err(|e| format!("[SPAWN] spawn: {e}"))?;
    let start = Instant::now();
    let deadline = Duration::from_secs_f64(timeout);
    loop {
        match child.try_wait() {
            Ok(Some(_)) => break,
            Ok(None) => {
                if start.elapsed() > deadline {
                    let _ = child.kill();
                    let _ = child.wait();
                    return Ok(Value::String(format!(
                        "TIMEOUT: el codigo no termino en {timeout}s (posible bucle infinito) — hijo cancelado"
                    )));
                }
                std::thread::sleep(Duration::from_millis(80));
            }
            Err(e) => return Err(format!("[SPAWN] wait: {e}")),
        }
    }
    let out = child
        .wait_with_output()
        .map_err(|e| format!("[SPAWN] output: {e}"))?;
    let mut s = String::from_utf8_lossy(&out.stdout).to_string();
    let err = String::from_utf8_lossy(&out.stderr);
    if !err.trim().is_empty() {
        s.push_str("\n[stderr] ");
        s.push_str(&err);
    }
    let code_txt = if out.status.success() { "exit=0" } else { "exit!=0" };
    if s.len() > 8000 {
        s.truncate(8000);
        s.push('…');
    }
    Ok(Value::String(format!("{code_txt}\n{s}")))
}
