#!/usr/bin/env python3
"""Rehace guia_maestra usando SOLO los ayudantes que ya usa node_context_base:
   all_keys(host) + get_hs(host, ns, &[subs...]) + sub_str(&sub)
Sin inventar APIs."""
from pathlib import Path

P = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/src/main.rs")
s = open(P, encoding="utf-8", newline="").read()

i = s.find("fn guia_maestra")
j = s.find("/// Envoltorio: el contexto de siempre")
if i < 0 or j < 0 or i > j:
    raise SystemExit("no encuentro el bloque a sustituir")

NUEVA = '''/// GUIA MAESTRA (^GUIA) para el prompt: lee el global y lo devuelve como texto.
/// MISMA fuente que ve el help. Vacia => "" (el prompt queda como antes).
fn guia_maestra(host: &MemoryHost) -> String {
    let keys = all_keys(host);
    let secciones = ["reglas", "rutinas", "device", "flujo", "error"];
    let mut t = String::new();
    for sec in secciones {
        let mut entradas: Vec<String> = Vec::new();
        if sec == "reglas" {
            let mut n = 1;
            loop {
                let v = get_hs(host, "GUIA", &["reglas", &n.to_string(), "1"]);
                if v.is_empty() {
                    break;
                }
                entradas.push(v);
                n += 1;
                if n > 12 {
                    break;
                }
            }
        } else {
            let mut claves: Vec<String> = Vec::new();
            for (ns, subs) in &keys {
                if ns.as_str() == "GUIA" && subs.len() == 2 && sub_str(&subs[0]) == sec {
                    claves.push(sub_str(&subs[1]));
                }
            }
            claves.sort();
            claves.dedup();
            for k in claves.iter().take(40) {
                let mut lineas: Vec<String> = Vec::new();
                let mut n = 1;
                loop {
                    let v = get_hs(host, "GUIA", &[sec, k, &n.to_string()]);
                    if v.is_empty() {
                        break;
                    }
                    lineas.push(v);
                    n += 1;
                    if n > 8 {
                        break;
                    }
                }
                if !lineas.is_empty() {
                    entradas.push(format!("{k}: {}", lineas.join(" | ")));
                }
            }
        }
        if !entradas.is_empty() {
            t.push_str(&format!("[{sec}]\\n"));
            for e in &entradas {
                t.push_str("  ");
                t.push_str(e);
                t.push('\\n');
            }
        }
    }
    if t.is_empty() {
        return String::new();
    }
    format!(
        "\\n=== GUIA MAESTRA DEL NODO (^GUIA) - lo que este nodo SABE HACER ===\\n{t}\\
         REGLA DE ORO: si algo no esta en esta guia ni en el contexto, DI QUE NO LO SABES. No lo inventes.\\n"
    )
}

'''
s = s[:i] + NUEVA + s[j:]
open(P, "w", encoding="utf-8", newline="").write(s)
print("guia_maestra reescrita con all_keys + get_hs")
