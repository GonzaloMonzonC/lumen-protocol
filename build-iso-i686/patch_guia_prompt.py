#!/usr/bin/env python3
"""Mete la ^GUIA en el contexto del LLM de forma SEGURA:
  - renombra fn node_context -> fn node_context_base (no se toca su logica)
  - anade un fn node_context que llama a la base y le APPENDEA la guia maestra
  - y un fn guia_maestra(host) que LEE el global ^GUIA del PDB
Asi, si algo falla, se ve en el compilador y se deshace facil.
"""
from pathlib import Path

P = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/src/main.rs")
s = open(P, encoding="utf-8", newline="").read()

if "node_context_base" in s:
    print("(ya estaba parcheado)")
    raise SystemExit(0)

ANCLA = "fn node_context(host: &MemoryHost) -> String {"
if ANCLA not in s:
    raise SystemExit("NO encuentro la firma de node_context")

NUEVO = '''/// ⭐ GUIA MAESTRA (^GUIA) para el prompt: lee el global y lo devuelve como texto.
/// Es la MISMA fuente que ve el help: el LLM y la persona leen lo mismo.
/// Si el global esta vacio, devuelve "" y el prompt queda como antes (sin romper).
fn guia_maestra(host: &MemoryHost) -> String {
    let secciones = ["reglas", "rutinas", "device", "flujo", "error"];
    let mut t = String::new();
    for sec in secciones {
        if let Ok(claves) = host.order("GUIA", &[sec]) {
            for (k, _) in claves.iter().take(40) {
                let ks = match k {
                    Value::String(x) => x.clone(),
                    otro => otro.as_string(),
                };
                let mut lineas: Vec<String> = Vec::new();
                let mut n = 1;
                loop {
                    let v = get_hs(host, "GUIA", &[sec, &ks, &n.to_string()]);
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
                    let _ = std::fmt::Write::write_fmt(
                        &mut t,
                        format_args!("  {ks}: {}\\n", lineas.join(" · ")),
                    );
                }
            }
        }
    }
    if t.is_empty() {
        return String::new();
    }
    format!(
        "\\n=== GUIA MAESTRA DEL NODO (^GUIA) — lo que este nodo SABE HACER ===\\n{t}\
         REGLA DE ORO: si algo no esta en esta guia ni en el contexto, DI QUE NO LO SABES. No lo inventes.\\n"
    )
}

/// Envoltorio: el contexto de siempre + la guia maestra al final.
fn node_context(host: &MemoryHost) -> String {
    let base = node_context_base(host);
    let g = guia_maestra(host);
    if g.is_empty() {
        base
    } else {
        format!("{base}{g}")
    }
}

'''
s = s.replace(ANCLA, NUEVO + "fn node_context_base(host: &MemoryHost) -> String {", 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("main.rs: node_context envuelto + guia_maestra anadida")
print("  (la logica original queda intacta en node_context_base)")
