use crate::{Subscript, Value};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::collections::HashMap;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GlobalEntry {
    pub ns: String,
    #[serde(default)]
    pub subs: Vec<Subscript>,
    pub value: Value,
}

pub trait Host {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String>;
    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String>;
    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String>;
    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String>;
    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String>;
    fn transaction_start(&mut self) -> Result<(), String>;
    fn transaction_commit(&mut self) -> Result<(), String>;
    fn transaction_rollback(&mut self) -> Result<(), String>;
    fn transaction_level(&self) -> usize;
    fn routine(&self, _name: &str) -> Result<Option<String>, String> {
        Ok(None)
    }
    fn read(&mut self) -> Result<String, String> {
        Ok(String::new())
    }
    fn read_would_block(&self) -> bool {
        false
    }
    /// LOCK ^NS(subs). `timeout=None` = intención de bloquear: el host hace
    /// UN intento no bloqueante y la VM cede y reintenta si devuelve false.
    /// Con timeout el host puede esperar hasta ese presupuesto (segundos).
    fn lock(&mut self, _ns: &str, _subs: &[Subscript], _timeout: Option<f64>) -> Result<bool, String> {
        Ok(true)
    }
    fn unlock(&mut self, _ns: &str, _subs: &[Subscript]) -> Result<(), String> {
        Ok(())
    }
    fn unlock_all(&mut self) -> Result<(), String> {
        Ok(())
    }
}

#[derive(Debug, Clone, Default)]
pub struct MemoryHost {
    values: BTreeMap<(String, Vec<Subscript>), Value>,
    transactions: Vec<BTreeMap<(String, Vec<Subscript>), Value>>,
    routines: HashMap<String, String>,
    input: Vec<String>,
    locks: HashMap<(String, Vec<Subscript>), u64>,
}

impl MemoryHost {
    pub fn from_entries(entries: Vec<GlobalEntry>) -> Self {
        let mut host = Self::default();
        for entry in entries {
            host.values.insert((entry.ns, entry.subs), entry.value);
        }
        host
    }

    pub fn entries(&self) -> Vec<GlobalEntry> {
        let mut entries: Vec<_> = self
            .values
            .iter()
            .map(|((ns, subs), value)| GlobalEntry {
                ns: ns.clone(),
                subs: subs.clone(),
                value: value.clone(),
            })
            .collect();
        entries.sort_by(|a, b| {
            a.ns.cmp(&b.ns)
                .then_with(|| compare_subscripts(&a.subs, &b.subs))
        });
        entries
    }

    pub fn add_routine(&mut self, name: impl Into<String>, source: impl Into<String>) {
        self.routines
            .insert(name.into().to_uppercase(), source.into());
    }

    pub fn push_input(&mut self, value: impl Into<String>) {
        self.input.push(value.into());
    }

    pub fn held_locks(&self) -> usize {
        self.locks.len()
    }
}

fn is_prefix(prefix: &[Subscript], value: &[Subscript]) -> bool {
    value.len() >= prefix.len() && prefix.iter().zip(value).all(|(a, b)| a == b)
}

fn compare_subscripts(a: &[Subscript], b: &[Subscript]) -> std::cmp::Ordering {
    for (left, right) in a.iter().zip(b) {
        let cmp = left.canonical_cmp(right);
        if cmp != std::cmp::Ordering::Equal {
            return cmp;
        }
    }
    a.len().cmp(&b.len())
}

impl Host for MemoryHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        Ok(self.values.get(&(ns.to_string(), subs.to_vec())).cloned())
    }

    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        self.values.insert((ns.to_string(), subs.to_vec()), value);
        Ok(())
    }

    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        let before = self.values.len();
        self.values.retain(|(candidate_ns, candidate), _| {
            candidate_ns != ns || !is_prefix(subs, candidate)
        });
        Ok((before - self.values.len()) as u64)
    }

    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        let own = self.values.contains_key(&(ns.to_string(), subs.to_vec()));
        let child = self.values.keys().any(|(candidate_ns, candidate)| {
            candidate_ns == ns && candidate.len() > subs.len() && is_prefix(subs, candidate)
        });
        Ok(match (own, child) {
            (true, true) => 11,
            (true, false) => 1,
            (false, true) => 10,
            (false, false) => 0,
        })
    }

    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        // Construir key prefix para BTreeMap::range
        let prefix_key = (ns.to_string(), parent.to_vec());
        let start_key = if let Some(cur) = current {
            let mut key = parent.to_vec();
            key.push(cur.clone());
            (ns.to_string(), key)
        } else {
            prefix_key.clone()
        };
        if direction >= 0 {
            // Avanzar: buscar primer key >= start_key que tenga el prefijo
            // Saltamos el match exacto con current (range() lo incluye)
            for (k, _v) in self.values.range(start_key..) {
                let (key_ns, key_subs) = k;
                if key_ns.as_str() != ns { break; }
                if key_subs.len() <= parent.len() { continue; }
                if !is_prefix(parent, key_subs) { continue; }
                let candidate = &key_subs[parent.len()];
                // Saltar el item actual (range() incluye el punto de inicio)
                if let Some(cur) = current {
                    if candidate.canonical_cmp(cur) == std::cmp::Ordering::Equal {
                        continue;
                    }
                }
                return Ok(Some(candidate.clone()));
            }
            Ok(None)
        } else {
            // Retroceder: buscar último key con el prefijo
            // Cuando current=None, iterar desde el final del mapa
            let range: Box<dyn Iterator<Item = _>> = if let Some(cur) = current {
                let mut key = parent.to_vec();
                key.push(cur.clone());
                let start = (ns.to_string(), key);
                Box::new(self.values.range(..start).rev())
            } else {
                Box::new(self.values.range(..).rev())
            };
            for (k, _v) in range {
                let (key_ns, key_subs) = k;
                if key_ns.as_str() != ns { continue; }
                if key_subs.len() <= parent.len() { continue; }
                if !is_prefix(parent, key_subs) { continue; }
                let candidate = &key_subs[parent.len()];
                if let Some(cur) = current {
                    if candidate.canonical_cmp(cur) == std::cmp::Ordering::Equal {
                        continue;
                    }
                }
                return Ok(Some(candidate.clone()));
            }
            Ok(None)
        }
    }

    fn transaction_start(&mut self) -> Result<(), String> {
        self.transactions.push(self.values.clone());
        Ok(())
    }

    fn transaction_commit(&mut self) -> Result<(), String> {
        self.transactions
            .pop()
            .map(|_| ())
            .ok_or_else(|| "TCOMMIT without TSTART".to_string())
    }

    fn transaction_rollback(&mut self) -> Result<(), String> {
        let snapshot = self
            .transactions
            .pop()
            .ok_or_else(|| "TROLLBACK without TSTART".to_string())?;
        self.values = snapshot;
        Ok(())
    }

    fn transaction_level(&self) -> usize {
        self.transactions.len()
    }

    fn routine(&self, name: &str) -> Result<Option<String>, String> {
        Ok(self.routines.get(&name.to_uppercase()).cloned())
    }

    fn read(&mut self) -> Result<String, String> {
        if self.input.is_empty() {
            Ok(String::new())
        } else {
            Ok(self.input.remove(0))
        }
    }

    // Un MemoryHost tiene un único dueño (una VM): los locks son contadores
    // reentrantes y siempre se adquieren. La contención real vive en los
    // hosts multi-proceso (LiveHost/pdb_lock).
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
