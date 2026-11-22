//! Hardware fisico por `$DEVICE("hw:*")` — SOLO /sys, sin dependencias nuevas.
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
        _ => String::new(),
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
            if let Some(t) = temperatura_en("/sys") {
                return Ok(Value::String(t));
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


/// Temperatura de la CPU en grados, con un decimal, o None si no hay sensores.
///
/// Dos fuentes, en este orden:
///   1. `/sys/class/thermal/thermal_zone*` — lo clásico en portátiles y ARM.
///   2. `/sys/class/hwmon/hwmon*tempN_input` — donde exponen los sensores
///      muchas placas y CPUs modernas cuando NO hay thermal_zone.
///
/// El segundo camino se añadió el 22-nov-2026: en Linux sin thermal_zone
/// (contenedores, algunas placas) `hw:temp` devolvía vacío aunque hubiera
/// sensores en hwmon.
///
/// `raiz` permite testear con un árbol de ficheros falso en vez de /sys.
fn temperatura_en(raiz: &str) -> Option<String> {
    let base_thermal = format!("{raiz}/class/thermal");
    if let Ok(rd) = fs::read_dir(&base_thermal) {
        let mut nombres: Vec<String> = rd
            .flatten()
            .map(|e| e.file_name().to_string_lossy().to_string())
            .filter(|n| n.starts_with("thermal_zone"))
            .collect();
        nombres.sort();
        for n in nombres {
            let v = lee(&format!("{base_thermal}/{n}/temp"));
            if let Ok(mc) = v.trim().parse::<i64>() {
                if mc != 0 {
                    return Some(format!("{:.1}", mc as f64 / 1000.0));
                }
            }
        }
    }

    let base_hw = format!("{raiz}/class/hwmon");
    if let Ok(rd) = fs::read_dir(&base_hw) {
        let mut dirs: Vec<String> = rd
            .flatten()
            .map(|e| e.file_name().to_string_lossy().to_string())
            .filter(|n| n.starts_with("hwmon"))
            .collect();
        dirs.sort();
        for d in dirs {
            let dir = format!("{base_hw}/{d}");
            let mut cands: Vec<String> = Vec::new();
            if let Ok(fs_) = fs::read_dir(&dir) {
                for f in fs_.flatten() {
                    let n = f.file_name().to_string_lossy().to_string();
                    if n.starts_with("temp") && n.ends_with("_input") {
                        cands.push(n);
                    }
                }
            }
            // temp1_input primero: suele ser el package de la CPU.
            cands.sort_by_key(|n| if n == "temp1_input" { 0 } else { 1 });
            for n in cands {
                let v = lee(&format!("{dir}/{n}"));
                if let Ok(mc) = v.trim().parse::<i64>() {
                    if mc > 0 {
                        return Some(format!("{:.1}", mc as f64 / 1000.0));
                    }
                }
            }
        }
    }
    None
}

#[cfg(test)]
mod tests {
    //! Tests de `hw:*`. El módulo tenía CERO tests hasta el 22-nov-2026
    //! (hallazgo de la auditoría). No se puede afirmar que un device funciona
    //! si nadie lo ha ejercitado.
    //!
    //! Qué se puede comprobar sin hardware concreto: que cada acción RESUELVE
    //! (Ok, nunca panic) y que devuelve un String. Las que dependen de /sys
    //! devuelven "" o un mensaje honesto si el fichero no está — ambas cosas
    //! son resultados válidos; lo que NO vale es un error ni un panic.

    /// Árbol de /sys falso en un directorio temporal, para ejercitar
    /// `temperatura_en` sin hardware. Se borra al salir del test.
    struct SysFalso(std::path::PathBuf);

    impl SysFalso {
        fn nuevo(nombre: &str) -> Self {
            let p = std::env::temp_dir().join(format!("hwtest_{nombre}"));
            let _ = std::fs::remove_dir_all(&p);
            std::fs::create_dir_all(&p).unwrap();
            SysFalso(p)
        }
        fn escribe(&self, rel: &str, contenido: &str) {
            let f = self.0.join(rel);
            std::fs::create_dir_all(f.parent().unwrap()).unwrap();
            std::fs::write(f, contenido).unwrap();
        }
        fn raiz(&self) -> String {
            self.0.to_string_lossy().to_string()
        }
    }

    impl Drop for SysFalso {
        fn drop(&mut self) {
            let _ = std::fs::remove_dir_all(&self.0);
        }
    }

    #[test]
    fn temp_lee_thermal_zone() {
        let s = SysFalso::nuevo("tz");
        s.escribe("class/thermal/thermal_zone0/temp", "48500\n");
        assert_eq!(super::temperatura_en(&s.raiz()), Some("48.5".to_string()));
    }

    #[test]
    fn temp_cae_a_hwmon_si_no_hay_thermal_zone() {
        // El caso real que motivó el fix: sin thermal_zone, con hwmon.
        let s = SysFalso::nuevo("hwmon");
        s.escribe("class/hwmon/hwmon0/temp1_input", "62000\n");
        assert_eq!(super::temperatura_en(&s.raiz()), Some("62.0".to_string()));
    }

    #[test]
    fn temp_prefiere_temp1_input() {
        let s = SysFalso::nuevo("pref");
        s.escribe("class/hwmon/hwmon0/temp2_input", "70000\n");
        s.escribe("class/hwmon/hwmon0/temp1_input", "55000\n");
        assert_eq!(super::temperatura_en(&s.raiz()), Some("55.0".to_string()));
    }

    #[test]
    fn temp_sin_sensores_devuelve_none() {
        let s = SysFalso::nuevo("vacio");
        std::fs::create_dir_all(s.0.join("class/thermal")).unwrap();
        s.escribe("class/thermal/cooling_device0/type", "Processor\n");
        assert_eq!(super::temperatura_en(&s.raiz()), None);
    }

    #[test]
    fn temp_ignora_ceros() {
        // Un temp a 0 no es una lectura válida (sensor apagado).
        let s = SysFalso::nuevo("cero");
        s.escribe("class/thermal/thermal_zone0/temp", "0\n");
        s.escribe("class/hwmon/hwmon0/temp1_input", "41000\n");
        assert_eq!(super::temperatura_en(&s.raiz()), Some("41.0".to_string()));
    }

    use super::hw_device;

    fn ejecuta(action: &str, args: &[&str]) -> String {
        let vals: Vec<crate::value::Value> = args
            .iter()
            .map(|s| crate::value::Value::String((*s).to_string()))
            .collect();
        match hw_device(action, &vals) {
            Ok(v) => v.as_string(),
            Err(e) => panic!("hw:{action} devolvió Err: {e}"),
        }
    }

    #[test]
    fn list_resuelve_sin_panic() {
        // "" (sin /sys legible) o "fuente(...) red(...)": ambos válidos.
        let _ = ejecuta("list", &[]);
    }

    #[test]
    fn temp_devuelve_numero_o_vacio() {
        let t = ejecuta("temp", &[]);
        if !t.is_empty() {
            let n: f64 = t.parse().expect("temp debe ser un número con formato 42.0");
            // rangos de cordura: ningún sensor real está fuera de esto
            assert!(n > -50.0 && n < 200.0, "temperatura fuera de rango: {n}");
        }
    }

    #[test]
    fn battery_devuelve_formato_o_mensaje() {
        let b = ejecuta("battery", &[]);
        // "sin bateria", o "BAT1: 96% · Charging"
        assert!(!b.is_empty(), "battery siempre debe decir algo");
    }

    #[test]
    fn rfkill_resuelve() {
        let _ = ejecuta("rfkill", &[]);
    }

    #[test]
    fn net_interfaz_inexistente_lo_dice() {
        let r = ejecuta("net", &["iface_que_no_existe_xyz"]);
        assert!(
            r.contains("NO EXISTE") || r.contains("unknown") || r.contains("up"),
            "net debe informar del estado o de que no existe, no fallar: {r:?}"
        );
    }

    #[test]
    fn accion_desconocida_es_error_claro() {
        let vals = vec![];
        let e = hw_device("inventada", &vals).unwrap_err();
        assert!(e.contains("Unknown HW action"), "mensaje poco claro: {e}");
    }
}
