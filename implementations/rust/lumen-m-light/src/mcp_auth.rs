//! Autenticación HMAC del servidor MCP — esquema del ecosistema DDP.
//!
//! Mismo contrato que el resto de servidores del ecosistema, para que los
//! clientes existentes (`hmac_client.py`, workers CF, poli :8082) sirvan tal
//! cual contra el MVM:
//!
//! ```text
//! HMAC-SHA256( timestamp + nonce + body + secret )   (hex)
//!
//! Headers:  X-DDP-Timestamp (epoch segundos)
//!           X-DDP-Nonce     (opcional; si va, entra en el cómputo)
//!           X-DDP-HMAC
//! ```
//!
//! # Política escalonada
//!
//! El servidor decide su modo al arrancar, según haya clave o no:
//!
//! | Clave | Escucha en | Escritura | Firma |
//! |-------|-----------|-----------|-------|
//! | sí    | lo que se pida | permitida | **obligatoria** |
//! | no    | **solo `127.0.0.1`** | `tools/call` denegado | n/a |
//!
//! Sin clave el servidor **no queda abierto**: queda en modo lectura y
//! enlazado a loopback. Es la diferencia con el patrón «sin clave → bypass»
//! de los servidores Python antiguos, que en un panel de administración sería
//! una puerta abierta.

use hmac::{Hmac, Mac};
use sha2::Sha256;
use std::collections::HashSet;
use std::net::IpAddr;
use std::sync::Mutex;
use std::time::{SystemTime, UNIX_EPOCH};

type HmacSha256 = Hmac<Sha256>;

/// Ventana de tolerancia del timestamp, en segundos (igual que el ecosistema).
const MAX_AGE_SECS: i64 = 120;

/// Nonces ya vistos (anti-replay). En memoria: un reinicio lo vacía, y eso es
/// correcto — los nonces viejos caducan solos con la ventana del timestamp.
static SEEN_NONCES: Mutex<Option<HashSet<String>>> = Mutex::new(None);

/// Modo de operación del servidor, decidido al arrancar.
#[derive(Clone, Debug, PartialEq)]
pub enum AuthMode {
    /// Sin clave configurada: solo loopback y solo lectura.
    ReadOnlyLocal,
    /// Con clave: firma obligatoria en toda petición POST.
    Signed,
}

impl AuthMode {
    /// Decide el modo a partir de la clave (vacía = sin auth).
    pub fn from_key(key: &str) -> Self {
        if key.trim().is_empty() {
            AuthMode::ReadOnlyLocal
        } else {
            AuthMode::Signed
        }
    }

    /// ¿Se puede ejecutar `tools/call` en este modo?
    pub fn allows_write(&self) -> bool {
        matches!(self, AuthMode::Signed)
    }

    /// Dirección de escucha efectiva.
    ///
    /// En modo lectura se fuerza loopback aunque el usuario pida `0.0.0.0`:
    /// si no hay auth, el servidor no debe ser alcanzable desde la red.
    pub fn effective_bind(&self, requested_host: &str) -> String {
        match self {
            AuthMode::ReadOnlyLocal => "127.0.0.1".to_string(),
            AuthMode::Signed => requested_host.to_string(),
        }
    }
}

/// Comprueba si una IP de origen es local (loopback).
pub fn is_loopback(addr: &IpAddr) -> bool {
    addr.is_loopback()
}

fn now_secs() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}

/// Verifica una petición firmada.
///
/// - `headers`: pares (nombre, valor) ya recibidos.
/// - `raw_body`: el cuerpo **exacto** que viajó (la firma se calcula sobre esto,
///   no sobre un JSON reserializado — reserializar cambia espacios y rompe la
///   verificación; es el error clásico de este esquema).
pub fn verify(headers: &[(String, String)], raw_body: &str, secret: &str) -> Result<(), String> {
    if secret.trim().is_empty() {
        return Err("servidor sin clave configurada".to_string());
    }

    let get = |name: &str| -> Option<String> {
        headers
            .iter()
            .find(|(k, _)| k.eq_ignore_ascii_case(name))
            .map(|(_, v)| v.trim().to_string())
    };

    let ts_str = get("X-DDP-Timestamp").ok_or("falta X-DDP-Timestamp")?;
    let sig = get("X-DDP-HMAC").ok_or("falta X-DDP-HMAC")?;
    let nonce = get("X-DDP-Nonce");

    let ts: i64 = ts_str.parse().map_err(|_| "X-DDP-Timestamp no es numerico")?;
    let drift = (now_secs() - ts).abs();
    if drift > MAX_AGE_SECS {
        return Err(format!(
            "timestamp fuera de ventana ({drift}s, max {MAX_AGE_SECS}s) — \
             comprobar el reloj del cliente"
        ));
    }

    // Anti-replay por nonce. Solo se registra DESPUÉS de validar la firma, para
    // que un atacante no pueda quemar nonces legítimos sin conocer la clave.
    let message = match &nonce {
        Some(n) if !n.is_empty() => format!("{ts_str}{n}{raw_body}{secret}"),
        _ => format!("{ts_str}{raw_body}{secret}"), // legacy: ts + body + key
    };

    let mut mac = HmacSha256::new_from_slice(secret.as_bytes())
        .map_err(|_| "clave HMAC invalida".to_string())?;
    mac.update(message.as_bytes());
    let expected = hex::encode(mac.finalize().into_bytes());

    if !constant_time_eq(expected.as_bytes(), sig.to_ascii_lowercase().as_bytes()) {
        return Err("firma HMAC invalida".to_string());
    }

    if let Some(n) = nonce {
        if !n.is_empty() {
            let mut guard = SEEN_NONCES.lock().unwrap_or_else(|e| e.into_inner());
            let set = guard.get_or_insert_with(HashSet::new);
            if !set.insert(n.clone()) {
                return Err("nonce ya usado (posible replay)".to_string());
            }
            // Limpieza simple: si crece demasiado, se vacía (los viejos ya
            // habrían caducado por timestamp).
            if set.len() > 10_000 {
                set.clear();
                set.insert(n);
            }
        }
    }

    Ok(())
}

/// Comparación en tiempo constante (evita filtrar la firma por timing).
fn constant_time_eq(a: &[u8], b: &[u8]) -> bool {
    if a.len() != b.len() {
        return false;
    }
    let mut diff = 0u8;
    for (x, y) in a.iter().zip(b.iter()) {
        diff |= x ^ y;
    }
    diff == 0
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sign(secret: &str, ts: &str, nonce: Option<&str>, body: &str) -> String {
        let msg = match nonce {
            Some(n) if !n.is_empty() => format!("{ts}{n}{body}{secret}"),
            _ => format!("{ts}{body}{secret}"),
        };
        let mut mac = HmacSha256::new_from_slice(secret.as_bytes()).unwrap();
        mac.update(msg.as_bytes());
        hex::encode(mac.finalize().into_bytes())
    }

    fn hdrs(ts: &str, sig: &str, nonce: Option<&str>) -> Vec<(String, String)> {
        let mut v = vec![
            ("X-DDP-Timestamp".to_string(), ts.to_string()),
            ("X-DDP-HMAC".to_string(), sig.to_string()),
        ];
        if let Some(n) = nonce {
            v.push(("X-DDP-Nonce".to_string(), n.to_string()));
        }
        v
    }

    #[test]
    fn acepta_firma_valida_con_nonce() {
        let key = "clave-de-prueba";
        let ts = now_secs().to_string();
        let body = r#"{"jsonrpc":"2.0","id":1,"method":"tools/list"}"#;
        let sig = sign(key, &ts, Some("abc123"), body);
        assert!(verify(&hdrs(&ts, &sig, Some("abc123")), body, key).is_ok());
    }

    #[test]
    fn acepta_legacy_sin_nonce() {
        let key = "clave-de-prueba";
        let ts = now_secs().to_string();
        let body = "{}";
        let sig = sign(key, &ts, None, body);
        assert!(verify(&hdrs(&ts, &sig, None), body, key).is_ok());
    }

    #[test]
    fn rechaza_firma_incorrecta() {
        let ts = now_secs().to_string();
        let body = "{}";
        let sig = sign("otra-clave", &ts, None, body);
        assert!(verify(&hdrs(&ts, &sig, None), body, "clave-de-prueba").is_err());
    }

    #[test]
    fn rechaza_sin_headers() {
        assert!(verify(&[], "{}", "clave").is_err());
    }

    #[test]
    fn rechaza_timestamp_viejo() {
        let key = "k";
        let ts = (now_secs() - MAX_AGE_SECS - 10).to_string();
        let body = "{}";
        let sig = sign(key, &ts, None, body);
        let e = verify(&hdrs(&ts, &sig, None), body, key).unwrap_err();
        assert!(e.contains("ventana"), "{e}");
    }

    #[test]
    fn rechaza_body_manipulado() {
        let key = "k";
        let ts = now_secs().to_string();
        let sig = sign(key, &ts, None, "{\"a\":1}");
        // Mismo ts y firma, body distinto -> debe fallar
        assert!(verify(&hdrs(&ts, &sig, None), "{\"a\":2}", key).is_err());
    }

    #[test]
    fn rechaza_replay_de_nonce() {
        let key = "k";
        let ts = now_secs().to_string();
        let body = "{}";
        let nonce = "nonce-unico-replay-test";
        let sig = sign(key, &ts, Some(nonce), body);
        assert!(verify(&hdrs(&ts, &sig, Some(nonce)), body, key).is_ok());
        // Segunda vez con el mismo nonce -> replay
        assert!(verify(&hdrs(&ts, &sig, Some(nonce)), body, key).is_err());
    }

    #[test]
    fn modo_escalonado() {
        assert_eq!(AuthMode::from_key(""), AuthMode::ReadOnlyLocal);
        assert_eq!(AuthMode::from_key("  "), AuthMode::ReadOnlyLocal);
        assert_eq!(AuthMode::from_key("k"), AuthMode::Signed);
        assert!(!AuthMode::ReadOnlyLocal.allows_write());
        assert!(AuthMode::Signed.allows_write());
        // sin clave NO puede escuchar en 0.0.0.0
        assert_eq!(AuthMode::ReadOnlyLocal.effective_bind("0.0.0.0"), "127.0.0.1");
        assert_eq!(AuthMode::Signed.effective_bind("0.0.0.0"), "0.0.0.0");
    }
}
