//! Device ZS estilo MSM (17-sep-2026, petición de Gonzalo) — «grabar rutinas».
//!
//! `$DEVICE("zroutines","save", BUF, [DEST])`
//! - Serializa las líneas `^EDIT(BUF,n)` (el buffer de trabajo del editor %E,
//!   que es un GLOBAL — editable con S, como el ^ROUTINE de MSM) y las graba
//!   como `routines/DEST.m` (DEST por defecto = BUF), **recargando en caliente**
//!   la rutina en el mapa del host.
//! - Si DEST ya existía, guarda `routines/DEST.m.bak` antes de sobrescribir.
//! - El directorio de rutinas se lee de `^SYSINFO("routines_dir")` (lo publica
//!   mvm-nas al arrancar). Sin él, el device no escribe nada (fail-closed).
//!
//! Flujo MSM clásico:
//!   D ZL^%Z("MU")          → fuente ^SYSINFO → buffer ^EDIT("MU",n)
//!   S ^EDIT("MU",2)="..."  → editar el GLOBAL
//!   D ZS^%Z("MU","OTRO")   → routines/OTRO.m + recarga en caliente
//!
//! Feature-gated (`zroutines`): nativo, fuera de WASM.

use std::collections::BTreeMap;
use std::path::PathBuf;

use crate::host::MemoryHost;
use crate::value::{Subscript, Value};

/// `$DEVICE("zroutines","save", BUF, [DEST])`
pub fn zroutines_device(host: &mut MemoryHost, action: &str, args: &[Value]) -> Result<Value, String> {
    match action {
        "save" => zs_save(host, args),
        "rollback" => zs_rollback(host, args),
        _ => Err(format!("[ZS] acción desconocida: {action} (usa \"save\")")),
    }
}

fn zs_save(host: &mut MemoryHost, args: &[Value]) -> Result<Value, String> {
    let buf = args.first().map(|v| v.as_string()).unwrap_or_default();
    let dest = match args.get(1).map(|v| v.as_string()) {
        Some(d) if !d.trim().is_empty() => d,
        _ => buf.clone(),
    };
    let buf = buf.trim().to_string();
    let mut dest = dest.trim().to_string();
    if buf.is_empty() {
        return Err("[ZS] uso: $DEVICE(\"zroutines\",\"save\",\"BUF\",[\"DEST\"])".to_string());
    }
    // Directorio de rutinas: ^SYSINFO("routines_dir") — lo siembra mvm-nas.
    let dir = host
        .values
        .get(&(
            "SYSINFO".to_string(),
            vec![Subscript::String("routines_dir".to_string())],
        ))
        .map(|v| v.as_string())
        .unwrap_or_default();
    if dir.trim().is_empty() {
        return Err("[ZS] sin ^SYSINFO(\"routines_dir\") — arranca con -r DIR".to_string());
    }
    // Serializar ^EDIT(BUF,n) en orden numérico (mismo criterio que :save).
    let mut by_num: BTreeMap<u64, (bool, String)> = BTreeMap::new();
    for ((ns, subs), v) in host.values.iter() {
        if ns != "EDIT" || subs.len() < 2 {
            continue;
        }
        if !sub_str(&subs[0]).eq_ignore_ascii_case(&buf) {
            continue;
        }
        let is_num = matches!(&subs[1], Subscript::Number(_));
        if let Ok(n) = sub_str(&subs[1]).parse::<u64>() {
            let keep_existing_num = matches!(by_num.get(&n), Some((true, _)));
            if !(keep_existing_num && !is_num) {
                by_num.insert(n, (is_num, v.as_string()));
            }
        }
    }
    if by_num.is_empty() {
        return Err(format!(
            "[ZS] ^EDIT({buf}) vacío — carga antes con D ZL^%Z(\"{buf}\")"
        ));
    }
    let source = format!(
        "{}\n",
        by_num
            .values()
            .map(|(_, l)| l.as_str())
            .collect::<Vec<_>>()
            .join("\n")
    );
    dest = dest.to_uppercase();
    let dirp = PathBuf::from(dir.trim());
    let path = dirp.join(format!("{dest}.m"));
    if path.exists() {
        let _ = std::fs::copy(&path, dirp.join(format!("{dest}.m.bak")));
    }
    std::fs::write(&path, &source)
        .map_err(|e| format!("[ZS] error escribiendo {}: {e}", path.display()))?;
    host.add_routine(dest.clone(), source);
    Ok(Value::String(format!(
        "ok · {} ({} líneas) · recargada en caliente ✓",
        path.display(),
        by_num.len()
    )))
}

fn sub_str(s: &Subscript) -> String {
    match s {
        Subscript::String(x) => x.clone(),
        Subscript::Number(n) => n.to_string(),
    }
}

/// `$DEVICE("zroutines:rollback", NAME)` — restaura routines/NAME.m desde el
/// .bak (la versión anterior al último ZS) y recarga en caliente. Fix 18-sep.
fn zs_rollback(host: &mut MemoryHost, args: &[Value]) -> Result<Value, String> {
    let name = args
        .first()
        .map(|v| v.as_string())
        .unwrap_or_default()
        .trim()
        .to_uppercase();
    if name.is_empty() {
        return Err("[ZS] uso: $DEVICE(\"zroutines:rollback\",\"NAME\")".to_string());
    }
    let dir = host
        .values
        .get(&(
            "SYSINFO".to_string(),
            vec![Subscript::String("routines_dir".to_string())],
        ))
        .map(|v| v.as_string())
        .unwrap_or_default();
    if dir.trim().is_empty() {
        return Err("[ZS] sin ^SYSINFO(\"routines_dir\")".to_string());
    }
    let dirp = PathBuf::from(dir.trim());
    let path = dirp.join(format!("{name}.m"));
    let bak = dirp.join(format!("{name}.m.bak"));
    if !bak.exists() {
        return Err(format!("[ZS] no hay {name}.m.bak para restaurar"));
    }
    let src = std::fs::read_to_string(&bak).map_err(|e| format!("[ZS] leyendo .bak: {e}"))?;
    std::fs::write(&path, &src).map_err(|e| format!("[ZS] escribiendo {name}.m: {e}"))?;
    host.add_routine(name.clone(), src);
    Ok(Value::String(format!(
        "ok · {name} restaurada del .bak · recargada en caliente ✓"
    )))
}
