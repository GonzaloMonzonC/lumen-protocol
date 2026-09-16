//! Device SSH (PoC 16-sep-2026) — "manos" para las MVMs.
//!
//! `$DEVICE("ssh:exec", "user@host", "comando", [timeout_s])`
//!
//! - Usa el cliente `ssh` del sistema (OpenSSH/dropbear) en modo BatchMode:
//!   la autenticación va por claves de `~/.ssh` del usuario que corre la MVM
//!   (nunca passwords en código ni en la PDB).
//! - **Fail-closed**: sin `^CONFIG("ssh_allow")` el device está DESHABILITADO
//!   (ni siquiera localhost). Con la clave presente: localhost siempre + los
//!   destinos de la lista (separada por comas, "user@host"). Así una
//!   instancia nueva (p.ej. neferu, la cara pública de los libros) nace sin
//!   manos sin tocar nada más — mismo binario, otra BD.
//! - Timeout duro (default 15 s, máx 120 s) y cap de salida (4 KB) con drenado
//!   del resto para que el proceso remoto nunca bloquee el pipe.
//!
//! Feature-gated (`ssh`): no entra en WASM ni en builds que no la activen.
//! Requiere `std::process` (nativo). Idea original de Gonzalo (15-sep-2026):
//! «quiero las MVM tengan un Device telnet o ssh para acceder a sistemas».

use std::io::Read;
use std::process::{Command, Stdio};
use std::time::{Duration, Instant};

use crate::host::{Host, MemoryHost};
use crate::value::{Subscript, Value};

const OUT_CAP: usize = 4096;

/// `$DEVICE("ssh:exec", destino, comando, [timeout_s])`
pub fn ssh_exec(host: &MemoryHost, args: &[Value]) -> Result<Value, String> {
    let target = args.first().map(|v| v.as_string()).unwrap_or_default();
    let cmd = args.get(1).map(|v| v.as_string()).unwrap_or_default();
    if target.is_empty() || cmd.is_empty() {
        return Err(
            "uso: $DEVICE(\"ssh:exec\",\"user@host\",\"comando\",[timeout_s])".to_string(),
        );
    }
    if target.contains(char::is_whitespace) || target.contains('\0') || cmd.contains('\0') {
        return Err("ssh: argumentos inválidos (espacios/NUL en destino o comando)".to_string());
    }
    let timeout_s: u64 = args
        .get(2)
        .map(|v| v.as_number() as u64)
        .unwrap_or(15)
        .clamp(1, 120);

    match allow_state(host, &target) {
        AllowState::Ok => {}
        AllowState::NoConfig => {
            return Err(
                "ssh: device deshabilitado — define ^CONFIG(\"ssh_allow\") (lista de destinos permitidos)"
                    .to_string(),
            )
        }
        AllowState::Denied => {
            return Err(format!(
                "ssh: destino '{target}' no permitido — añádelo a ^CONFIG(\"ssh_allow\") (lista separada por comas)"
            ))
        }
    }

    let mut child = Command::new("ssh")
        .args([
            "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=8",
            "-o", "StrictHostKeyChecking=accept-new",
            "-o", "ServerAliveInterval=5",
            "-o", "ServerAliveCountMax=2",
            "--",
            target.as_str(),
            cmd.as_str(),
        ])
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .map_err(|e| format!("ssh: no se pudo lanzar el cliente ssh: {e}"))?;

    let t_out = child.stdout.take().map(drain_thread);
    let t_err = child.stderr.take().map(drain_thread);

    let start = Instant::now();
    let mut killed = false;
    let status = loop {
        match child.try_wait() {
            Ok(Some(st)) => break Some(st),
            Ok(None) => {
                if start.elapsed() > Duration::from_secs(timeout_s) {
                    let _ = child.kill();
                    let _ = child.wait();
                    killed = true;
                    break None;
                }
                std::thread::sleep(Duration::from_millis(80));
            }
            Err(e) => return Err(format!("ssh: error esperando al cliente: {e}")),
        }
    };

    let mut text = String::new();
    if let Some(t) = t_out {
        if let Ok(bytes) = t.join() {
            text.push_str(&String::from_utf8_lossy(&bytes));
        }
    }
    let mut err_text = String::new();
    if let Some(t) = t_err {
        if let Ok(bytes) = t.join() {
            err_text.push_str(&String::from_utf8_lossy(&bytes));
        }
    }
    if !err_text.trim().is_empty() {
        if !text.is_empty() && !text.ends_with('\n') {
            text.push('\n');
        }
        text.push_str("stderr: ");
        text.push_str(err_text.trim());
    }

    if killed {
        return Ok(Value::String(format!(
            "ssh: timeout de {timeout_s}s en {target} (proceso terminado)\n{}",
            cap(&text)
        )));
    }

    let rc = status.and_then(|s| s.code()).unwrap_or(-1);
    let mut out = text.trim_end().to_string();
    if out.is_empty() {
        out = format!("(sin salida; rc={rc})");
    } else if rc != 0 {
        out.push_str(&format!("\n[ssh rc={rc}]"));
    }
    Ok(Value::String(cap(&out)))
}

/// Recorta a OUT_CAP chars (seguro en UTF-8) con marca de truncado.
fn cap(s: &str) -> String {
    if s.chars().count() <= OUT_CAP {
        return s.to_string();
    }
    let mut out: String = s.chars().take(OUT_CAP).collect();
    out.push_str(" […truncado]");
    out
}

enum AllowState {
    Ok,
    NoConfig,
    Denied,
}

/// Fail-closed: sin `^CONFIG("ssh_allow")` (o vacía) → NoConfig (ssh apagado).
/// Con lista → localhost siempre + los destinos exactos de la lista.
fn allow_state(host: &MemoryHost, target: &str) -> AllowState {
    let list = match host.get("CONFIG", &[Subscript::String("ssh_allow".to_string())]) {
        Ok(Some(v)) => v.as_string(),
        _ => return AllowState::NoConfig,
    };
    if list.trim().is_empty() {
        return AllowState::NoConfig;
    }
    let hostpart = target.rsplit('@').next().unwrap_or(target);
    if hostpart == "localhost" || hostpart == "127.0.0.1" || hostpart == "::1" {
        return AllowState::Ok;
    }
    if list.split(',').map(|s| s.trim()).any(|t| t == target) {
        AllowState::Ok
    } else {
        AllowState::Denied
    }
}

/// Hilo lector: drena el pipe completo (sin bloquear al remoto) y conserva
/// solo los primeros OUT_CAP bytes.
fn drain_thread(mut pipe: impl Read + Send + 'static) -> std::thread::JoinHandle<Vec<u8>> {
    std::thread::spawn(move || {
        let mut kept: Vec<u8> = Vec::new();
        let mut chunk = [0u8; 8192];
        loop {
            match pipe.read(&mut chunk) {
                Ok(0) => break,
                Ok(n) => {
                    if kept.len() < OUT_CAP {
                        let room = OUT_CAP - kept.len();
                        let take = n.min(room);
                        kept.extend_from_slice(&chunk[..take]);
                    }
                }
                Err(_) => break,
            }
        }
        kept
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn host_with_allow(list: &str) -> MemoryHost {
        let mut h = MemoryHost::default();
        if !list.is_empty() {
            h.set(
                "CONFIG",
                &[Subscript::String("ssh_allow".to_string())],
                Value::String(list.to_string()),
            )
            .unwrap();
        }
        h
    }

    #[test]
    fn fail_closed_sin_config() {
        let h = host_with_allow("");
        // Sin ^CONFIG("ssh_allow") ni siquiera localhost: device apagado.
        let args = vec![
            Value::String("localhost".to_string()),
            Value::String("uptime".to_string()),
        ];
        let err = ssh_exec(&h, &args).unwrap_err();
        assert!(err.contains("deshabilitado"), "err: {err}");
        assert!(matches!(allow_state(&h, "localhost"), AllowState::NoConfig));
    }

    #[test]
    fn con_config_localhost_y_lista() {
        let h = host_with_allow("nasdedavid@192.168.1.14, root@10.0.0.2");
        assert!(matches!(allow_state(&h, "nasdedavid@localhost"), AllowState::Ok));
        assert!(matches!(allow_state(&h, "user@127.0.0.1"), AllowState::Ok));
        assert!(matches!(allow_state(&h, "nasdedavid@192.168.1.14"), AllowState::Ok));
        assert!(matches!(allow_state(&h, "root@10.0.0.2"), AllowState::Ok));
        assert!(matches!(allow_state(&h, "root@10.0.0.3"), AllowState::Denied));
    }

    #[test]
    fn uso_incorrecto() {
        let h = host_with_allow("");
        let err = ssh_exec(&h, &[]).unwrap_err();
        assert!(err.contains("uso:"));
    }

    #[test]
    fn destino_no_permitido() {
        let h = host_with_allow("user@10.1.1.1");
        let args = vec![
            Value::String("user@10.9.9.9".to_string()),
            Value::String("uptime".to_string()),
        ];
        let err = ssh_exec(&h, &args).unwrap_err();
        assert!(err.contains("no permitido"));
    }
}
