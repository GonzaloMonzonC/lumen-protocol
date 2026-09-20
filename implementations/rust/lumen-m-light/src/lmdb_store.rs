//! lmdb_store.rs — backend LMDB (feature "lmdb") para MemoryHost.
//!
//! Modo DIRECTO: las operaciones van contra LMDB (mmap) SIN precargar la PDB en
//! el BTreeMap → «solo el puntero en RAM» (RSS acotado por la caché del kernel;
//! medido en la DS216se: 2–4× más rápido que SQLite, hasta 14× en caliente).
//!
//! Layout de claves:  ns_bytes || 0x00 || encode_subkey(subs)
//!   - `ns` es ASCII sin 0x00 → el separador 0x00 es inequívoco.
//!   - subkey = encoding canónico del camino SQLite: 01+f64BE (nums) /
//!     02+ascii+FF (strings), y un 0xFF FINAL de formato (encode_subkey).
//!
//! ⚠️ Dos sutilezas del encoding (verificadas con tests 20-sep-2026):
//!   1) El 0xFF final es TERMINADOR del nodo: los descendientes de `subs`
//!      empiezan con byte 01/02 (< 0xFF) y ordenan ANTES del nodo. Para rangos
//!      de subárbol el prefijo va SIN ese terminador:
//!      rango = (P, P+0x00FF]  con P = ns||0||concat(encode_one_sub(subs)).
//!   2) El byte-order NO es el canónico de M para strings-prefijo ("ab" < "a" en
//!      bytes; "a" < "ab" canónico). Por eso $O enumera hijos con saltos de
//!      cursor (log n por hijo) y luego ordena con `canonical_cmp` igual que el
//!      host RAM → paridad exacta entre backends.
//!
//! Valores: value.as_string().as_bytes() — misma convención que la columna
//!   `value` de SQLite (el conversor SQLite→LMDB copia 1:1).
//!
//! Transacciones TSTART/TCOMMIT/TROLLBACK: anidables con undo-log por nivel
//! (mismo patrón que el RedbHost de lumen-pdb). Cada SET/KILL es durable al
//! momento (autocommit); el rollback deshace por claves. Sin atomicidad ante
//! crash a mitad de txn — igual que el camino SQLite actual (que también
//! escribe al momento); mejora futura: mantener un RwTxn real abierto.
//!
//! Hechos en el hierro (19/20-sep-2026): heed 0.22 compila a armv7-unknown-
//! linux-musleabi (con wrapper tools/cc-arm.py + vendor-patch de lmdb-master-sys
//! para cross-builds desde Windows) y CORRE en la DS216se (kernel 3.2).
//! mapsize: LUMEN_LMDB_MAPSIZE_MB (default 1024; clamp ≤1400 en 32-bit).

use crate::host::{decode_subkey, encode_one_sub, GlobalEntry};
use crate::{Subscript, Value};
use heed::types::Bytes;
use heed::{Database, Env, EnvOpenOptions};
use std::ops::Bound;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

/// Entrada del undo-log: clave + valor previo (None = la clave no existía).
#[derive(Clone)]
struct UndoEntry {
    key: Vec<u8>,
    previous: Option<Vec<u8>>,
}

/// Caché de hijos por nivel (para $O): clave = prefijo del parent.
struct OrderCache {
    version: u64,
    map: std::collections::HashMap<Vec<u8>, Vec<Subscript>>,
}

pub struct LmdbStore {
    env: Env,
    db: Database<Bytes, Bytes>,
    /// Un Vec de entradas por nivel de TSTART, en orden cronológico.
    undo: Vec<Vec<UndoEntry>>,
    /// Caché de hijos por parent para $O (invalidada por versión en cada write).
    /// ⚠️ Asume un único proceso escritor (modelo del nodo); otro proceso que
    /// escriba no la invalida (el modo LMDB del motor es de proceso único).
    order_cache: Mutex<OrderCache>,
    write_version: AtomicU64,
}

impl Clone for LmdbStore {
    fn clone(&self) -> Self {
        // Comparte el env (mismo proceso; modelo estándar de LMDB) y re-abre el
        // handle de la DB por nombre — barato, no toca ficheros.
        let rtxn = self.env.read_txn().expect("lmdb clone: read_txn");
        let db = self
            .env
            .open_database::<Bytes, Bytes>(&rtxn, Some("globals"))
            .expect("lmdb clone: open_database")
            .expect("lmdb clone: db globals existe");
        Self {
            env: self.env.clone(),
            db,
            undo: self.undo.clone(),
            order_cache: Mutex::new(OrderCache { version: 0, map: Default::default() }),
            write_version: AtomicU64::new(self.write_version.load(Ordering::Relaxed)),
        }
    }
}

/// Clave-prefijo SIN el 0xFF final de formato: ns || 0x00 || concat(encode_one_sub).
/// Es el prefijo que cubre el subárbol entero de `subs` (nodo + descendientes).
fn prefix_key(ns: &str, subs: &[Subscript]) -> Vec<u8> {
    let mut k = Vec::with_capacity(ns.len() + 1 + subs.len() * 10 + 2);
    k.extend_from_slice(ns.as_bytes());
    k.push(0);
    for s in subs {
        k.extend(encode_one_sub(s));
    }
    k
}

/// Clave exacta del nodo `subs`: prefix != + 0xFF final (= encode_subkey envuelto).
fn node_key(ns: &str, subs: &[Subscript]) -> Vec<u8> {
    let mut k = prefix_key(ns, subs);
    k.push(0xFF);
    k
}

/// Devuelve (ns, subkey_bytes) de una clave. None si no hay separador (clave ajena).
fn split_ns(key: &[u8]) -> Option<(&str, &[u8])> {
    let i = key.iter().position(|b| *b == 0)?;
    std::str::from_utf8(&key[..i]).ok().map(|ns| (ns, &key[i + 1..]))
}

/// bytes → Value (misma política que la carga de SQLite: String).
fn bytes_to_value(b: &[u8]) -> Value {
    Value::String(String::from_utf8_lossy(b).into_owned())
}

fn map_err<E: std::fmt::Display>(what: &str, e: E) -> String {
    format!("LMDB {what}: {e}")
}

impl LmdbStore {
    pub fn open(dir: &str) -> Result<Self, String> {
        std::fs::create_dir_all(dir).map_err(|e| map_err(&format!("mkdir({dir})"), e))?;

        let mut mapsize_mb: usize = std::env::var("LUMEN_LMDB_MAPSIZE_MB")
            .ok()
            .and_then(|v| v.trim().parse().ok())
            .unwrap_or(1024);
        // 32-bit: el mapa debe caber en el espacio de direcciones (DS216se:
        // 2048 MB = ENOMEM; 1536 MB OK). Clamp de seguridad.
        if cfg!(target_pointer_width = "32") && mapsize_mb > 1400 {
            mapsize_mb = 1400;
        }

        let env = unsafe {
            EnvOpenOptions::new()
                .map_size(mapsize_mb * 1024 * 1024)
                .max_dbs(4)
                .open(dir)
                .map_err(|e| map_err(&format!("open({dir})"), e))?
        };
        let mut wtxn = env.write_txn().map_err(|e| map_err("write_txn(init)", e))?;
        let db: Database<Bytes, Bytes> = env
            .create_database(&mut wtxn, Some("globals"))
            .map_err(|e| map_err("create_database", e))?;
        wtxn.commit().map_err(|e| map_err("commit(init)", e))?;

        Ok(Self {
            env,
            db,
            undo: Vec::new(),
            order_cache: Mutex::new(OrderCache { version: 0, map: Default::default() }),
            write_version: AtomicU64::new(1),
        })
    }

    /// Tamaño del mapa (diagnóstico).
    pub fn mapsize_bytes(&self) -> usize {
        self.env.info().map_size
    }

    // ── operaciones crudas (ns + subs → bytes) ──────────────────────────

    pub fn get_raw(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Vec<u8>>, String> {
        let key = node_key(ns, subs);
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn", e))?;
        Ok(self
            .db
            .get(&rtxn, &key)
            .map_err(|e| map_err("get", e))?
            .map(|v| v.to_vec()))
    }

    pub fn set_raw(&mut self, ns: &str, subs: &[Subscript], val: &[u8]) -> Result<(), String> {
        let key = node_key(ns, subs);
        if !self.undo.is_empty() {
            let prev = self.get_raw(ns, subs)?;
            if let Some(level) = self.undo.last_mut() {
                level.push(UndoEntry { key: key.clone(), previous: prev });
            }
        }
        let mut wtxn = self.env.write_txn().map_err(|e| map_err("write_txn(set)", e))?;
        self.db
            .put(&mut wtxn, &key, val)
            .map_err(|e| map_err("put", e))?;
        wtxn.commit().map_err(|e| map_err("commit(set)", e))?;
        self.invalidate();
        Ok(())
    }

    /// Inserción masiva en UNA sola write-transaction (conversores / bulk load).
    /// `rows` = (ns, subkey YA codificado, value bytes). No entra en el undo-log
    /// (uso: migración one-shot fuera de transacciones M).
    pub fn put_many(&mut self, rows: &[(String, Vec<u8>, Vec<u8>)]) -> Result<usize, String> {
        let mut wtxn = self.env.write_txn().map_err(|e| map_err("write_txn(put_many)", e))?;
        for (ns, subkey, val) in rows {
            let mut k = Vec::with_capacity(ns.len() + 1 + subkey.len());
            k.extend_from_slice(ns.as_bytes());
            k.push(0);
            k.extend_from_slice(subkey);
            self.db.put(&mut wtxn, &k, val).map_err(|e| map_err("put_many", e))?;
        }
        wtxn.commit().map_err(|e| map_err("commit(put_many)", e))?;
        self.invalidate();
        Ok(rows.len())
    }

    /// Nº total de claves (verificación del conversor).
    pub fn count(&self) -> Result<u64, String> {
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(count)", e))?;
        self.db.len(&rtxn).map_err(|e| map_err("len", e))
    }

    /// Lectura cruda por subkey ya codificado (verificación del conversor).
    pub fn get_raw_subkey(&self, ns: &str, subkey: &[u8]) -> Result<Option<Vec<u8>>, String> {
        let mut k = Vec::with_capacity(ns.len() + 1 + subkey.len());
        k.extend_from_slice(ns.as_bytes());
        k.push(0);
        k.extend_from_slice(subkey);
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn", e))?;
        Ok(self
            .db
            .get(&rtxn, &k)
            .map_err(|e| map_err("get", e))?
            .map(|v| v.to_vec()))
    }

    /// KILL ^ns(subs...): borra el nodo y todo su subárbol. Devuelve nº de claves.
    /// Rango: (P, P+0xFF] con P sin terminador final — cubre nodo+descendientes
    /// y NADA más (el byte tras P en un descendiente es 01/02 < FF; nada tras
    /// el nodo P+FF en el formato).
    pub fn kill_raw(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        let start = prefix_key(ns, subs);
        let mut end = start.clone();
        end.push(0xFF);

        // 1) recoger las claves afectadas (para el undo-log, si hay txn activa)
        let undo_active = !self.undo.is_empty();
        if undo_active {
            let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(kill)", e))?;
            let mut to_undo: Vec<UndoEntry> = Vec::new();
            let iter = self
                .db
                .range(
                    &rtxn,
                    &(Bound::Excluded(start.as_slice()), Bound::Included(end.as_slice())),
                )
                .map_err(|e| map_err("range(kill)", e))?;
            for item in iter {
                let (k, v) = item.map_err(|e| map_err("iter(kill)", e))?;
                to_undo.push(UndoEntry { key: k.to_vec(), previous: Some(v.to_vec()) });
            }
            drop(rtxn);
            if let Some(level) = self.undo.last_mut() {
                level.append(&mut to_undo);
            }
        }

        // 2) borrar el rango entero
        let mut wtxn = self.env.write_txn().map_err(|e| map_err("write_txn(kill)", e))?;
        let n = self
            .db
            .delete_range(
                &mut wtxn,
                &(Bound::Excluded(start.as_slice()), Bound::Included(end.as_slice())),
            )
            .map_err(|e| map_err("delete_range", e))?;
        wtxn.commit().map_err(|e| map_err("commit(kill)", e))?;
        self.invalidate();
        Ok(n as u64)
    }

    /// $DATA: 0 / 1 / 10 / 11 (solo local).
    pub fn data_raw(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        let start = prefix_key(ns, subs);
        let mut node = start.clone();
        node.push(0xFF);
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(data)", e))?;
        let own = self
            .db
            .get(&rtxn, &node)
            .map_err(|e| map_err("get(data)", e))?
            .is_some();
        // hijo = primera clave del rango que no sea el propio nodo (el nodo
        // ordena DESPUÉS de sus descendientes, así que si hay hijo, sale antes).
        let mut child = false;
        let iter = self
            .db
            .range(
                &rtxn,
                &(Bound::Excluded(start.as_slice()), Bound::Included(node.as_slice())),
            )
            .map_err(|e| map_err("range(data)", e))?;
        for item in iter {
            let (k, _v) = item.map_err(|e| map_err("iter(data)", e))?;
            if k != node.as_slice() {
                child = true;
                break;
            }
        }
        Ok(match (own, child) {
            (true, true) => 11,
            (true, false) => 1,
            (false, true) => 10,
            (false, false) => 0,
        })
    }

    /// Enumera los hijos directos de `parent` en orden canónico M (números por
    /// valor, luego strings lexicográficas — igual que el host RAM).
    /// Saltos de cursor: O(log n) por hijo, UNA vez por parent (caché hasta el
    /// siguiente write) → $O queda O(log k) por paso.
    pub fn order_candidates(&self, ns: &str, parent: &[Subscript]) -> Result<Vec<Subscript>, String> {
        let pfx = prefix_key(ns, parent);
        if let Some(list) = self.cache_get(&pfx) {
            return Ok(list);
        }
        let list = self.enumerate_children(&pfx)?;
        self.cache_put(pfx, list.clone());
        Ok(list)
    }

    /// Enumeración cruda (byte-order con saltos) + re-orden canónico. Sin caché.
    fn enumerate_children(&self, pfx: &[u8]) -> Result<Vec<Subscript>, String> {
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(cand)", e))?;
        let mut out: Vec<Subscript> = Vec::new();
        let mut seek = pfx.to_vec();

        loop {
            let item = self
                .db
                .get_greater_than(&rtxn, seek.as_slice())
                .map_err(|e| map_err("cand(next)", e))?;
            let (k, _v) = match item {
                Some(kv) => kv,
                None => break,
            };
            if !k.starts_with(pfx) || k.len() <= pfx.len() {
                break;
            }
            let rest = &k[pfx.len()..];
            if rest[0] == 0xFF {
                break; // nodo del propio `parent` (P+FF) → no hay más hijos
            }
            // ⚠️ Boundary ESTRUCTURAL del primer sub (no fiarse del decode: el
            // decoder manglea nums cuyo f64-BE contiene 0xFF — bug pre-existente
            // del core; con él, el saltar con un sub mal decodificado corta la
            // enumeración). Formato del encoder actual: 01 → 01+8B (9 bytes);
            // 02 → 02+ascii+FF (hasta el FF inclusive).
            let boundary = match rest[0] {
                0x01 => 9usize.min(rest.len()),
                0x02 => rest
                    .iter()
                    .position(|&b| b == 0xFF)
                    .map(|p| p + 1)
                    .unwrap_or(rest.len()),
                _ => break,
            };
            if let Some(sub) = decode_subkey(&rest[..boundary]).into_iter().next() {
                out.push(sub);
            }
            // saltar el subárbol del sub: P + bytes-del-sub + 0xFF (su nodo máx.)
            let mut jump = pfx.to_vec();
            jump.extend_from_slice(&rest[..boundary]);
            jump.push(0xFF);
            seek = jump;
        }
        // Orden canónico M + dedup (el byte-order no vale para strings-prefijo)
        out.sort_by(|a, b| a.canonical_cmp(b));
        out.dedup();
        Ok(out)
    }

    fn cache_get(&self, pfx: &[u8]) -> Option<Vec<Subscript>> {
        let c = self.order_cache.lock().ok()?;
        if c.version != self.write_version.load(Ordering::Relaxed) {
            return None;
        }
        c.map.get(pfx).cloned()
    }

    fn cache_put(&self, pfx: Vec<u8>, list: Vec<Subscript>) {
        if let Ok(mut c) = self.order_cache.lock() {
            let v = self.write_version.load(Ordering::Relaxed);
            if c.version != v {
                c.map.clear();
                c.version = v;
            }
            if c.map.len() > 32 {
                c.map.clear();
            }
            c.map.insert(pfx, list);
        }
    }

    /// Invalida la caché de $O (cualquier write cambia los hijos).
    fn invalidate(&self) {
        self.write_version.fetch_add(1, Ordering::Relaxed);
    }

    /// $O forward/backward con semántica canónica idéntica al host RAM:
    /// búsqueda binaria sobre la lista de hijos (cacheada).
    pub fn order_raw(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        let candidates = self.order_candidates(ns, parent)?;
        if direction >= 0 {
            let start = match current {
                Some(cur) => candidates
                    .partition_point(|c| c.canonical_cmp(cur) != std::cmp::Ordering::Greater),
                None => 0,
            };
            Ok(candidates.get(start).cloned())
        } else {
            let end = match current {
                Some(cur) => candidates
                    .partition_point(|c| c.canonical_cmp(cur) == std::cmp::Ordering::Less),
                None => candidates.len(),
            };
            Ok(end.checked_sub(1).and_then(|i| candidates.get(i).cloned()))
        }
    }

    /// Todas las entradas (dumps, fibers, ffi) — decodifica ns + subs + value.
    pub fn entries_raw(&self) -> Result<Vec<GlobalEntry>, String> {
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(entries)", e))?;
        let mut out: Vec<GlobalEntry> = Vec::new();
        for item in self.db.iter(&rtxn).map_err(|e| map_err("iter(entries)", e))? {
            let (k, v) = item.map_err(|e| map_err("row(entries)", e))?;
            if let Some((ns, subkey)) = split_ns(k) {
                out.push(GlobalEntry {
                    ns: ns.to_string(),
                    subs: decode_subkey(subkey),
                    value: bytes_to_value(v),
                });
            }
        }
        Ok(out)
    }

    /// Volcado ^NS("doc",id,"texto") → [(id, texto)] sin materializar todo (filtra).
    pub fn rag_docs(&self, ns: &str) -> Result<Vec<(String, String)>, String> {
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(rag)", e))?;
        let pfx = prefix_key(ns, &[]);
        let mut end = pfx.clone();
        end.push(0xFF);
        let mut out = Vec::new();
        let iter = self
            .db
            .range(
                &rtxn,
                &(Bound::Excluded(pfx.as_slice()), Bound::Included(end.as_slice())),
            )
            .map_err(|e| map_err("range(rag)", e))?;
        for item in iter {
            let (k, v) = item.map_err(|e| map_err("iter(rag)", e))?;
            let subs = decode_subkey(&k[pfx.len()..]);
            if subs.len() != 3 {
                continue;
            }
            let es_doc = matches!(&subs[0], Subscript::String(x) if x.as_str() == "doc");
            let es_texto = matches!(&subs[2], Subscript::String(x) if x.as_str() == "texto");
            if es_doc && es_texto {
                let txt = String::from_utf8_lossy(v).into_owned();
                if !txt.trim().is_empty() {
                    let id = match &subs[1] {
                        Subscript::String(x) => x.clone(),
                        Subscript::Number(n) => n.to_string(),
                    };
                    out.push((id, txt));
                }
            }
        }
        Ok(out)
    }

    // ── transacciones (undo-log por nivel) ─────────────────────────────

    pub fn tstart(&mut self) {
        self.undo.push(Vec::new());
    }

    pub fn tlevel(&self) -> usize {
        self.undo.len()
    }

    pub fn tcommit(&mut self) -> Result<(), String> {
        self.undo
            .pop()
            .map(|_| ())
            .ok_or_else(|| "TCOMMIT without TSTART".to_string())
    }

    pub fn trollback(&mut self) -> Result<(), String> {
        let level = self
            .undo
            .pop()
            .ok_or_else(|| "TROLLBACK without TSTART".to_string())?;
        let mut wtxn = self.env.write_txn().map_err(|e| map_err("write_txn(rollback)", e))?;
        for e in level.into_iter().rev() {
            match e.previous {
                Some(p) => {
                    self.db.put(&mut wtxn, &e.key, &p).map_err(|e2| map_err("put(rollback)", e2))?;
                }
                None => {
                    self.db.delete(&mut wtxn, &e.key).map_err(|e2| map_err("del(rollback)", e2))?;
                }
            }
        }
        wtxn.commit().map_err(|e| map_err("commit(rollback)", e))?;
        self.invalidate();
        Ok(())
    }
}
