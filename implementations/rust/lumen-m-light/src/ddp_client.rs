//! Cliente DDP mínimo para nodos (LAN, HTTP plano, HMAC legacy `ts + data + key`).
//!
//! Deliberadamente SIN TLS ni dependencias nuevas: `TcpStream` + los crates ya
//! presentes (hmac/sha2/hex). Contraparte: `vm_api.py` (:8081) del hub.
//! - GET  → firma el path+query EXACTO que viaja en la request line
//! - POST → firma el BODY EXACTO que viaja (byte a byte)
//! Timestamp: epoch en segundos (string), ventana ±120 s en el server.

use std::io::{Read, Write};
use std::net::{TcpStream, ToSocketAddrs};
use std::time::Duration;

/// HMAC-SHA256(key, ts + data + key) en hex — esquema legacy de vm_api/poli.
pub fn hmac_sign(ts: &str, data: &str, key: &str) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut mac =
        Hmac::<Sha256>::new_from_slice(key.as_bytes()).expect("HMAC acepta claves de cualquier len");
    mac.update(format!("{ts}{data}{key}").as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// Timestamp (epoch segundos) como string — SystemTime (shim en NAS ✓).
pub fn now_ts() -> String {
    match std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH) {
        Ok(d) => d.as_secs().to_string(),
        Err(_) => "0".to_string(),
    }
}

/// Percent-encoding mínimo para valores de query (subs de ns).
pub fn urlenc(s: &str) -> String {
    let mut out = String::new();
    for b in s.bytes() {
        match b {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'-' | b'.' | b'~' => {
                out.push(b as char)
            }
            _ => out.push_str(&format!("%{:02X}", b)),
        }
    }
    out
}

fn split_url(url: &str) -> Result<(String, u16, String), String> {
    let rest = url
        .strip_prefix("http://")
        .ok_or_else(|| format!("DDP: solo http:// soportado (LAN sin TLS): {url}"))?;
    let (hostport, path) = match rest.find('/') {
        Some(i) => (&rest[..i], &rest[i..]),
        None => (rest, "/"),
    };
    let (host, port) = match hostport.rsplit_once(':') {
        Some((h, p)) => (
            h.to_string(),
            p.parse::<u16>()
                .map_err(|_| format!("DDP: puerto inválido en {hostport}"))?,
        ),
        None => (hostport.to_string(), 80),
    };
    Ok((host, port, path.to_string()))
}

/// HTTP/1.1 mínimo con `Connection: close`. Devuelve (status, body).
pub fn http_request(
    method: &str,
    url: &str,
    body: Option<&str>,
    headers: &[(&str, &str)],
) -> Result<(u16, String), String> {
    http_request_t(method, url, body, headers, 20)
}

/// Igual que `http_request` con timeout de lectura explícito (segundos).
/// F5 (14-sep-2026): las llamadas de "voz prestada" al hub pueden tardar
/// (el agente destino piensa) → 120 s en vez de 20 s. El resto de rutas
/// (pull/push/health) mantienen su timeout corto.
pub fn http_request_t(
    method: &str,
    url: &str,
    body: Option<&str>,
    headers: &[(&str, &str)],
    read_timeout_secs: u64,
) -> Result<(u16, String), String> {
    let (host, port, path) = split_url(url)?;
    let addr = format!("{host}:{port}");
    let sock = addr
        .to_socket_addrs()
        .map_err(|e| format!("DDP: resolve {addr}: {e}"))?
        .next()
        .ok_or_else(|| format!("DDP: sin dirección para {addr}"))?;
    let mut stream = TcpStream::connect_timeout(&sock, Duration::from_secs(5))
        .map_err(|e| format!("DDP: conecta {addr}: {e}"))?;
    let _ = stream.set_read_timeout(Some(Duration::from_secs(read_timeout_secs)));
    let _ = stream.set_write_timeout(Some(Duration::from_secs(10)));

    let mut req = String::new();
    req.push_str(&format!("{method} {path} HTTP/1.1\r\n"));
    req.push_str(&format!("Host: {host}\r\n"));
    req.push_str("User-Agent: mvm-nas-ddp/0.1\r\nAccept: application/json\r\nConnection: close\r\n");
    if let Some(b) = body {
        req.push_str("Content-Type: application/json\r\n");
        req.push_str(&format!("Content-Length: {}\r\n", b.as_bytes().len()));
    }
    for (k, v) in headers {
        req.push_str(&format!("{k}: {v}\r\n"));
    }
    req.push_str("\r\n");

    stream
        .write_all(req.as_bytes())
        .map_err(|e| format!("DDP: escribe {addr}: {e}"))?;
    if let Some(b) = body {
        stream
            .write_all(b.as_bytes())
            .map_err(|e| format!("DDP: escribe body {addr}: {e}"))?;
    }
    let _ = stream.flush();

    let mut buf = Vec::new();
    stream
        .read_to_end(&mut buf)
        .map_err(|e| format!("DDP: lee {addr}: {e}"))?;
    let text = String::from_utf8_lossy(&buf).into_owned();
    let (head, resp_body) = text.split_once("\r\n\r\n").ok_or_else(|| {
        let preview: String = text.chars().take(120).collect();
        format!("DDP: respuesta HTTP inválida: {preview}")
    })?;
    let status = head
        .lines()
        .next()
        .and_then(|l| l.split_whitespace().nth(1))
        .and_then(|s| s.parse::<u16>().ok())
        .ok_or_else(|| "DDP: status HTTP ilegible".to_string())?;
    Ok((status, resp_body.to_string()))
}

/// GET firmado: firma sobre el path+query EXACTO (así lo verifica vm_api).
pub fn get_signed(peer: &str, path: &str, key: &str) -> Result<(u16, String), String> {
    let url = format!("{}{}", peer.trim_end_matches('/'), path);
    let ts = now_ts();
    let sig = if key.is_empty() { String::new() } else { hmac_sign(&ts, path, key) };
    let mut hdrs: Vec<(&str, &str)> = Vec::new();
    if !key.is_empty() {
        hdrs.push(("X-DDP-Timestamp", ts.as_str()));
        hdrs.push(("X-DDP-HMAC", sig.as_str()));
    }
    http_request("GET", &url, None, &hdrs)
}

/// POST firmado: firma sobre el BODY EXACTO (así lo verifica vm_api).
pub fn post_signed(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
) -> Result<(u16, String), String> {
    post_signed_t(peer, path, body, key, 20)
}

/// POST firmado con timeout de lectura explícito (segundos).
pub fn post_signed_t(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
    read_timeout_secs: u64,
) -> Result<(u16, String), String> {
    let url = format!("{}{}", peer.trim_end_matches('/'), path);
    let ts = now_ts();
    let sig = if key.is_empty() { String::new() } else { hmac_sign(&ts, body, key) };
    let mut hdrs: Vec<(&str, &str)> = Vec::new();
    if !key.is_empty() {
        hdrs.push(("X-DDP-Timestamp", ts.as_str()));
        hdrs.push(("X-DDP-HMAC", sig.as_str()));
    }
    http_request_t("POST", &url, Some(body), &hdrs, read_timeout_secs)
}

/// F5: "voz prestada" — el hub (vm_api) espera hasta 90 s al agente
/// destino; damos 120 s de margen de lectura.
pub fn post_signed_llm(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
) -> Result<(u16, String), String> {
    post_signed_t(peer, path, body, key, 120)
}
