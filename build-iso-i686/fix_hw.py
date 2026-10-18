#!/usr/bin/env python3
"""$DEVICE("hw:*") - hardware fisico por M. SOLO lectura/escritura de /sys.
Cero dependencias nuevas. Alcance A: list, temp, rfkill, net, battery."""
from pathlib import Path

SRC = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src")

HW = r'''//! Hardware fisico por `$DEVICE("hw:*")` — SOLO /sys, sin dependencias nuevas.
//!
//! 02-oct-2026. Alcance A (diagnostico; ademas es el utillaje para depurar la WiFi):
//!   $DEVICE("hw:list")              -> que tiene ESTA maquina (se adapta al hierro)
//!   $DEVICE("hw:temp")              -> temperatura CPU en grados C
//!   $DEVICE("hw:rfkill")            -> estado de las radios (radio de WiFi incluida)
//!   $DEVICE("hw:rfkill","unblock")  -> desbloquear la radio
//!   $DEVICE("hw:net","wlan0")       -> estado|carrier|driver de una interfaz
//!   $DEVICE("hw:battery")           -> capacidad%|estado
//!
//! Todo es leer/escribir ficheros de /sys: si el fichero no esta, se devuelve
//! vacio en vez de fallar (estos PCs viejos tienen muy poco o nada de /sys).

use std::fs;

use crate::value::Value;

fn lee(p: &str) -> String {
    fs::read_to_string(p)
        .map(|s| s.trim().to_string())
        .unwrap_or_default()
}

/// Devuelve los argumentos como texto (para no depender de Value::as_string).
fn txt(v: Option<&Value>) -> String {
    match v {
        Some(Value::String(s)) => s.clone(),
        Some(other) => format!("{other}"),
        None => String::new(),
    }
}

pub fn hw_device(action: &str, args: &[Value]) -> Result<Value, String> {
    match action {
        "list" => {
            let mut out = String::new();
            if let Ok(rd) = fs::read_dir("/sys/class/thermal") {
                for e in rd.flatten() {
                    let n = e.file_name().to_string_lossy().to_string();
                    if n.starts_with("thermal_zone") {
                        out.push_str(&format!("temp({n}) "));
                    }
                }
            }
            if let Ok(rd) = fs::read_dir("/sys/class/power_supply") {
                for e in rd.flatten() {
                    out.push_str(&format!("fuente({}) ", e.file_name().to_string_lossy()));
                }
            }
            if let Ok(rd) = fs::read_dir("/sys/class/rfkill") {
                let mut n = 0;
                for _ in rd.flatten() {
                    n += 1;
                }
                if n > 0 {
                    out.push_str(&format!("rfkill({n}) "));
                }
            }
            if let Ok(rd) = fs::read_dir("/sys/class/backlight") {
                for e in rd.flatten() {
                    out.push_str(&format!("brillo({}) ", e.file_name().to_string_lossy()));
                }
            }
            if let Ok(rd) = fs::read_dir("/sys/class/leds") {
                let mut n = 0;
                for _ in rd.flatten() {
                    n += 1;
                }
                if n > 0 {
                    out.push_str(&format!("leds({n}) "));
                }
            }
            if let Ok(rd) = fs::read_dir("/sys/class/net") {
                out.push_str("red(");
                for e in rd.flatten() {
                    out.push_str(&e.file_name().to_string_lossy());
                    out.push(' ');
                }
                out.push_str(") ");
            }
            if out.is_empty() {
                out = "sin /sys legible".to_string();
            }
            Ok(Value::String(out.trim_end().to_string()))
        }
        "temp" => {
            if let Ok(rd) = fs::read_dir("/sys/class/thermal") {
                for e in rd.flatten() {
                    let n = e.file_name().to_string_lossy().to_string();
                    if n.starts_with("thermal_zone") {
                        let v = lee(&format!("/sys/class/thermal/{n}/temp"));
                        if let Ok(mc) = v.parse::<i64>() {
                            return Ok(Value::String(format!("{:.1}", mc as f64 / 1000.0)));
                        }
                    }
                }
            }
            Ok(Value::String(String::new()))
        }
        "rfkill" => {
            let op = txt(args.first());
            let mut out = String::new();
            let mut tocado = 0;
            if let Ok(rd) = fs::read_dir("/sys/class/rfkill") {
                for e in rd.flatten() {
                    let d = e.path();
                    let n = e.file_name().to_string_lossy().to_string();
                    let tipo = lee(&d.join("type").to_string_lossy());
                    let soft = lee(&d.join("soft").to_string_lossy());
                    let hard = lee(&d.join("hard").to_string_lossy());
                    out.push_str(&format!("{n}:{tipo}:soft={soft},hard={hard} "));
                    if op == "unblock" && soft == "1" {
                        if fs::write(d.join("soft"), "0").is_ok() {
                            tocado += 1;
                        }
                    }
                }
            }
            if tocado > 0 {
                out.push_str(&format!("[desbloqueadas {tocado}]"));
            }
            if out.is_empty() {
                out = "sin rfkill".to_string();
            }
            Ok(Value::String(out.trim_end().to_string()))
        }
        "net" => {
            let i = txt(args.first());
            if i.is_empty() {
                return Err("uso: $DEVICE(\"hw:net\",\"<iface>\")".to_string());
            }
            let base = format!("/sys/class/net/{i}");
            if !std::path::Path::new(&base).exists() {
                return Ok(Value::String(format!("{i}: NO EXISTE")));
            }
            let oper = lee(&format!("{base}/operstate"));
            let carrier = lee(&format!("{base}/carrier"));
            let drv = fs::read_link(format!("{base}/device/driver"))
                .ok()
                .and_then(|p| p.file_name().map(|s| s.to_string_lossy().to_string()))
                .unwrap_or_default();
            let velocidad = lee(&format!("{base}/speed"));
            Ok(Value::String(format!(
                "{i}: {oper} · carrier={carrier} · driver={drv} · speed={velocidad}"
            )))
        }
        "battery" => {
            for b in ["BAT0", "BAT1", "BAT", "CMB0"] {
                let p = format!("/sys/class/power_supply/{b}");
                if std::path::Path::new(&p).exists() {
                    let cap = lee(&format!("{p}/capacity"));
                    let st = lee(&format!("{p}/status"));
                    return Ok(Value::String(format!("{b}: {cap}% · {st}")));
                }
            }
            Ok(Value::String("sin bateria".to_string()))
        }
        _ => Err(format!(
            "Unknown HW action: {action} (list, temp, rfkill, net, battery)"
        )),
    }
}
'''
(SRC / "hw.rs").write_text(HW, encoding="utf-8", newline="")
print("hw.rs escrito")

# mod en lib.rs (fuera de wasm)
pl = SRC / "lib.rs"
l = open(pl, encoding="utf-8", newline="").read()
if "pub mod hw;" not in l:
    ancla = "pub mod ddp;"
    assert ancla in l, "no encontre pub mod ddp"
    l = l.replace(ancla, ancla + "\n\n/// Hardware fisico por $DEVICE(\"hw:*\") — solo /sys (no aplica a wasm).\n#[cfg(not(target_arch = \"wasm32\"))]\npub mod hw;", 1)
    open(pl, "w", encoding="utf-8", newline="").write(l)
    print("lib.rs OK: mod hw")

# brazo en device_call
ph = SRC / "host.rs"
h = open(ph, encoding="utf-8", newline="").read()
if '"hw" =>' not in h:
    ancla = '''            #[cfg(feature = "spawn")]
            "spawn" => {'''
    nuevo = '''            #[cfg(not(target_arch = "wasm32"))]
            "hw" => {
                // ── 02-oct-2026: HARDWARE FISICO por M (solo /sys, sin deps) ──
                //   $DEVICE("hw:list")   · hw:temp · hw:rfkill[,unblock]
                //   $DEVICE("hw:net","iface") · hw:battery
                // Es tambien el utillaje para depurar la WiFi por telnet.
                crate::hw::hw_device(action, &args)
            }
            #[cfg(feature = "spawn")]
            "spawn" => {'''
    assert ancla in h, "no encontre el brazo spawn"
    h = h.replace(ancla, nuevo, 1)
    open(ph, "w", encoding="utf-8", newline="").write(h)
    print("host.rs OK: brazo hw")
