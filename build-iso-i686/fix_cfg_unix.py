#!/usr/bin/env python3
"""Arregla el aviso de Windows: termios no existe ahi.
Se encierra lo de Unix en #[cfg(unix)] y se deja una alternativa simple."""
from pathlib import Path

M = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/src/main.rs")
m = open(M, encoding="utf-8").read()   # modo texto: normaliza CRLF -> LF

if "cfg(not(unix))\nfn leer_linea_cruda" not in m:
    # 1) poner #[cfg(unix)] delante de cada pieza de Unix
    for decl in ("struct TermGuard {",
                 "impl Drop for TermGuard {",
                 "fn crudo_on() -> Option<TermGuard> {",
                 "fn repinta(prompt: &str, buf: &str, pos: usize) {",
                 "fn leer_linea_cruda(prompt: &str, hist: &mut Vec<String>) -> Option<String> {"):
        m = m.replace(decl, "#[cfg(unix)]\n" + decl, 1)

    # 2) alternativa para lo que NO es Unix (Windows): read_line de siempre
    FALLBACK = '''
// Fuera de Unix no hay termios: se usa el camino de siempre. Asi el repo
// compila tambien en el host Windows para `cargo check` sin errores.
#[cfg(not(unix))]
fn leer_linea_cruda(_prompt: &str, _hist: &mut Vec<String>) -> Option<String> {
    let mut s = String::new();
    match std::io::stdin().lock().read_line(&mut s) {
        Ok(0) | Err(_) => None,
        Ok(_) => Some(s),
    }
}
'''
    # justo DESPUES de la funcion de Unix (que termina en la llave del match final).
    # Se inserta antes del ancla del bloque que sigue (el comentario de secciones).
    ancla = "\n// ─────────────────────────────────────────────────────────────────────────────\n// SEPARADOR"
    if ancla in m:
        m = m.replace(ancla, FALLBACK + ancla, 1)
    else:
        # si no hay ese separador, se pone justo antes del uso
        m = m.replace("    let raw = match leer_linea_cruda(", FALLBACK + "\n    let raw = match leer_linea_cruda(", 1)
    open(M, "w", encoding="utf-8").write(m)
    print("main.rs OK: cfg(unix) + alternativa para Windows")
else:
    print("(ya estaba)")
