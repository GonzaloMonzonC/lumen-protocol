#!/usr/bin/env python3
"""$DEVICE("sys:ps") - la LISTA DE PROCESOS DEL SISTEMA, para el %SS.
Sigue el mismo patron que sys_top() (host.rs:1535): leer /proc directo, sin
dependencias. Devuelve lineas: pid|comm|rss_kb|estado|cpu_ticks"""
import re
from pathlib import Path

H = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src/host.rs")
s = open(H, encoding="utf-8", newline="").read()

if "fn sys_ps" not in s:
    FUNC = '''
/// Lista de procesos del SISTEMA (para el %SS). Mismo espiritu que sys_top():
/// leer /proc directo, sin dependencias. Una linea por proceso:
///     pid|comm|rss_kb|estado|cpu_ticks
/// Ordenada como la saca /proc (por pid). Si no hay permisos en algun /proc/N,
/// se salta ese proceso (no falla).
#[cfg(target_os = "linux")]
pub fn sys_ps() -> String {
    let mut out: Vec<String> = Vec::new();
    let rd = match std::fs::read_dir("/proc") {
        Ok(r) => r,
        Err(_) => return String::new(),
    };
    for e in rd.flatten() {
        let nombre = e.file_name().to_string_lossy().to_string();
        if !nombre.chars().all(|c| c.is_ascii_digit()) {
            continue;
        }
        let base = format!("/proc/{nombre}");
        let comm = std::fs::read_to_string(format!("{base}/comm"))
            .map(|x| x.trim().to_string())
            .unwrap_or_default();
        if comm.is_empty() {
            continue;
        }
        // memoria residente (de status: VmRSS) - mas fiable que statm
        let mut rss = String::new();
        let mut estado = String::new();
        if let Ok(st) = std::fs::read_to_string(format!("{base}/status")) {
            for l in st.lines() {
                if let Some(v) = l.strip_prefix("VmRSS:") {
                    rss = v.split_whitespace().next().unwrap_or("").to_string();
                } else if let Some(v) = l.strip_prefix("State:") {
                    estado = v.trim().split_whitespace().next().unwrap_or("").to_string();
                }
            }
        }
        // cpu (utime+stime) de stat
        let mut ticks = String::new();
        if let Ok(stat) = std::fs::read_to_string(format!("{base}/stat")) {
            if let Some((_, tras)) = stat.rsplit_once(')') {
                let f: Vec<&str> = tras.split_whitespace().collect();
                if f.len() > 13 {
                    let ut: u64 = f[11].parse().unwrap_or(0);
                    let st_: u64 = f[12].parse().unwrap_or(0);
                    ticks = (ut + st_).to_string();
                }
            }
        }
        out.push(format!("{nombre}|{comm}|{rss}|{estado}|{ticks}"));
    }
    out.join("\\n")
}

/// Igual que sys_ps() pero devuelve solo los N procesos que MAS memoria usan,
/// que es lo que se quiere ver en un top.
#[cfg(target_os = "linux")]
pub fn sys_ps_top(n: usize) -> String {
    let todo = sys_ps();
    let mut v: Vec<(u64, String)> = todo
        .lines()
        .filter_map(|l| {
            let p: Vec<&str> = l.split('|').collect();
            if p.len() < 3 {
                return None;
            }
            let mem: u64 = p[2].parse().unwrap_or(0);
            Some((mem, l.to_string()))
        })
        .collect();
    v.sort_by(|a, b| b.0.cmp(&a.0));
    v.truncate(n);
    v.into_iter().map(|(_, l)| l).collect::<Vec<_>>().join("\\n")
}
'''
    # insertar antes de fn sys_top
    ancla = "pub fn sys_top() -> String {"
    assert ancla in s, "no encontre fn sys_top"
    s = s.replace(ancla, FUNC.lstrip("\n") + "\n" + ancla, 1)
    print("host.rs: sys_ps() y sys_ps_top() anadidas")

# enganchar al $DEVICE("sys:...")
if '"ps"' not in s:
    an = '''                match action {
                    "top" | "stat" => Ok(Value::String(sys_top())),'''
    if an in s:
        s = s.replace(an, '''                match action {
                    "top" | "stat" => Ok(Value::String(sys_top())),
                    // 03-oct-2026: lista de procesos para el %SS (estilo MSM):
                    //   $DEVICE("sys:ps")        -> todos: pid|comm|rss|estado|ticks
                    //   $DEVICE("sys:ps","10")   -> los 10 que mas memoria usan
                    "ps" => {
                        let n: usize = args
                            .first()
                            .and_then(|v| match v {
                                Value::String(t) => t.parse().ok(),
                                _ => None,
                            })
                            .unwrap_or(0);
                        if n > 0 {
                            Ok(Value::String(sys_ps_top(n)))
                        } else {
                            Ok(Value::String(sys_ps()))
                        }
                    }''', 1)
        print("host.rs: $DEVICE(\"sys:ps\") enganchado")
    else:
        print("  !! no encontre el match de sys:top para enganchar")

open(H, "w", encoding="utf-8", newline="").write(s)
print("escrito")
