#!/usr/bin/env python3
"""PASO 1.3: consola con modo crudo + flechas + historial.
- lee BYTE a byte (no linea) -> puede actuar sobre ESC [ A/B/C/D
- guarda de termios: se restaura SIEMPRE (Drop), aunque el proceso muera
- si NO es terminal (pipe o telnet) -> camino de siempre (read_line)"""
from pathlib import Path

# ── 1. libc al Cargo.toml (ya esta en el arbol via rusqlite: no añade peso) ──
C = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/Cargo.toml")
c = open(C, encoding="utf-8", newline="").read()
if 'libc = ' not in c:
    c = c.replace('serde_json = "1"',
                  'serde_json = "1"\n'
                  '# 03-oct-2026: modo crudo de la consola (flechas + historial).\n'
                  '# libc ya viene en el arbol via rusqlite -> no añade peso al binario.\n'
                  'libc = "0.2"', 1)
    open(C, "w", encoding="utf-8", newline="").write(c)
    print("Cargo.toml OK: +libc")

# ── 2. el lector crudo, antes del bucle ──
M = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/src/main.rs")
m = open(M, encoding="utf-8").read()

if "fn leer_linea_cruda" not in m:
    HELPER = r'''
// ─────────────────────────────────────────────────────────────────────────────
// 03-oct-2026 · CONSOLA: modo crudo, flechas e historial.
//
// ANTES: se leia con read_line. El terminal esta en modo canonico, asi que
// HACE ECO de lo que tecleas y las flechas se veian como ^[[A (tres bytes
// ESC [ A que pintaba el propio terminal, no nosotros). No habia historial.
//
// AHORA: se pone el terminal en crudo (sin eco, sin canonico) y se lee BYTE a
// byte, para poder actuar sobre las secuencias. Si NO es un terminal (por un
// pipe o por telnet), se usa el camino de siempre: asi nada se rompe.
//
// ⚠️ GUARDA DE TERMIOS: si el proceso muriera con el terminal en crudo, la
// terminal se queda SIN ECO y sin Enter. Por eso la restauracion va en un Drop
// (se ejecuta al salir del ambito, tambien con panic). Es lo que hay que hacer.
// ─────────────────────────────────────────────────────────────────────────────

struct TermGuard {
    orig: libc::termios,
}

impl Drop for TermGuard {
    fn drop(&mut self) {
        unsafe {
            libc::tcsetattr(0, libc::TCSANOW, &self.orig);
        }
    }
}

/// Pone el terminal en crudo. Devuelve None si no es un terminal (pipe/telnet).
fn crudo_on() -> Option<TermGuard> {
    unsafe {
        if libc::isatty(0) != 1 {
            return None;
        }
        let mut t: libc::termios = std::mem::zeroed();
        if libc::tcgetattr(0, &mut t) != 0 {
            return None;
        }
        let orig = t;
        t.c_lflag &= !(libc::ICANON | libc::ECHO);
        t.c_cc[libc::VMIN] = 1;
        t.c_cc[libc::VTIME] = 0;
        if libc::tcsetattr(0, libc::TCSANOW, &t) != 0 {
            return None;
        }
        Some(TermGuard { orig })
    }
}

/// Repinta la linea en curso (prompt + buffer) y vuelve a poner el cursor.
fn repinta(prompt: &str, buf: &str, pos: usize) {
    // \r + borrar la linea entera + prompt + buf; luego colocar el cursor.
    eprint!("\r\x1b[2K{}{}", prompt, buf);
    let atras = buf.chars().count().saturating_sub(pos);
    if atras > 0 {
        eprint!("\x1b[{}D", atras);
    }
    std::io::Write::flush(&mut std::io::stderr()).ok();
}

/// Lee una linea con el terminal en crudo: flechas + historial + edicion.
/// Devuelve None si se acaba la entrada (EOF).
fn leer_linea_cruda(prompt: &str, hist: &mut Vec<String>) -> Option<String> {
    let _guard = crudo_on();
    let mut stdin = std::io::stdin();
    if _guard.is_none() {
        // Pipe o telnet: camino de siempre, sin secuencias ANSI.
        let mut s = String::new();
        match std::io::BufRead::read_line(&mut stdin.lock(), &mut s) {
            Ok(0) | Err(_) => return None,
            Ok(_) => return Some(s),
        }
    }
    let mut buf: Vec<char> = Vec::new();
    let mut pos = 0usize;
    let mut hpos = hist.len();
    let mut guardada: Vec<char> = Vec::new();
    loop {
        let mut b = [0u8; 1];
        if std::io::Read::read(&mut stdin, &mut b).unwrap_or(0) == 0 {
            eprint!("\r\n");
            return None;
        }
        match b[0] {
            b'\r' | b'\n' => {
                eprint!("\r\n");
                let s: String = buf.iter().collect();
                if !s.trim().is_empty() {
                    hist.push(s.clone());
                }
                return Some(s);
            }
            3 => {
                // Ctrl-C: linea cancelada
                eprint!("^C\r\n");
                return Some(String::new());
            }
            4 => {
                // Ctrl-D: fin
                eprint!("\r\n");
                return None;
            }
            127 | 8 => {
                // Backspace
                if pos > 0 {
                    buf.remove(pos - 1);
                    pos -= 1;
                    repinta(prompt, &buf.iter().collect::<String>(), pos);
                }
            }
            27 => {
                // ESC: puede ser una flecha (ESC [ A/B/C/D)
                let mut s2 = [0u8; 2];
                if std::io::Read::read_exact(&mut stdin, &mut s2).is_err() {
                    continue;
                }
                if s2[0] != b'[' {
                    continue;
                }
                match s2[1] {
                    b'A' => {
                        // arriba: comando anterior
                        if hpos > 0 {
                            if hpos == hist.len() {
                                guardada = buf.clone();
                            }
                            hpos -= 1;
                            buf = hist[hpos].chars().collect();
                            pos = buf.len();
                            repinta(prompt, &buf.iter().collect::<String>(), pos);
                        }
                    }
                    b'B' => {
                        // abajo: siguiente
                        if hpos < hist.len() {
                            hpos += 1;
                            buf = if hpos == hist.len() {
                                guardada.clone()
                            } else {
                                hist[hpos].chars().collect()
                            };
                            pos = buf.len();
                            repinta(prompt, &buf.iter().collect::<String>(), pos);
                        }
                    }
                    b'C' => {
                        // derecha
                        if pos < buf.len() {
                            pos += 1;
                            repinta(prompt, &buf.iter().collect::<String>(), pos);
                        }
                    }
                    b'D' => {
                        // izquierda
                        if pos > 0 {
                            pos -= 1;
                            repinta(prompt, &buf.iter().collect::<String>(), pos);
                        }
                    }
                    b'3' => {
                        // Supr: ESC [ 3 ~
                        let mut s3 = [0u8; 1];
                        let _ = std::io::Read::read_exact(&mut stdin, &mut s3);
                        if pos < buf.len() {
                            buf.remove(pos);
                            repinta(prompt, &buf.iter().collect::<String>(), pos);
                        }
                    }
                    _ => {}
                }
            }
            c if c >= 32 && c < 127 => {
                buf.insert(pos, c as char);
                pos += 1;
                repinta(prompt, &buf.iter().collect::<String>(), pos);
            }
            _ => {}
        }
    }
}

'''
    # insertar justo antes de la declaracion de la funcion que contiene el bucle
    ancla = "    let mut pending: Option<String> = None;\n    let mut saludo_hecho = false;\n    loop {"
    assert ancla in m, "no encontre el ancla del bucle del console"
    m = m.replace(ancla, HELPER + ancla, 1)
    open(M, "w", encoding="utf-8").write(m)
    print("main.rs OK: helper leer_linea_cruda insertado")
else:
    print("(el helper ya estaba)")

# ── 3. usar el lector nuevo en el bucle (con historial) ──
m = open(M, encoding="utf-8").read()
if "leer_linea_cruda(&" not in m:
    viejo = '''        let mut raw = String::new();
        match std::io::stdin().lock().read_line(&mut raw) {
            Ok(0) => break,
            Ok(_) => {}
            Err(_) => break,
        }'''
    nuevo = '''        let raw = match leer_linea_cruda(&prompt_txt, &mut hist_cmd) {
            Some(s) => s,
            None => break,
        };'''
    assert viejo in m, "no encontre el read_line del bucle"
    m = m.replace(viejo, nuevo, 1)
    # declarar el historial y el prompt antes del loop
    m = m.replace("    let mut pending: Option<String> = None;\n    let mut saludo_hecho = false;",
                  "    let mut pending: Option<String> = None;\n"
                  "    let mut saludo_hecho = false;\n"
                  "    let mut hist_cmd: Vec<String> = Vec::new();   // historial de la consola (flechas)\n"
                  "    let mut prompt_txt = String::new();   // se recalcula en cada vuelta", 1)
    # el prompt: guardarlo en prompt_txt para que repinta() lo use
    m = m.replace('''        if mode_now.trim().is_empty() {
            eprint!("{}", paint("» ", C_ACC));
        } else {
            eprint!("{}", paint(&format!("({}) » ", mode_now.trim()), C_ACC));
        }
        std::io::stderr().flush().ok();''',
                  '''        prompt_txt = if mode_now.trim().is_empty() {
            "» ".to_string()
        } else {
            format!("({}) » ", mode_now.trim())
        };
        {
            use std::io::Write;
            eprint!("{}", paint(&prompt_txt, C_ACC));
            std::io::stderr().flush().ok();
        }''', 1)
    open(M, "w", encoding="utf-8").write(m)
    print("main.rs OK: bucle usa leer_linea_cruda + historial")
else:
    print("(el bucle ya estaba)")
