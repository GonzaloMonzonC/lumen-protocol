//! `mvm-mcp-serve` — expone un MVM como servidor MCP.
//!
//! Uso:
//!   mvm-mcp-serve --pdb <ruta.db> [--host 127.0.0.1] [--port 8790]
//!   mvm-mcp-serve --globals <globals.json> [--port 8790]
//!
//! Las tools que sirve salen de `^TOOLS` de esa PDB. El formato es el mismo que
//! usa el motor para el catálogo de tools:
//!   ^TOOLS("__names")          = "saludar,contar"
//!   ^TOOLS("saludar","desc")   = "Saluda a alguien"
//!   ^TOOLS("saludar","kind")   = "m:%SALUDAR"
//!   ^TOOLS("saludar","params") = {"type":"object","properties":{...}}
//!
//! Al llamar la tool, cada argumento se escribe en `^MCPARGS("clave")` y se
//! ejecuta la rutina `%SALUDAR`; su salida vuelve como texto MCP.

use lumen_mlight::host::GlobalEntry;
use lumen_mlight::mcp_server::{serve, ServeConfig};
use lumen_mlight::value::{Subscript, Value};

fn usage() -> ! {
    eprintln!(
        "uso: mvm-mcp-serve --pdb <ruta.db> [--host 127.0.0.1] [--port 8790]\n\
         \x20    mvm-mcp-serve --globals <globals.json> [--port 8790]"
    );
    std::process::exit(2)
}

fn main() {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let mut cfg = ServeConfig::default();
    let mut pdb: Option<String> = None;
    let mut globals_json: Option<String> = None;

    let mut i = 0;
    while i < args.len() {
        match args[i].as_str() {
            "--pdb" => {
                i += 1;
                pdb = args.get(i).cloned();
            }
            "--globals" => {
                i += 1;
                globals_json = args.get(i).cloned();
            }
            "--host" => {
                i += 1;
                if let Some(h) = args.get(i) {
                    cfg.host_addr = h.clone();
                }
            }
            "--port" => {
                i += 1;
                if let Some(p) = args.get(i).and_then(|s| s.parse().ok()) {
                    cfg.port = p;
                }
            }
            "--timeout" => {
                i += 1;
                if let Some(t) = args.get(i).and_then(|s| s.parse().ok()) {
                    cfg.timeout_secs = t;
                }
            }
            "-h" | "--help" => usage(),
            other => {
                eprintln!("argumento desconocido: {other}");
                usage()
            }
        }
        i += 1;
    }

    let entries: Vec<GlobalEntry> = if let Some(p) = pdb {
        load_pdb(&p)
    } else if let Some(g) = globals_json {
        load_globals_json(&g)
    } else {
        usage()
    };

    println!(
        "[mvm-mcp-serve] {} globals cargados · {} tools en ^TOOLS",
        entries.len(),
        count_tools(&entries)
    );

    if let Err(e) = serve(cfg, entries) {
        eprintln!("[mvm-mcp-serve] no se pudo arrancar: {e}");
        std::process::exit(1);
    }
}

/// Cuenta las tools para el mensaje de arranque (feedback inmediato).
fn count_tools(entries: &[GlobalEntry]) -> usize {
    entries
        .iter()
        .find(|e| {
            e.ns == "TOOLS" && e.subs.len() == 1 && format!("{:?}", e.subs[0]).contains("__names")
        })
        .map(|e| match &e.value {
            Value::String(s) => s.split(',').filter(|x| !x.trim().is_empty()).count(),
            _ => 0,
        })
        .unwrap_or(0)
}

/// Carga los globals de una PDB SQLite (esquema `_globals(ns, subkey, value)`).
///
/// `subkey` está en el formato empaquetado de M (separador 0x02), igual que lo
/// lee el resto del motor. Se decodifica aquí para no depender del host.
fn load_pdb(path: &str) -> Vec<GlobalEntry> {
    let conn = match rusqlite::Connection::open_with_flags(
        path,
        rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
    ) {
        Ok(c) => c,
        Err(e) => {
            eprintln!("[mvm-mcp-serve] no se puede abrir {path}: {e}");
            std::process::exit(1);
        }
    };
    let mut stmt = match conn.prepare("SELECT ns, subkey, value FROM _globals") {
        Ok(s) => s,
        Err(e) => {
            eprintln!("[mvm-mcp-serve] PDB sin tabla _globals: {e}");
            std::process::exit(1);
        }
    };
    let rows = stmt.query_map([], |row| {
        let ns: String = row.get(0)?;
        let subkey: Vec<u8> = row.get(1)?;
        let value: Option<String> = row.get(2)?;
        Ok((ns, subkey, value.unwrap_or_default()))
    });
    let mut out = Vec::new();
    if let Ok(rows) = rows {
        for r in rows.flatten() {
            let (ns, subkey, value) = r;
            out.push(GlobalEntry {
                ns,
                subs: decode_subkey(&subkey),
                value: Value::String(value),
            });
        }
    }
    out
}

/// El `subkey` va como `\x02nivel1\x02nivel2...`; cada nivel es texto o número.
/// Se usa `Value::String` para los subíndices de texto y `Subscript::Number`
/// para los que parsean como número (las líneas de `^ROUTINE`, p.ej.).
fn decode_subkey(raw: &[u8]) -> Vec<Subscript> {
    let s = String::from_utf8_lossy(raw);
    s.split('\u{2}')
        .filter(|p| !p.is_empty())
        .map(|p| {
            if let Ok(n) = p.parse::<f64>() {
                Subscript::Number(n)
            } else {
                Subscript::String(p.to_string())
            }
        })
        .collect()
}

/// Carga globals desde un JSON: `[{"ns","subs":[...],"value"}]`.
fn load_globals_json(path: &str) -> Vec<GlobalEntry> {
    let txt = match std::fs::read_to_string(path) {
        Ok(t) => t,
        Err(e) => {
            eprintln!("[mvm-mcp-serve] no se puede leer {path}: {e}");
            std::process::exit(1);
        }
    };
    match serde_json::from_str(&txt) {
        Ok(v) => v,
        Err(e) => {
            eprintln!("[mvm-mcp-serve] JSON invalido: {e}");
            std::process::exit(1);
        }
    }
}
