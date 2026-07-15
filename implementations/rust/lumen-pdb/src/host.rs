//! host.rs — RedbHost: el trait `Host` de la VM M-Light directamente sobre
//! el engine redb (Fase 5.1). Permite ejecutar la VM Rust standalone, sin
//! el roundtrip Python/pdb_tools.
//!
//! Semántica:
//!   - Valores como JSON UTF-8 (misma convención que la columna `value`
//!     de SQLite y que el migrador de Fase 4).
//!   - TSTART/TCOMMIT/TROLLBACK anidables sobre UNA WriteTransaction redb
//!     + undo-log por nivel (los savepoints de redb exigen transacción
//!     limpia, así que el anidamiento se deshace por claves tocadas).
//!   - Rutinas leídas de ^ROUTINE(nombre, línea), como el host live.
//!   - LOCK: contadores reentrantes en memoria — este host es de proceso
//!     único; la contención multi-proceso vive en _lock_table (SQLite).

use crate::globals::{data_in, kill_collect, order_in, Pdb};
use crate::subkey::{decode_subkey, encode_subkey, Sub};
use lumen_mlight::{Host, Subscript, Value};
use redb::{ReadableTable, WriteTransaction};
use std::collections::HashMap;

struct UndoEntry {
    ns: String,
    key: Vec<u8>,
    previous: Option<Vec<u8>>,
}

pub struct RedbHost {
    pdb: Pdb,
    txn: Option<WriteTransaction>,
    /// Un Vec de entradas por nivel de TSTART, en orden cronológico.
    undo: Vec<Vec<UndoEntry>>,
    locks: HashMap<(String, Vec<Subscript>), u64>,
    input: Vec<String>,
}

fn subs_to_key(subs: &[Subscript]) -> Vec<u8> {
    let subs: Vec<Sub> = subs
        .iter()
        .map(|sub| match sub {
            Subscript::Number(n) => Sub::Num(*n),
            Subscript::String(s) => Sub::Str(s.clone()),
        })
        .collect();
    encode_subkey(&subs)
}

fn seg_to_subscript(seg: &[u8]) -> Option<Subscript> {
    decode_subkey(seg).into_iter().next().map(|sub| match sub {
        Sub::Num(n) => Subscript::Number(n),
        Sub::Str(s) => Subscript::String(s),
        Sub::Null => Subscript::String(String::new()),
    })
}

fn value_to_bytes(value: &Value) -> Result<Vec<u8>, String> {
    serde_json::to_vec(&value.to_json()).map_err(|e| e.to_string())
}

fn bytes_to_value(bytes: &[u8]) -> Option<Value> {
    if bytes.is_empty() {
        // Sentinel del migrador: nodo estructural sin valor propio.
        return None;
    }
    Some(
        serde_json::from_slice::<serde_json::Value>(bytes)
            .map(Value::from_json)
            .unwrap_or_else(|_| Value::String(String::from_utf8_lossy(bytes).into_owned())),
    )
}

impl RedbHost {
    pub fn open(path: &str) -> Result<Self, String> {
        Ok(Self {
            pdb: Pdb::open(path)?,
            txn: None,
            undo: Vec::new(),
            locks: HashMap::new(),
            input: Vec::new(),
        })
    }

    pub fn push_input(&mut self, value: impl Into<String>) {
        self.input.push(value.into());
    }

    /// Checkpoint duradero del engine subyacente.
    pub fn flush(&self) -> Result<(), String> {
        self.pdb.flush()
    }

    fn record_undo(&mut self, ns: &str, key: Vec<u8>, previous: Option<Vec<u8>>) {
        if let Some(level) = self.undo.last_mut() {
            level.push(UndoEntry {
                ns: ns.to_string(),
                key,
                previous,
            });
        }
    }
}

impl Drop for RedbHost {
    fn drop(&mut self) {
        if let Some(txn) = self.txn.take() {
            let _ = txn.abort();
        }
    }
}

impl Host for RedbHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        let key = subs_to_key(subs);
        let bytes = match &self.txn {
            Some(txn) => {
                let t = txn
                    .open_table(Pdb::table_def(ns))
                    .map_err(|e| e.to_string())?;
                let bytes = t
                    .get(key.as_slice())
                    .map_err(|e| e.to_string())?
                    .map(|g| g.value().to_vec());
                bytes
            }
            None => self.pdb.get(ns, &key)?,
        };
        Ok(bytes.as_deref().and_then(bytes_to_value))
    }

    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        let key = subs_to_key(subs);
        let bytes = value_to_bytes(&value)?;
        match &self.txn {
            Some(txn) => {
                let previous = {
                    let mut t = txn
                        .open_table(Pdb::table_def(ns))
                        .map_err(|e| e.to_string())?;
                    let previous = t
                        .insert(key.as_slice(), bytes.as_slice())
                        .map_err(|e| e.to_string())?
                        .map(|g| g.value().to_vec());
                    previous
                };
                self.record_undo(ns, key, previous);
                Ok(())
            }
            None => self.pdb.set(ns, &key, &bytes),
        }
    }

    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        let key = subs_to_key(subs);
        match &self.txn {
            Some(txn) => {
                let deleted = {
                    let mut t = txn
                        .open_table(Pdb::table_def(ns))
                        .map_err(|e| e.to_string())?;
                    let pairs = kill_collect(&t, &key)?;
                    for (k, _) in &pairs {
                        t.remove(k.as_slice()).map_err(|e| e.to_string())?;
                    }
                    pairs
                };
                let count = deleted.len() as u64;
                for (k, v) in deleted {
                    self.record_undo(ns, k, Some(v));
                }
                Ok(count)
            }
            None => self.pdb.kill(ns, &key),
        }
    }

    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        let key = subs_to_key(subs);
        match &self.txn {
            Some(txn) => {
                let t = txn
                    .open_table(Pdb::table_def(ns))
                    .map_err(|e| e.to_string())?;
                data_in(&t, &key)
            }
            None => self.pdb.data(ns, &key),
        }
    }

    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        let parent_key = subs_to_key(parent);
        let current_seg = current.map(|sub| subs_to_key(std::slice::from_ref(sub)));
        let seg = match &self.txn {
            Some(txn) => {
                let t = txn
                    .open_table(Pdb::table_def(ns))
                    .map_err(|e| e.to_string())?;
                order_in(&t, &parent_key, current_seg.as_deref(), direction)?
            }
            None => self
                .pdb
                .order(ns, &parent_key, current_seg.as_deref(), direction)?,
        };
        Ok(seg.as_deref().and_then(seg_to_subscript))
    }

    fn transaction_start(&mut self) -> Result<(), String> {
        if self.txn.is_none() {
            self.txn = Some(self.pdb.begin()?);
        }
        self.undo.push(Vec::new());
        Ok(())
    }

    fn transaction_commit(&mut self) -> Result<(), String> {
        match self.undo.len() {
            0 => Err("TCOMMIT without TSTART".to_string()),
            1 => {
                let txn = self.txn.take().ok_or("transaction lost")?;
                txn.commit().map_err(|e| e.to_string())?;
                self.undo.clear();
                Ok(())
            }
            _ => {
                // Anidado: el trabajo del hijo pasa a formar parte del padre.
                let child = self.undo.pop().unwrap_or_default();
                if let Some(parent) = self.undo.last_mut() {
                    parent.extend(child);
                }
                Ok(())
            }
        }
    }

    fn transaction_rollback(&mut self) -> Result<(), String> {
        match self.undo.len() {
            0 => Err("TROLLBACK without TSTART".to_string()),
            1 => {
                let txn = self.txn.take().ok_or("transaction lost")?;
                txn.abort().map_err(|e| e.to_string())?;
                self.undo.clear();
                Ok(())
            }
            _ => {
                let entries = self.undo.pop().unwrap_or_default();
                let txn = self.txn.as_ref().ok_or("transaction lost")?;
                for entry in entries.into_iter().rev() {
                    let mut t = txn
                        .open_table(Pdb::table_def(&entry.ns))
                        .map_err(|e| e.to_string())?;
                    match entry.previous {
                        Some(previous) => {
                            t.insert(entry.key.as_slice(), previous.as_slice())
                                .map_err(|e| e.to_string())?;
                        }
                        None => {
                            t.remove(entry.key.as_slice()).map_err(|e| e.to_string())?;
                        }
                    }
                }
                Ok(())
            }
        }
    }

    fn transaction_level(&self) -> usize {
        self.undo.len()
    }

    /// Rutinas desde ^ROUTINE(nombre, línea) — mismo layout que el host live.
    fn routine(&self, name: &str) -> Result<Option<String>, String> {
        let name = name.to_uppercase();
        let parent = vec![Subscript::String(name)];
        let mut lines: Vec<(f64, String)> = Vec::new();
        let mut current: Option<Subscript> = None;
        while let Some(next) = self.order("ROUTINE", &parent, current.as_ref(), 1)? {
            if let Subscript::Number(line_no) = next {
                let mut subs = parent.clone();
                subs.push(Subscript::Number(line_no));
                if let Some(value) = self.get("ROUTINE", &subs)? {
                    lines.push((line_no, value.as_string()));
                }
            }
            current = Some(next);
        }
        if lines.is_empty() {
            return Ok(None);
        }
        lines.sort_by(|a, b| a.0.total_cmp(&b.0));
        Ok(Some(
            lines
                .into_iter()
                .map(|(_, source)| source)
                .collect::<Vec<_>>()
                .join("\n"),
        ))
    }

    fn read(&mut self) -> Result<String, String> {
        if self.input.is_empty() {
            Ok(String::new())
        } else {
            Ok(self.input.remove(0))
        }
    }

    fn lock(&mut self, ns: &str, subs: &[Subscript], _timeout: Option<f64>) -> Result<bool, String> {
        *self
            .locks
            .entry((ns.to_string(), subs.to_vec()))
            .or_insert(0) += 1;
        Ok(true)
    }

    fn unlock(&mut self, ns: &str, subs: &[Subscript]) -> Result<(), String> {
        let key = (ns.to_string(), subs.to_vec());
        if let Some(count) = self.locks.get_mut(&key) {
            *count -= 1;
            if *count == 0 {
                self.locks.remove(&key);
            }
        }
        Ok(())
    }

    fn unlock_all(&mut self) -> Result<(), String> {
        self.locks.clear();
        Ok(())
    }
}
