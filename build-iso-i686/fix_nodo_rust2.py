#!/usr/bin/env python3
"""host.rs: ddp_cfg devuelve tambien la IDENTIDAD del nodo, y las llamadas la usan."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src/host.rs"
s = open(P, encoding="utf-8").read()

# 1) ddp_cfg -> (peer, key, nodo)
old1 = '''/// Lee `^CONFIG("ddp_peer")` + `^CONFIG("ddp_hmac_key")` del host (F2 — hub DDP).
fn ddp_cfg(host: &MemoryHost) -> Result<(String, String), String> {'''
new1 = '''/// Lee `^CONFIG("ddp_peer")` + `^CONFIG("ddp_hmac_key")` + la IDENTIDAD del nodo.
///
/// La identidad (opcion B) sale de `^CONFIG("nodo_id")`; si no esta, de
/// `^SYS("NODO")` — que el init fija al arrancar desde el DMI de la maquina
/// (Asus 1005HA, Acer TravelMate 4000...). Se sanea para que valga como cabecera.
fn ddp_cfg(host: &MemoryHost) -> Result<(String, String, String), String> {'''
assert old1 in s
s = s.replace(old1, new1, 1)

old2 = '''    Ok((peer, key))
}'''
new2 = '''    let crudo = match host.get("CONFIG", &[Subscript::String("nodo_id".to_string())]) {
        Ok(Some(v)) if !v.as_string().trim().is_empty() => v.as_string(),
        _ => match host.get("SYS", &[Subscript::String("NODO".to_string())]) {
            Ok(Some(v)) => v.as_string(),
            _ => String::new(),
        },
    };
    // saneado: letras/numeros/._- y todo lo demas a un guion (vale como cabecera)
    let mut nodo = String::new();
    let mut guion = false;
    for c in crudo.trim().chars() {
        if c.is_ascii_alphanumeric() || c == '.' || c == '_' || c == '-' {
            nodo.push(c);
            guion = false;
        } else if !guion {
            nodo.push('-');
            guion = true;
        }
    }
    let nodo = nodo.trim_matches('-').to_string();
    Ok((peer, key, nodo))
}'''
assert old2 in s, "no encontre el Ok((peer, key))"
s = s.replace(old2, new2, 1)

# 2) los 5 sitios que reciben la tupla
n = s.count("let (peer, key) = ddp_cfg(")
s = s.replace("let (peer, key) = ddp_cfg(", "let (peer, key, nodo) = ddp_cfg(")
print(f"call sites de ddp_cfg actualizados: {n}")

# 3) las llamadas firmadas -> variantes con identidad
reps = [
    ("crate::ddp_client::get_signed(&peer, &path, &key)?",
     "crate::ddp_client::get_signed_id(&peer, &path, &key, &nodo)?"),
    ('crate::ddp_client::get_signed(&peer, "/ddp/health", &key)?',
     'crate::ddp_client::get_signed_id(&peer, "/ddp/health", &key, &nodo)?'),
    ('crate::ddp_client::post_signed(&peer, "/ddp/push", &body, &key)?',
     'crate::ddp_client::post_signed_id(&peer, "/ddp/push", &body, &key, &nodo)?'),
]
for a, b in reps:
    c = s.count(a)
    s = s.replace(a, b)
    print(f"  {c} x {a[:52]}...")

# post_signed_llm -> post_signed_id_t con el timeout de 120 s
old3 = '''                        let (status, resp) = crate::ddp_client::post_signed_llm(
                            &peer,
                            "/ddp/agent/chat",
                            &body,
                            &key,
                        )?;'''
new3 = '''                        let (status, resp) = crate::ddp_client::post_signed_id_t(
                            &peer,
                            "/ddp/agent/chat",
                            &body,
                            &key,
                            &nodo,
                            120,
                        )?;'''
assert old3 in s, "no encontre post_signed_llm"
s = s.replace(old3, new3, 1)
print("  post_signed_llm -> post_signed_id_t (120 s)")

open(P, "w", encoding="utf-8", newline="").write(s)
print("host.rs OK")
