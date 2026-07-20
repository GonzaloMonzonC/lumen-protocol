use crate::{Subscript, Value};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, OnceLock};
use std::thread;

// ── LlmThreadPool — thread pool para LLM calls asíncronas ─────────
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum LlmFutureStatus {
    Pending,
    Dependent(u64), // waiting for another future to resolve first
    Resolved(String),
    Rejected(String),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LlmFuture {
    pub id: u64,
    pub status: LlmFutureStatus,
    pub provider: String,
    pub model: String,
    pub prompt: String,
    pub system: String,
    pub tokens_in: Option<u64>,
    pub tokens_out: Option<u64>,
}

#[derive(Clone, Debug)]
struct WorkItem {
    id: u64,
    provider: String,
    model: String,
    prompt: String,
    system: String,
    api_key: String,
    state: Arc<Mutex<LlmFutureStatus>>,
}

#[derive(Debug)]
pub struct LlmThreadPool {
    next_id: AtomicU64,
    futures: Arc<Mutex<HashMap<u64, Arc<Mutex<LlmFutureStatus>>>>>,
    /// WorkItems pendientes (cadenas esperando que el padre se resuelva)
    pending: Arc<Mutex<HashMap<u64, WorkItem>>>,
    worker_tx: std::sync::mpsc::Sender<WorkItem>,
}

/// Process-wide LLM thread pool (singleton).
fn global_llm_pool() -> &'static LlmThreadPool {
    static POOL: OnceLock<LlmThreadPool> = OnceLock::new();
    POOL.get_or_init(|| LlmThreadPool::new())
}

impl LlmThreadPool {
    pub fn new() -> Self {
        let futures: Arc<Mutex<HashMap<u64, Arc<Mutex<LlmFutureStatus>>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let pending: Arc<Mutex<HashMap<u64, WorkItem>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let (tx, rx) = std::sync::mpsc::channel::<WorkItem>();
        let worker_futures = futures.clone();

        // Worker thread: recibe WorkItems y hace HTTP blocking
        thread::spawn(move || {
            for item in rx {
                let result = Self::do_llm_call(&item);
                if let Err(e) = result {
                    if let Ok(mut state) = item.state.lock() {
                        *state = LlmFutureStatus::Rejected(e);
                    }
                }
            }
        });

        Self {
            next_id: AtomicU64::new(1),
            futures,
            pending,
            worker_tx: tx,
        }
    }

    fn do_llm_call(item: &WorkItem) -> Result<String, String> {
        let url = match item.provider.to_lowercase().as_str() {
            "openrouter" => "https://openrouter.ai/api/v1/chat/completions",
            "deepseek" => "https://api.deepseek.com/v1/chat/completions",
            _ => return Err(format!("unknown provider: {}", item.provider)),
        };

        #[cfg(feature = "minreq")]
        {
            let body = serde_json::json!({
                "model": item.model,
                "messages": [
                    {"role": "system", "content": item.system},
                    {"role": "user", "content": item.prompt}
                ],
                "max_tokens": 4096,
                "temperature": 0.7,
            });

            let body_str = serde_json::to_string(&body)
                .map_err(|e| format!("JSON serialize error: {e}"))?;
            let resp = minreq::post(url)
                .with_header("Authorization", &format!("Bearer {}", item.api_key))
                .with_header("Content-Type", "application/json")
                .with_body(body_str)
                .send()
                .map_err(|e| format!("HTTP error: {e}"))?;

            if resp.status_code != 200 {
                let err_text = resp.as_str().unwrap_or("unknown");
                return Err(format!("API error {}: {}", resp.status_code, err_text));
            }

            let json: serde_json::Value = resp.json()
                .map_err(|e| format!("JSON parse error: {e}"))?;

            let content = json["choices"][0]["message"]["content"]
                .as_str()
                .unwrap_or("")
                .to_string();

            if let Ok(mut state) = item.state.lock() {
                *state = LlmFutureStatus::Resolved(content.clone());
            }

            Ok(content)
        }

        #[cfg(not(feature = "minreq"))]
        { return Err("HTTP client not enabled (minreq feature)".to_string()); }
    }

    pub fn fork(&self, provider: &str, model: &str, prompt: &str, system: &str) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let state = Arc::new(Mutex::new(LlmFutureStatus::Pending));

        let api_key = match provider.to_lowercase().as_str() {
            "openrouter" => std::env::var("OPENROUTER_API_KEY").unwrap_or_default(),
            "deepseek" => std::env::var("DEEPSEEK_API_KEY").unwrap_or_default(),
            _ => String::new(),
        };

        self.futures.lock().unwrap().insert(id, state.clone());

        let item = WorkItem {
            id,
            provider: provider.to_string(),
            model: model.to_string(),
            prompt: prompt.to_string(),
            system: system.to_string(),
            api_key,
            state,
        };

        let _ = self.worker_tx.send(item);
        id
    }

    pub fn poll(&self, id: u64) -> Option<String> {
        let futures = self.futures.lock().unwrap();
        if let Some(state_arc) = futures.get(&id) {
            let status = state_arc.lock().unwrap().clone();
            match status {
                LlmFutureStatus::Pending => None,
                LlmFutureStatus::Dependent(parent_id) => {
                    // Drop the status lock before checking parent
                    drop(status);
                    let parent_status = futures
                        .get(&parent_id)
                        .and_then(|s| s.lock().ok().map(|g| g.clone()));
                    match parent_status {
                        Some(LlmFutureStatus::Resolved(_)) |
                        Some(LlmFutureStatus::Rejected(_)) => {
                            // Parent done! Submit this future to the worker
                            drop(futures);
                            self.submit_pending(id);
                            None
                        }
                        _ => None,
                    }
                }
                LlmFutureStatus::Resolved(text) => Some(text),
                LlmFutureStatus::Rejected(err) => Some(format!("LLM_ERROR: {err}")),
            }
        } else {
            Some("FUTURE_NOT_FOUND".to_string())
        }
    }

    pub fn cancel(&self, id: u64) -> bool {
        self.pending.lock().unwrap().remove(&id);
        self.futures.lock().unwrap().remove(&id).is_some()
    }

    pub fn chain(&self, parent_id: u64, provider: &str, model: &str, prompt: &str, system: &str) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let state = Arc::new(Mutex::new(LlmFutureStatus::Dependent(parent_id)));

        let api_key = match provider.to_lowercase().as_str() {
            "openrouter" => std::env::var("OPENROUTER_API_KEY").unwrap_or_default(),
            "deepseek" => std::env::var("DEEPSEEK_API_KEY").unwrap_or_default(),
            _ => String::new(),
        };

        self.futures.lock().unwrap().insert(id, state.clone());

        let item = WorkItem {
            id,
            provider: provider.to_string(),
            model: model.to_string(),
            prompt: prompt.to_string(),
            system: system.to_string(),
            api_key,
            state,
        };

        self.pending.lock().unwrap().insert(id, item);
        id
    }

    /// Envía un WorkItem pendiente al worker cuando su dependencia se resuelve.
    fn submit_pending(&self, id: u64) {
        if let Some(item) = self.pending.lock().unwrap().remove(&id) {
            let _ = self.worker_tx.send(item);
        }
    }
}

// ── GlobalEntry ────────────────────────────────────────────────────
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub struct GlobalEntry {
    pub ns: String,
    #[serde(default)]
    pub subs: Vec<Subscript>,
    pub value: Value,
}

// ── Host trait ─────────────────────────────────────────────────────
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
    /// LOCK ^NS(subs).
    fn lock(&mut self, _ns: &str, _subs: &[Subscript], _timeout: Option<f64>) -> Result<bool, String> {
        Ok(true)
    }
    fn unlock(&mut self, _ns: &str, _subs: &[Subscript]) -> Result<(), String> {
        Ok(())
    }
    fn unlock_all(&mut self) -> Result<(), String> {
        Ok(())
    }

    // ── LLM Device ────────────────────────────────────────────
/// Lanza un LLM call asíncrono. Devuelve future ID inmediatamente.
    fn llm_fork(&self, provider: &str, model: &str, prompt: &str, system: &str) -> Result<u64, String> {
        Err("LLM device not implemented".to_string())
    }

    /// Poll: None = pendiente, Some = resultado.
    fn llm_poll(&self, _future_id: u64) -> Result<Option<String>, String> {
        Ok(None)
    }

    /// Cancela un future en curso.
    fn llm_cancel(&self, _future_id: u64) -> Result<bool, String> {
        Ok(false)
    }

    /// Crea un future que depende de otro.
    fn llm_chain(&self, _parent_id: u64, _provider: &str, _model: &str, _prompt: &str, _system: &str) -> Result<u64, String> {
        Err("LLM device not implemented".to_string())
    }
}

// ── MemoryHost ─────────────────────────────────────────────────────
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

    fn pool(&self) -> &'static LlmThreadPool {
        global_llm_pool()
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
        let prefix_key = (ns.to_string(), parent.to_vec());
        let start_key = if let Some(cur) = current {
            let mut key = parent.to_vec();
            key.push(cur.clone());
            (ns.to_string(), key)
        } else {
            prefix_key.clone()
        };
        if direction >= 0 {
            for (k, _v) in self.values.range(start_key..) {
                let (key_ns, key_subs) = k;
                if key_ns.as_str() != ns { break; }
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
        } else {
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

    // ── LLM Device implementation ─────────────────────────────
    fn llm_fork(&self, provider: &str, model: &str, prompt: &str, system: &str) -> Result<u64, String> {
        Ok(self.pool().fork(provider, model, prompt, system))
    }

    fn llm_poll(&self, future_id: u64) -> Result<Option<String>, String> {
        Ok(self.pool().poll(future_id))
    }

    fn llm_cancel(&self, future_id: u64) -> Result<bool, String> {
        Ok(self.pool().cancel(future_id))
    }

    fn llm_chain(&self, parent_id: u64, provider: &str, model: &str, prompt: &str, system: &str) -> Result<u64, String> {
        Ok(self.pool().chain(parent_id, provider, model, prompt, system))
    }
}
