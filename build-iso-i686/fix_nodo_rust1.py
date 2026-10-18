#!/usr/bin/env python3
"""OPCION B (lado NODO): firma DDP CON IDENTIDAD, de forma COMPATIBLE.

Manda las DOS cosas:
   X-DDP-HMAC   -> firma legacy del circulo      (la entiende un hub viejo)
   X-DDP-Node   -> el ID del nodo
   X-DDP-HMAC2  -> HMAC(key, ts + nodo + data + key)   (la entiende un hub nuevo)
Asi funciona con hub viejo Y con hub nuevo, sin cortar nada.
"""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src/ddp_client.rs"
s = open(P, encoding="utf-8").read()

# 1) funcion de firma CON identidad
old1 = '''/// Timestamp (epoch segundos) como string — SystemTime (shim en NAS ✓).'''
new1 = '''/// HMAC-SHA256(key, ts + nodo + data + key) — opcion B: firma que ATA la identidad.
///
/// El hub (vm_api) puede verificarla y saber QUE nodo la manda, en vez de solo
/// saber que "alguien del circulo" la manda. Se manda ADEMAS de la legacy.
pub fn hmac_sign_id(ts: &str, nodo: &str, data: &str, key: &str) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    let mut mac =
        Hmac::<Sha256>::new_from_slice(key.as_bytes()).expect("HMAC acepta claves de cualquier len");
    mac.update(format!("{ts}{nodo}{data}{key}").as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

/// Timestamp (epoch segundos) como string — SystemTime (shim en NAS ✓).'''
assert old1 in s
s = s.replace(old1, new1, 1)

# 2) get_signed con nodo
old2 = '''pub fn get_signed(peer: &str, path: &str, key: &str) -> Result<(u16, String), String> {
    let url = format!("{}{}", peer.trim_end_matches('/'), path);
    let ts = now_ts();
    let sig = if key.is_empty() { String::new() } else { hmac_sign(&ts, path, key) };
    let mut hdrs: Vec<(&str, &str)> = Vec::new();
    if !key.is_empty() {
        hdrs.push(("X-DDP-Timestamp", ts.as_str()));
        hdrs.push(("X-DDP-HMAC", sig.as_str()));
    }
    http_request("GET", &url, None, &hdrs)
}'''
new2 = '''pub fn get_signed(peer: &str, path: &str, key: &str) -> Result<(u16, String), String> {
    get_signed_id(peer, path, key, "")
}

/// GET firmado con IDENTIDAD de nodo (opcion B). `nodo` vacio = solo legacy.
pub fn get_signed_id(
    peer: &str,
    path: &str,
    key: &str,
    nodo: &str,
) -> Result<(u16, String), String> {
    let url = format!("{}{}", peer.trim_end_matches('/'), path);
    let ts = now_ts();
    let sig = if key.is_empty() { String::new() } else { hmac_sign(&ts, path, key) };
    let sig2 = if key.is_empty() || nodo.is_empty() {
        String::new()
    } else {
        hmac_sign_id(&ts, nodo, path, key)
    };
    let mut hdrs: Vec<(&str, &str)> = Vec::new();
    if !key.is_empty() {
        hdrs.push(("X-DDP-Timestamp", ts.as_str()));
        hdrs.push(("X-DDP-HMAC", sig.as_str()));
        if !nodo.is_empty() {
            hdrs.push(("X-DDP-Node", nodo));
            hdrs.push(("X-DDP-HMAC2", sig2.as_str()));
        }
    }
    http_request("GET", &url, None, &hdrs)
}'''
assert old2 in s
s = s.replace(old2, new2, 1)

# 3) post_signed_t con nodo
old3 = '''pub fn post_signed_t(
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
}'''
new3 = '''pub fn post_signed_t(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
    read_timeout_secs: u64,
) -> Result<(u16, String), String> {
    post_signed_id_t(peer, path, body, key, "", read_timeout_secs)
}

/// POST firmado con IDENTIDAD de nodo (opcion B). `nodo` vacio = solo legacy.
pub fn post_signed_id_t(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
    nodo: &str,
    read_timeout_secs: u64,
) -> Result<(u16, String), String> {
    let url = format!("{}{}", peer.trim_end_matches('/'), path);
    let ts = now_ts();
    let sig = if key.is_empty() { String::new() } else { hmac_sign(&ts, body, key) };
    let sig2 = if key.is_empty() || nodo.is_empty() {
        String::new()
    } else {
        hmac_sign_id(&ts, nodo, body, key)
    };
    let mut hdrs: Vec<(&str, &str)> = Vec::new();
    if !key.is_empty() {
        hdrs.push(("X-DDP-Timestamp", ts.as_str()));
        hdrs.push(("X-DDP-HMAC", sig.as_str()));
        if !nodo.is_empty() {
            hdrs.push(("X-DDP-Node", nodo));
            hdrs.push(("X-DDP-HMAC2", sig2.as_str()));
        }
    }
    http_request_t("POST", &url, Some(body), &hdrs, read_timeout_secs)
}'''
assert old3 in s
s = s.replace(old3, new3, 1)

# 4) post_signed (publico, sin timeout) tambien con variante
old4 = '''pub fn post_signed(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
) -> Result<(u16, String), String> {
    post_signed_t(peer, path, body, key, 20)
}'''
new4 = '''pub fn post_signed(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
) -> Result<(u16, String), String> {
    post_signed_t(peer, path, body, key, 20)
}

/// POST firmado con identidad y timeout por defecto.
pub fn post_signed_id(
    peer: &str,
    path: &str,
    body: &str,
    key: &str,
    nodo: &str,
) -> Result<(u16, String), String> {
    post_signed_id_t(peer, path, body, key, nodo, 20)
}'''
assert old4 in s
s = s.replace(old4, new4, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
print("ddp_client.rs OK")
