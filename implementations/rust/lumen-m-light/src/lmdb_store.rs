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
//! Transacciones TSTART/TCOMMIT/TROLLBACK: write-behind anidables. Los writes
//! dentro de una txn se acumulan en memoria (con read-your-writes) y se aplican
//! al disco en UNA sola write-txn al TCOMMIT más externo → 1 fsync por txn
//! (los sets sueltos pagan ~70 ms de fsync cada uno en HDD; con TS/TC = 1).
//! TROLLBACK descarta el nivel SIN tocar disco. SET/KILL fuera de txn:
//! autocommit durable (semántica intacta). Sin atomicidad ante crash a mitad
//! de txn (se pierden los pendientes sin aplicar; el disco queda consistente).
//! put_many no se usa dentro de txns.
//!
//! Hechos en el hierro (19/20-sep-2026): heed 0.22 compila a armv7-unknown-
//! linux-musleabi (con wrapper tools/cc-arm.py + vendor-patch de lmdb-master-sys
//! para cross-builds desde Windows) y CORRE en la DS216se (kernel 3.2).
//! mapsize: LUMEN_LMDB_MAPSIZE_MB (default 1024; clamp ≤1400 en 32-bit).

use crate::host::{decode_subkey, encode_one_sub, first_sub_with_len, GlobalEntry};
use crate::{Subscript, Value};
use heed::types::Bytes;
use heed::{Database, Env, EnvOpenOptions};
use std::ops::Bound;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

/// Nivel de txn (write-behind): clave → (previo [None=no existía], nuevo [None=borrar]).
/// El "previo" se captura en el PRIMER toque de la clave dentro del nivel (visible
/// vía niveles externos + disco) → el merge de savepoint conserva el más antiguo
/// y el rollback externo restaura el estado pre-txn correcto.
#[derive(Clone, Default)]
struct TxnLevel {
    ops: std::collections::HashMap<Vec<u8>, (Option<Vec<u8>>, Option<Vec<u8>>)>,
}

/// Caché de hijos por nivel (para $O): clave = prefijo del parent.
struct OrderCache {
    version: u64,
    map: std::collections::HashMap<Vec<u8>, Vec<Subscript>>,
}

/// Siguiente (dir>=0) / anterior (dir<0) respecto a `current` en una lista de
/// hijos ordenada canónicamente (misma semántica que el host RAM).
fn order_search(
    list: &[Subscript],
    current: Option<&Subscript>,
    direction: i32,
) -> Option<Subscript> {
    if direction >= 0 {
        let start = match current {
            Some(cur) => list
                .partition_point(|c| c.canonical_cmp(cur) != std::cmp::Ordering::Greater),
            None => 0,
        };
        list.get(start).cloned()
    } else {
        let end = match current {
            Some(cur) => list.partition_point(|c| c.canonical_cmp(cur) == std::cmp::Ordering::Less),
            None => list.len(),
        };
        end.checked_sub(1).and_then(|i| list.get(i).cloned())
    }
}

pub struct LmdbStore {
    env: Env,
    db: Database<Bytes, Bytes>,
    /// Niveles de TSTART abiertos (write-behind), en orden cronológico.
    txns: Vec<TxnLevel>,
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
            txns: self.txns.clone(),
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

        // NOSYNC opcional (LUMEN_LMDB_NOSYNC=1): sin fsync por commit — para
        // cargas de escritura masiva en HDD (los datos siguen consistentes ante
        // crash; puede perderse la cola de writes no sincronizada). Default: OFF.
        let nosync = std::env::var("LUMEN_LMDB_NOSYNC")
            .map(|v| v == "1" || v.eq_ignore_ascii_case("true"))
            .unwrap_or(false);

        let mut opts = EnvOpenOptions::new();
        opts.map_size(mapsize_mb * 1024 * 1024).max_dbs(4);
        if nosync {
            // SAFETY: NO_SYNC solo relaja la durabilidad (sin fsync por commit);
            // el env se usa en un nodo monoproceso con acceso controlado.
            unsafe {
                opts.flags(heed::EnvFlags::NO_SYNC);
            }
        }
        let env = unsafe {
            opts.open(dir)
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
            txns: Vec::new(),
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
        if let Some(v) = self.overlay_get(&key) {
            return Ok(v); // la txn manda (read-your-writes)
        }
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn", e))?;
        Ok(self
            .db
            .get(&rtxn, &key)
            .map_err(|e| map_err("get", e))?
            .map(|v| v.to_vec()))
    }

    /// Estado de una clave según los niveles abiertos (innermost primero).
    /// None = ningún nivel opina; Some(None) = borrada; Some(Some(v)) = valor.
    fn overlay_get(&self, key: &[u8]) -> Option<Option<Vec<u8>>> {
        for level in self.txns.iter().rev() {
            if let Some((_prev, next)) = level.ops.get(key) {
                return Some(next.clone());
            }
        }
        None
    }

    /// Valor visible AHORA (overlay de txns + disco).
    fn visible(&self, key: &[u8]) -> Result<Option<Vec<u8>>, String> {
        if let Some(v) = self.overlay_get(key) {
            return Ok(v);
        }
        let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(visible)", e))?;
        Ok(self
            .db
            .get(&rtxn, key)
            .map_err(|e| map_err("get(visible)", e))?
            .map(|v| v.to_vec()))
    }

    pub fn set_raw(&mut self, ns: &str, subs: &[Subscript], val: &[u8]) -> Result<(), String> {
        let key = node_key(ns, subs);
        if !self.txns.is_empty() {
            // Write-behind: acumular en el nivel abierto (cero disco hasta TCOMMIT).
            let prev = self.visible(&key)?;
            if let Some(level) = self.txns.last_mut() {
                level.ops.entry(key).or_insert((prev, None)).1 = Some(val.to_vec());
            }
            return Ok(());
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
        if !self.txns.is_empty() {
            return Err("LMDB put_many: no soportado con TSTART abierta (uso: conversores, fuera de txns)".to_string());
        }
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

        if !self.txns.is_empty() {
            // Write-behind: registrar deletes en el nivel (sin tocar disco).
            let mut keys: Vec<Vec<u8>> = Vec::new();
            {
                let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(kill)", e))?;
                let iter = self
                    .db
                    .range(
                        &rtxn,
                        &(Bound::Excluded(start.as_slice()), Bound::Included(end.as_slice())),
                    )
                    .map_err(|e| map_err("range(kill)", e))?;
                for item in iter {
                    let (k, _v) = item.map_err(|e| map_err("iter(kill)", e))?;
                    // ya "borrada" en el overlay → no cuenta
                    if matches!(self.overlay_get(k), Some(None)) {
                        continue;
                    }
                    keys.push(k.to_vec());
                }
            }
            // + claves creadas en txns bajo el prefijo
            for level in &self.txns {
                for (k, (_prev, next)) in level.ops.iter() {
                    if next.is_some()
                        && k.len() > start.len()
                        && k.starts_with(&start)
                        && !keys.iter().any(|e| e == k)
                    {
                        keys.push(k.clone());
                    }
                }
            }
            let n = keys.len() as u64;
            let mut ops: Vec<(Vec<u8>, Option<Vec<u8>>)> = Vec::with_capacity(keys.len());
            for k in keys {
                let prev = self.visible(&k)?;
                ops.push((k, prev));
            }
            if let Some(level) = self.txns.last_mut() {
                for (k, prev) in ops {
                    level.ops.entry(k).or_insert((prev, None)).1 = None;
                }
            }
            return Ok(n);
        }

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
        let own = match self.overlay_get(&node) {
            Some(v) => v.is_some(),
            None => self
                .db
                .get(&rtxn, &node)
                .map_err(|e| map_err("get(data)", e))?
                .is_some(),
        };
        // hijo = primera clave del rango que no sea el propio nodo (el nodo
        // ordena DESPUÉS de sus descendientes, así que si hay hijo, sale antes).
        // Con txn abierta: se saltan las claves borradas por el overlay y se
        // añaden los hijos creados en txns.
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
            if k == node.as_slice() {
                continue;
            }
            if matches!(self.overlay_get(k), Some(None)) {
                continue; // borrada en txn
            }
            child = true;
            break;
        }
        if !child && !self.txns.is_empty() {
            'outer: for level in &self.txns {
                for (k, (_prev, next)) in level.ops.iter() {
                    if next.is_some()
                        && k.len() > start.len()
                        && k.starts_with(&start)
                        && k.as_slice() != node.as_slice()
                    {
                        child = true;
                        break 'outer;
                    }
                }
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
        if !self.txns.is_empty() {
            // Con txn abierta: sin caché (los pendientes pueden añadir/quitar hijos).
            return self.enumerate_children_txn(&pfx);
        }
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
            // Primer sub + longitud EXACTA vía la MISMA lógica que decode_subkey
            // (fix 2026-09-20: el boundary "estructural" anterior cortaba la lista
            // con nums canónicos cuyo f64 contiene 0xFF en mantisa — ahora cursor
            // y valores nunca divergen porque comparten decode_step).
            let (sub, boundary) = match first_sub_with_len(rest) {
                Some(v) => v,
                None => break,
            };
            out.push(sub);
            // saltar el subárbol del sub: P + bytes-del-sub + 0xFF (su nodo máx.)
            let mut jump = pfx.to_vec();
            jump.extend_from_slice(&rest[..boundary]);
            jump.push(0xFF);
            // Garantía de avance ESTRICTO (anti-bucle): si el salto no supera
            // la clave actual (encoding inesperado → jump = prefijo de k),
            // seek = k → get_greater_than(k) da la siguiente clave estricta.
            // Cualquier caso degenerado = avance + dedup final, nunca ∞.
            seek = if jump.as_slice() > k { jump } else { k.to_vec() };
        }
        // Orden canónico M + dedup (el byte-order no vale para strings-prefijo)
        out.sort_by(|a, b| a.canonical_cmp(b));
        out.dedup();
        Ok(out)
    }

    /// Enumera hijos con txn abierta: disco + overlay (altas y bajas), sin caché.
    fn enumerate_children_txn(&self, pfx: &[u8]) -> Result<Vec<Subscript>, String> {
        let mut out = self.enumerate_children(pfx)?;
        let mut added: Vec<Vec<u8>> = Vec::new(); // bytes del primer sub (nuevo)
        let mut del_candidates: Vec<Vec<u8>> = Vec::new(); // bytes del primer sub (candidato a borrar)
        for level in &self.txns {
            for (k, (_prev, next)) in level.ops.iter() {
                if k.len() > pfx.len() && k.starts_with(pfx) {
                    let rest = &k[pfx.len()..];
                    if rest[0] == 0xFF {
                        continue; // nodo del propio parent
                    }
                    if let Some((_sub, len)) = first_sub_with_len(rest) {
                        let enc = rest[..len].to_vec();
                        if next.is_some() {
                            added.push(enc);
                        } else {
                            del_candidates.push(enc);
                        }
                    }
                }
            }
        }
        // ¿algún candidato a borrado ya NO existe? → quitar de la lista
        let mut dead: Vec<Vec<u8>> = Vec::new();
        for enc in del_candidates {
            let mut p2 = pfx.to_vec();
            p2.extend_from_slice(&enc);
            if !self.subtree_exists(&p2)? {
                // Comparar con la MISMA forma que encode_one_sub (los subkeys
                // qpdb/poli llevan \xff tras el número; encode_one_sub no).
                let canon = first_sub_with_len(&enc)
                    .map(|(s, _)| encode_one_sub(&s))
                    .unwrap_or(enc);
                dead.push(canon);
            }
        }
        out.retain(|s| {
            let e = encode_one_sub(s);
            !dead.iter().any(|d| *d == e)
        });
        for enc in added {
            if let Some((sub, _len)) = first_sub_with_len(&enc) {
                out.push(sub);
            }
        }
        out.sort_by(|a, b| a.canonical_cmp(b));
        out.dedup();
        Ok(out)
    }

    /// ¿Existe alguna clave viva bajo el subárbol `p2` (disco u overlay, con
    /// precedencia del nivel más interno)? Rango (p2, p2+0xFF]: node + descendientes.
    fn subtree_exists(&self, p2: &[u8]) -> Result<bool, String> {
        let mut end = p2.to_vec();
        end.push(0xFF);
        {
            let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(exists)", e))?;
            let iter = self
                .db
                .range(
                    &rtxn,
                    &(Bound::Excluded(p2), Bound::Included(end.as_slice())),
                )
                .map_err(|e| map_err("range(exists)", e))?;
            for item in iter {
                let (k, _v) = item.map_err(|e| map_err("iter(exists)", e))?;
                match self.overlay_get(k) {
                    Some(None) => continue, // borrada esperando commit
                    _ => return Ok(true),
                }
            }
        }
        // claves vivas solo en overlay (creadas en txn)
        let mut seen: std::collections::HashSet<Vec<u8>> = Default::default();
        for level in &self.txns {
            for k2 in level.ops.keys() {
                if k2.len() > p2.len() && k2.starts_with(p2) && seen.insert(k2.clone()) {
                    if let Some(Some(_)) = self.overlay_get(k2) {
                        return Ok(true);
                    }
                }
            }
        }
        Ok(false)
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

    /// Respuesta de $O desde la caché SIN clonar la lista completa:
    /// None = caché no válida (toca enumerar); Some(r) = resultado directo.
    fn cached_order(
        &self,
        pfx: &[u8],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Option<Option<Subscript>> {
        let c = self.order_cache.lock().ok()?;
        if c.version != self.write_version.load(Ordering::Relaxed) {
            return None;
        }
        let list = c.map.get(pfx)?;
        Some(order_search(list, current, direction))
    }

    /// $O forward/backward con semántica canónica idéntica al host RAM.
    /// Camino caliente SIN clonar la lista cacheada: la búsqueda binaria va
    /// dentro del candado y solo se clona el subscript devuelto. (Antes cada
    /// paso clonaba los k hijos → 0,6 ms/paso con 82k hijos; incidente
    /// 22-sep-2026: scan de ^CHANGES en 52 s cuando debe ser <1 s.)
    pub fn order_raw(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        let pfx = prefix_key(ns, parent);
        if self.txns.is_empty() {
            if let Some(r) = self.cached_order(&pfx, current, direction) {
                return Ok(r);
            }
            let list = self.enumerate_children(&pfx)?;
            let r = order_search(&list, current, direction);
            self.cache_put(pfx, list); // se mueve a la caché, sin clon
            return Ok(r);
        }
        let list = self.enumerate_children_txn(&pfx)?;
        Ok(order_search(&list, current, direction))
    }

    /// Todas las entradas (dumps, fibers, ffi) — decodifica ns + subs + value.
    /// Con txn abierta, fusiona el overlay (borrados fuera, pendientes dentro).
    pub fn entries_raw(&self) -> Result<Vec<GlobalEntry>, String> {
        let mut map: std::collections::BTreeMap<Vec<u8>, Vec<u8>> = Default::default();
        {
            let rtxn = self.env.read_txn().map_err(|e| map_err("read_txn(entries)", e))?;
            for item in self.db.iter(&rtxn).map_err(|e| map_err("iter(entries)", e))? {
                let (k, v) = item.map_err(|e| map_err("row(entries)", e))?;
                map.insert(k.to_vec(), v.to_vec());
            }
        }
        for level in &self.txns {
            for k in level.ops.keys() {
                match self.overlay_get(k) {
                    Some(Some(v)) => {
                        map.insert(k.clone(), v);
                    }
                    Some(None) => {
                        map.remove(k);
                    }
                    None => {}
                }
            }
        }
        let mut out: Vec<GlobalEntry> = Vec::new();
        for (k, v) in &map {
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

    // ── transacciones (write-behind por nivel) ─────────────────────────

    pub fn tstart(&mut self) {
        self.txns.push(TxnLevel::default());
    }

    pub fn tlevel(&self) -> usize {
        self.txns.len()
    }

    /// Cierra el nivel: si queda alguno abierto → merge de savepoint (conserva el
    /// previo más antiguo); si es el externo → aplica TODO en UNA write-txn (1 fsync).
    pub fn tcommit(&mut self) -> Result<(), String> {
        let level = self
            .txns
            .pop()
            .ok_or_else(|| "TCOMMIT without TSTART".to_string())?;
        if let Some(parent) = self.txns.last_mut() {
            for (k, (prev, next)) in level.ops {
                match parent.ops.get_mut(&k) {
                    Some(e) => e.1 = next,
                    None => {
                        parent.ops.insert(k, (prev, next));
                    }
                }
            }
            return Ok(());
        }
        if level.ops.is_empty() {
            return Ok(());
        }
        let mut wtxn = self.env.write_txn().map_err(|e| map_err("write_txn(tcommit)", e))?;
        for (k, (_prev, next)) in level.ops {
            match next {
                Some(v) => {
                    self.db.put(&mut wtxn, &k, &v).map_err(|e| map_err("put(tcommit)", e))?;
                }
                None => {
                    self.db.delete(&mut wtxn, &k).map_err(|e| map_err("del(tcommit)", e))?;
                }
            }
        }
        wtxn.commit().map_err(|e| map_err("commit(tcommit)", e))?;
        self.invalidate();
        Ok(())
    }

    /// Descarta el nivel abierto: los pendientes NUNCA tocaron disco → se tiran.
    pub fn trollback(&mut self) -> Result<(), String> {
        self.txns
            .pop()
            .map(|_| ())
            .ok_or_else(|| "TROLLBACK without TSTART".to_string())
    }
}
