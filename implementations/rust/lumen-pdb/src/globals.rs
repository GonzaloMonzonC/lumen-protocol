//! globals.rs — operaciones de globals M sobre redb (Fase 4).
//!
//! Modelo: una tabla redb por namespace, clave = subkey codificada
//! (subkey.rs), valor = bytes (JSON UTF-8, igual que la columna value
//! de SQLite). Semántica portada de pdb_tools.py y verificada con la
//! suite de conformidad:
//!   - KILL borra nodo + subárbol (rango (key, key+FFFFFFFF))
//!   - $DATA: 0/1/10/11 con prefix-check real del siguiente subkey
//!   - $ORDER: siguiente/anterior subscript del nivel del padre,
//!     saltando los hijos del actual

use crate::subkey::segment_at;
use redb::{
    Database, Durability, ReadableTable, ReadableTableMetadata, TableDefinition, TableHandle,
};
use std::ops::Bound;

/// Cota superior del subárbol de `key` (misma convención que tool_kill).
pub(crate) fn subtree_hi(key: &[u8]) -> Vec<u8> {
    let mut hi = key.to_vec();
    hi.extend_from_slice(&[0xFF, 0xFF, 0xFF, 0xFF]);
    hi
}

/// $DATA sobre cualquier tabla legible (comprometida o transacción abierta).
pub(crate) fn data_in<T>(t: &T, key: &[u8]) -> Result<u8, String>
where
    T: ReadableTable<&'static [u8], &'static [u8]>,
{
    // El migrador representa SQLite NULL (nodo puramente estructural)
    // como un value raw vacío. Los valores de usuario son siempre JSON,
    // por lo que nunca colisionan con este sentinel.
    let has_value = t
        .get(key)
        .map_err(|e| e.to_string())?
        .map(|g| !g.value().is_empty())
        .unwrap_or(false);
    // hijos ⟺ el primer subkey posterior lleva `key` como prefijo
    let mut has_children = false;
    let mut range = t
        .range::<&[u8]>((Bound::Excluded(key), Bound::Unbounded))
        .map_err(|e| e.to_string())?;
    if let Some(entry) = range.next() {
        let (k, _) = entry.map_err(|e| e.to_string())?;
        let kb = k.value();
        has_children = kb.len() > key.len() && &kb[..key.len()] == key;
    }
    Ok(match (has_value, has_children) {
        (true, true) => 11,
        (true, false) => 1,
        (false, true) => 10,
        (false, false) => 0,
    })
}

/// $ORDER sobre cualquier tabla legible: siguiente (dir=1) o anterior
/// (dir=-1) segmento de subscript al nivel del `parent`. Devuelve el
/// segmento codificado del hermano, o None si no hay más.
pub(crate) fn order_in<T>(
    t: &T,
    parent: &[u8],
    current_seg: Option<&[u8]>,
    dir: i32,
) -> Result<Option<Vec<u8>>, String>
where
    T: ReadableTable<&'static [u8], &'static [u8]>,
{
    let parent_hi = subtree_hi(parent);

    let pick = |kb: &[u8]| -> Option<Vec<u8>> {
        if kb.len() <= parent.len() || &kb[..parent.len()] != parent {
            return None;
        }
        segment_at(kb, parent.len()).map(|r| kb[r].to_vec())
    };

    if dir >= 0 {
        // lo: tras el subárbol del actual, o el propio parent
        let lo: Vec<u8> = match current_seg {
            Some(seg) => {
                let mut v = parent.to_vec();
                v.extend_from_slice(seg);
                subtree_hi(&v)
            }
            None => parent.to_vec(),
        };
        let range = t
            .range::<&[u8]>((
                Bound::Excluded(lo.as_slice()),
                if parent.is_empty() {
                    Bound::Unbounded
                } else {
                    Bound::Excluded(parent_hi.as_slice())
                },
            ))
            .map_err(|e| e.to_string())?;
        for entry in range {
            let (k, _) = entry.map_err(|e| e.to_string())?;
            if let Some(seg) = pick(k.value()) {
                return Ok(Some(seg));
            }
        }
    } else {
        // hacia atrás: última clave < hi dentro del prefijo del parent
        let hi: Vec<u8> = match current_seg {
            Some(seg) => {
                let mut v = parent.to_vec();
                v.extend_from_slice(seg);
                v // excluido: no incluye el nodo actual ni sus hijos
            }
            None => parent_hi.clone(),
        };
        let range = t
            .range::<&[u8]>((
                if parent.is_empty() {
                    Bound::Unbounded
                } else {
                    Bound::Excluded(parent)
                },
                Bound::Excluded(hi.as_slice()),
            ))
            .map_err(|e| e.to_string())?;
        for entry in range.rev() {
            let (k, _) = entry.map_err(|e| e.to_string())?;
            if let Some(seg) = pick(k.value()) {
                return Ok(Some(seg));
            }
        }
    }
    Ok(None)
}

/// Claves del nodo exacto + subárbol, con sus valores (para KILL con undo).
pub(crate) fn kill_collect<T>(t: &T, key: &[u8]) -> Result<Vec<(Vec<u8>, Vec<u8>)>, String>
where
    T: ReadableTable<&'static [u8], &'static [u8]>,
{
    let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
    if let Some(g) = t.get(key).map_err(|e| e.to_string())? {
        pairs.push((key.to_vec(), g.value().to_vec()));
    }
    let hi = subtree_hi(key);
    let range = t
        .range::<&[u8]>((Bound::Excluded(key), Bound::Excluded(hi.as_slice())))
        .map_err(|e| e.to_string())?;
    for entry in range {
        let (k, v) = entry.map_err(|e| e.to_string())?;
        pairs.push((k.value().to_vec(), v.value().to_vec()));
    }
    Ok(pairs)
}

pub struct Pdb {
    db: Database,
    /// Política de durabilidad de los commits. `Eventual` (default) es el
    /// mismo tradeoff que SQLite WAL + synchronous=NORMAL (Fase 1a): un
    /// corte de energía puede perder los últimos commits, nunca corromper.
    /// `flush()` fuerza un checkpoint duradero.
    durability: Durability,
}

impl Pdb {
    pub fn open(path: &str) -> Result<Self, String> {
        let db = Database::create(path).map_err(|e| e.to_string())?;
        let durability = match std::env::var("LUMEN_PDB_DURABILITY").as_deref() {
            Ok("immediate") => Durability::Immediate,
            _ => Durability::Eventual,
        };
        Ok(Self { db, durability })
    }

    pub(crate) fn begin(&self) -> Result<redb::WriteTransaction, String> {
        let mut txn = self.db.begin_write().map_err(|e| e.to_string())?;
        txn.set_durability(self.durability);
        Ok(txn)
    }

    /// Checkpoint duradero: commit vacío con Durability::Immediate.
    pub fn flush(&self) -> Result<(), String> {
        let mut txn = self.db.begin_write().map_err(|e| e.to_string())?;
        txn.set_durability(Durability::Immediate);
        txn.commit().map_err(|e| e.to_string())
    }

    pub(crate) fn table_def<'a>(ns: &'a str) -> TableDefinition<'a, &'static [u8], &'static [u8]> {
        TableDefinition::new(ns)
    }

    // ── SET ──
    pub fn set(&self, ns: &str, key: &[u8], value: &[u8]) -> Result<(), String> {
        let txn = self.begin()?;
        {
            let mut t = txn
                .open_table(Self::table_def(ns))
                .map_err(|e| e.to_string())?;
            t.insert(key, value).map_err(|e| e.to_string())?;
        }
        txn.commit().map_err(|e| e.to_string())
    }

    /// Bulk insert en una sola transacción (migrador / batch_set).
    pub fn set_many(&self, ns: &str, pairs: &[(Vec<u8>, Vec<u8>)]) -> Result<usize, String> {
        let txn = self.begin()?;
        {
            let mut t = txn
                .open_table(Self::table_def(ns))
                .map_err(|e| e.to_string())?;
            for (k, v) in pairs {
                t.insert(k.as_slice(), v.as_slice())
                    .map_err(|e| e.to_string())?;
            }
        }
        txn.commit().map_err(|e| e.to_string())?;
        Ok(pairs.len())
    }

    // ── GET ──
    pub fn get(&self, ns: &str, key: &[u8]) -> Result<Option<Vec<u8>>, String> {
        let txn = self.db.begin_read().map_err(|e| e.to_string())?;
        let t = match txn.open_table(Self::table_def(ns)) {
            Ok(t) => t,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(e) => return Err(e.to_string()),
        };
        Ok(t.get(key)
            .map_err(|e| e.to_string())?
            .map(|g| g.value().to_vec()))
    }

    // ── KILL (nodo + subárbol) ──
    pub fn kill(&self, ns: &str, key: &[u8]) -> Result<u64, String> {
        let txn = self.begin()?;
        let mut deleted: u64 = 0;
        {
            let mut t = match txn.open_table(Self::table_def(ns)) {
                Ok(t) => t,
                Err(redb::TableError::TableDoesNotExist(_)) => return Ok(0),
                Err(e) => return Err(e.to_string()),
            };
            let to_delete = kill_collect(&t, key)?;
            for (k, _) in &to_delete {
                t.remove(k.as_slice()).map_err(|e| e.to_string())?;
                deleted += 1;
            }
        }
        txn.commit().map_err(|e| e.to_string())?;
        Ok(deleted)
    }

    // ── $DATA ──
    pub fn data(&self, ns: &str, key: &[u8]) -> Result<u8, String> {
        let txn = self.db.begin_read().map_err(|e| e.to_string())?;
        let t = match txn.open_table(Self::table_def(ns)) {
            Ok(t) => t,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(0),
            Err(e) => return Err(e.to_string()),
        };
        data_in(&t, key)
    }

    // ── $ORDER ──
    /// Siguiente (dir=1) o anterior (dir=-1) segmento de subscript al nivel
    /// del `parent`. `current_seg` = segmento codificado del subscript
    /// actual (None = desde el principio/final). Devuelve el segmento
    /// codificado del hermano encontrado, o None si no hay más.
    pub fn order(
        &self,
        ns: &str,
        parent: &[u8],
        current_seg: Option<&[u8]>,
        dir: i32,
    ) -> Result<Option<Vec<u8>>, String> {
        let txn = self.db.begin_read().map_err(|e| e.to_string())?;
        let t = match txn.open_table(Self::table_def(ns)) {
            Ok(t) => t,
            Err(redb::TableError::TableDoesNotExist(_)) => return Ok(None),
            Err(e) => return Err(e.to_string()),
        };
        order_in(&t, parent, current_seg, dir)
    }

    // ── $INCREMENT ──
    /// Incremento atómico. El valor se guarda como JSON (igual que Python:
    /// enteros sin decimales, floats con ellos).
    pub fn incr(&self, ns: &str, key: &[u8], delta: f64) -> Result<f64, String> {
        let txn = self.begin()?;
        let new_val: f64;
        {
            let mut t = txn
                .open_table(Self::table_def(ns))
                .map_err(|e| e.to_string())?;
            let current: f64 = t
                .get(key)
                .map_err(|e| e.to_string())?
                .and_then(|g| std::str::from_utf8(g.value()).ok().map(|s| s.to_owned()))
                .and_then(|s| s.trim().trim_matches('"').parse::<f64>().ok())
                .unwrap_or(0.0);
            new_val = current + delta;
            let serialized = if new_val.fract() == 0.0 && new_val.abs() < 9.0e15 {
                format!("{}", new_val as i64)
            } else {
                format!("{}", new_val)
            };
            t.insert(key, serialized.as_bytes())
                .map_err(|e| e.to_string())?;
        }
        txn.commit().map_err(|e| e.to_string())?;
        Ok(new_val)
    }

    // ── MERGE (copia de subárbol) ──
    pub fn merge(
        &self,
        dst_ns: &str,
        dst_key: &[u8],
        src_ns: &str,
        src_key: &[u8],
    ) -> Result<u64, String> {
        // leer subárbol origen (nodo exacto + descendientes)
        let mut pairs: Vec<(Vec<u8>, Vec<u8>)> = Vec::new();
        {
            let txn = self.db.begin_read().map_err(|e| e.to_string())?;
            let t = match txn.open_table(Self::table_def(src_ns)) {
                Ok(t) => t,
                Err(redb::TableError::TableDoesNotExist(_)) => return Ok(0),
                Err(e) => return Err(e.to_string()),
            };
            if let Some(g) = t.get(src_key).map_err(|e| e.to_string())? {
                pairs.push((src_key.to_vec(), g.value().to_vec()));
            }
            let hi = subtree_hi(src_key);
            let range = t
                .range::<&[u8]>((Bound::Excluded(src_key), Bound::Excluded(hi.as_slice())))
                .map_err(|e| e.to_string())?;
            for entry in range {
                let (k, v) = entry.map_err(|e| e.to_string())?;
                pairs.push((k.value().to_vec(), v.value().to_vec()));
            }
        }
        // reescribir prefijo src_key → dst_key
        let rewritten: Vec<(Vec<u8>, Vec<u8>)> = pairs
            .into_iter()
            .map(|(k, v)| {
                let mut nk = dst_key.to_vec();
                nk.extend_from_slice(&k[src_key.len()..]);
                (nk, v)
            })
            .collect();
        let n = rewritten.len() as u64;
        self.set_many(dst_ns, &rewritten)?;
        Ok(n)
    }

    // ── Namespaces / stats ──
    pub fn namespaces(&self) -> Result<Vec<String>, String> {
        let txn = self.db.begin_read().map_err(|e| e.to_string())?;
        let names = txn
            .list_tables()
            .map_err(|e| e.to_string())?
            .map(|h| h.name().to_string())
            .collect();
        Ok(names)
    }

    pub fn count(&self, ns: &str) -> Result<u64, String> {
        let txn = self.db.begin_read().map_err(|e| e.to_string())?;
        match txn.open_table(Self::table_def(ns)) {
            Ok(t) => t.len().map_err(|e| e.to_string()),
            Err(redb::TableError::TableDoesNotExist(_)) => Ok(0),
            Err(e) => Err(e.to_string()),
        }
    }
}
