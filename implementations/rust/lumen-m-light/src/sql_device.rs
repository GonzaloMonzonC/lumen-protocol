//! Device `sql:query` — consultas contra bases de datos externas.
//!
//! El MVM no lleva un driver por cada motor: eso metería cinco runtimes async
//! y sus CVE en un intérprete de 15k líneas. Este device cubre el caso que sí
//! lo justifica — SQLite local con `rusqlite`, que ya está compilado — y deja
//! el resto por HTTP/MCP, que es como se conectan Postgres, Mongo, Redis, etc.
//! sin tocar el core.
//!
//! # Declaración de conexiones
//!
//! Las conexiones viven en la PDB, nunca en el código:
//!
//! ```text
//! ^CONFIG("sql","ventas","url")  = "sqlite:/ruta/ventas.db"
//! ^CONFIG("sql","ventas","mode") = "ro"        (por defecto) | "rw"
//! ```
//!
//! # Política de escritura
//!
//! **Por defecto solo lectura.** Una conexión `mode=rw` habilita escritura, y
//! aun así solo para sentencias de escritura explícitas. La razón es concreta:
//! el SQL lo puede generar un LLM, y un `DROP TABLE` generado por error no se
//! deshace. La política vive aquí, no en el prompt.
//!
//! # Uso desde M
//!
//! ```text
//! $DEVICE("sql:query","ventas","SELECT nombre FROM clientes LIMIT 5")
//! $DEVICE("sql:exec","ventas","INSERT INTO log VALUES (...)")   ← exige rw
//! ```
//!
//! El resultado es JSON: `{"ok":true,"columns":[...],"rows":[[...]],"count":N}`.

use crate::host::{Host, MemoryHost};
use crate::value::Subscript;
use serde_json::{json, Value as Json};

/// Modo de una conexión declarada.
#[derive(Clone, Copy, Debug, PartialEq)]
pub enum DbMode {
    ReadOnly,
    ReadWrite,
}

impl DbMode {
    pub fn from_decl(raw: &str) -> Self {
        match raw.trim().to_ascii_lowercase().as_str() {
            "rw" | "readwrite" | "read-write" => DbMode::ReadWrite,
            _ => DbMode::ReadOnly, // por defecto: lo restrictivo
        }
    }
}

/// Una conexión resuelta desde `^CONFIG("sql",<nombre>,…)`.
#[derive(Clone, Debug)]
pub struct DbConn {
    pub name: String,
    pub url: String,
    pub mode: DbMode,
}

/// ¿La sentencia es de lectura?
///
/// No es un parser SQL: es un filtro conservador. Si hay duda, se trata como
/// escritura (y por tanto exige `rw`). Un falso positivo solo obliga a declarar
/// `rw`; un falso negativo ejecutaría una escritura donde no toca.
pub fn is_read_query(sql: &str) -> bool {
    let s = sql.trim_start();
    // Ignorar comentarios de cabecera y espacios
    let lower = s.trim_start_matches(|c: char| c.is_whitespace()).to_ascii_lowercase();
    let head = lower
        .trim_start_matches("--")
        .split('\n')
        .last()
        .unwrap_or("")
        .trim_start()
        .to_string();
    let head = if head.is_empty() { lower.as_str() } else { head.as_str() };

    // Palabras que SOLO aparecen en sentencias de escritura. Se buscan en todo
    // el texto (no solo al inicio) porque `WITH ... INSERT` existe.
    const WRITE_WORDS: &[&str] = &[
        "insert", "update", "delete", "drop", "alter", "create", "replace",
        "truncate", "attach", "detach", "pragma", "vacuum", "reindex", "grant",
        "revoke",
    ];
    let padded = format!(" {} ", lower.replace('\n', " ").replace('\t', " "));
    for w in WRITE_WORDS {
        if padded.contains(&format!(" {w} ")) {
            return false;
        }
    }
    // Lectura explícita
    head.starts_with("select") || head.starts_with("with") || head.starts_with("explain")
}

/// Resuelve una conexión declarada en `^CONFIG`.
pub fn resolve(host: &MemoryHost, name: &str) -> Result<DbConn, String> {
    let get = |leaf: &str| -> String {
        host.get(
            "CONFIG",
            &[
                Subscript::String("sql".into()),
                Subscript::String(name.to_string()),
                Subscript::String(leaf.into()),
            ],
        )
        .ok()
        .flatten()
        .map(|v| v.as_string())
        .unwrap_or_default()
    };
    let url = get("url");
    if url.trim().is_empty() {
        return Err(format!(
            "conexion sql '{name}' no declarada: falta ^CONFIG(\"sql\",\"{name}\",\"url\")"
        ));
    }
    Ok(DbConn {
        name: name.to_string(),
        url,
        mode: DbMode::from_decl(&get("mode")),
    })
}

/// Ejecuta una consulta. `write` indica si es `sql:exec` (escritura) o
/// `sql:query` (lectura); la política final combina eso con el modo declarado.
pub fn run_query(
    host: &mut MemoryHost,
    conn_name: &str,
    sql: &str,
    write: bool,
    max_rows: usize,
) -> Result<Json, String> {
    if sql.trim().is_empty() {
        return Err("sql vacio".to_string());
    }
    let conn = resolve(host, conn_name)?;

    let read_only_sql = is_read_query(sql);
    // Doble candado: el device de escritura exige `rw`, y una sentencia de
    // escritura por `sql:query` también (por si alguien la cuela por ahí).
    if (write || !read_only_sql) && conn.mode != DbMode::ReadWrite {
        return Err(format!(
            "conexion '{}' es de solo lectura (mode=ro): no se permite esta sentencia. \
             Declara ^CONFIG(\"sql\",\"{}\",\"mode\")=\"rw\" para habilitar escritura.",
            conn.name, conn.name
        ));
    }

    // Solo sqlite: por ahora. El resto se hace por HTTP/MCP (ver doc del modulo).
    let path = conn
        .url
        .strip_prefix("sqlite:")
        .or_else(|| conn.url.strip_prefix("sqlite://"))
        .ok_or_else(|| {
            format!(
                "url '{}' no soportada: este device solo abre 'sqlite:<ruta>'. \
                 Para {} usa $DEVICE(\"http:*\") o un servidor MCP.",
                conn.url,
                conn.url.split(':').next().unwrap_or("ese motor")
            )
        })?;

    run_sqlite(path, sql, read_only_sql, max_rows)
}

#[cfg(feature = "sqlite")]
fn run_sqlite(path: &str, sql: &str, read_only: bool, max_rows: usize) -> Result<Json, String> {
    use rusqlite::OpenFlags;

    let flags = if read_only {
        OpenFlags::SQLITE_OPEN_READ_ONLY
    } else {
        OpenFlags::SQLITE_OPEN_READ_WRITE
    };
    let conn = rusqlite::Connection::open_with_flags(path, flags)
        .map_err(|e| format!("no se puede abrir '{path}': {e}"))?;

    if read_only {
        let mut stmt = conn
            .prepare(sql)
            .map_err(|e| format!("SQL invalido: {e}"))?;
        let cols: Vec<String> = stmt.column_names().iter().map(|c| c.to_string()).collect();
        let ncols = cols.len();
        let mut rows_out: Vec<Json> = Vec::new();
        let mut rows = stmt.query([]).map_err(|e| format!("error ejecutando: {e}"))?;
        while let Some(row) = rows.next().map_err(|e| format!("error leyendo fila: {e}"))? {
            if rows_out.len() >= max_rows {
                break;
            }
            let mut vals: Vec<Json> = Vec::with_capacity(ncols);
            for i in 0..ncols {
                vals.push(sqlite_value_to_json(row, i));
            }
            rows_out.push(Json::Array(vals));
        }
        let truncated = rows_out.len() >= max_rows;
        Ok(json!({
            "ok": true,
            "columns": cols,
            "rows": rows_out,
            "count": rows_out.len(),
            "truncated": truncated
        }))
    } else {
        let affected = conn
            .execute(sql, [])
            .map_err(|e| format!("error ejecutando escritura: {e}"))?;
        Ok(json!({
            "ok": true,
            "affected": affected,
            "count": affected
        }))
    }
}

#[cfg(feature = "sqlite")]
fn sqlite_value_to_json(row: &rusqlite::Row<'_>, i: usize) -> Json {
    use rusqlite::types::ValueRef;
    match row.get_ref(i) {
        Ok(ValueRef::Null) => Json::Null,
        Ok(ValueRef::Integer(n)) => json!(n),
        Ok(ValueRef::Real(f)) => json!(f),
        Ok(ValueRef::Text(t)) => json!(String::from_utf8_lossy(t)),
        Ok(ValueRef::Blob(b)) => json!(format!("<blob {} bytes>", b.len())),
        Err(_) => Json::Null,
    }
}

#[cfg(not(feature = "sqlite"))]
fn run_sqlite(_path: &str, _sql: &str, _read_only: bool, _max_rows: usize) -> Result<Json, String> {
    Err("build sin feature 'sqlite': el device sql:query no esta disponible".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detecta_lecturas() {
        assert!(is_read_query("SELECT * FROM t"));
        assert!(is_read_query("  select 1"));
        assert!(is_read_query("WITH x AS (SELECT 1) SELECT * FROM x"));
        assert!(is_read_query("EXPLAIN SELECT 1"));
        assert!(is_read_query("SeLeCt nombre FROM clientes"));
    }

    #[test]
    fn detecta_escrituras() {
        assert!(!is_read_query("INSERT INTO t VALUES (1)"));
        assert!(!is_read_query("DELETE FROM t"));
        assert!(!is_read_query("DROP TABLE t"));
        assert!(!is_read_query("UPDATE t SET a=1"));
        assert!(!is_read_query("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x"));
        assert!(!is_read_query("PRAGMA journal_mode=WAL"));
        assert!(!is_read_query("ATTACH DATABASE 'x' AS y"));
    }

    #[test]
    fn ante_la_duda_es_escritura() {
        // basura -> no es lectura -> exige rw
        assert!(!is_read_query("ñ"));
        assert!(!is_read_query(""));
    }

    #[test]
    fn modo_por_defecto_es_lectura() {
        assert_eq!(DbMode::from_decl(""), DbMode::ReadOnly);
        assert_eq!(DbMode::from_decl("ro"), DbMode::ReadOnly);
        assert_eq!(DbMode::from_decl("rw"), DbMode::ReadWrite);
    }
}
