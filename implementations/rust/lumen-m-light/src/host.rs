use crate::compiler::Compiler;
use crate::vm::{Execution, FiberState, VmState};
use crate::{smith::SmithRegistry, Subscript, Value};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::atomic::AtomicUsize;
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
    pending: Arc<Mutex<HashMap<u64, WorkItem>>>,
    workers: Vec<std::sync::mpsc::Sender<WorkItem>>,
    next_worker: AtomicUsize,
}

/// Process-wide Smith session registry (singleton).
fn global_smith_registry() -> &'static SmithRegistry {
    static REGISTRY: OnceLock<SmithRegistry> = OnceLock::new();
    REGISTRY.get_or_init(|| SmithRegistry::new())
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
        const NUM_WORKERS: usize = 4;
        let mut workers = Vec::with_capacity(NUM_WORKERS);
        for _ in 0..NUM_WORKERS {
            let (tx, rx) = std::sync::mpsc::channel::<WorkItem>();
            let wf = futures.clone();
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
            workers.push(tx);
        }

        Self {
            next_id: AtomicU64::new(1),
            futures,
            pending,
            workers,
            next_worker: AtomicUsize::new(0),
        }
    }

    fn do_llm_call(item: &WorkItem) -> Result<String, String> {
        let url = match item.provider.to_lowercase().as_str() {
            "openrouter" => "https://openrouter.ai/api/v1/chat/completions",
            "deepseek" => "https://api.deepseek.com/v1/chat/completions",
            "lingyi" | "zai" | "yi" | "01ai" => "https://api.lingyiwanwu.com/v1/chat/completions",
            "anthropic" => "https://api.z.ai/api/anthropic/v1/messages",
            _ => return Err(format!("unknown provider: {}", item.provider)),
        };

        #[cfg(feature = "minreq")]
        {
            let is_anthropic = item.provider.to_lowercase() == "anthropic";
            
            let body = if is_anthropic {
                serde_json::json!({
                    "model": item.model,
                    "max_tokens": 8192,
                    "system": item.system,
                    "messages": [
                        {"role": "user", "content": item.prompt}
                    ],
                })
            } else {
                serde_json::json!({
                    "model": item.model,
                    "messages": [
                        {"role": "system", "content": item.system},
                        {"role": "user", "content": item.prompt}
                    ],
                    "max_tokens": 8192,
                    "temperature": 0.7,
                })
            };

            let body_str = serde_json::to_string(&body)
                .map_err(|e| format!("JSON serialize error: {e}"))?;
            
            let mut req = minreq::post(url)
                .with_header("Content-Type", "application/json")
                .with_timeout(120)
                .with_body(body_str);
            
            if is_anthropic {
                req = req.with_header("x-api-key", &item.api_key)
                         .with_header("anthropic-version", "2023-06-01");
            } else {
                req = req.with_header("Authorization", &format!("Bearer {}", item.api_key));
            }
            
            let resp = req.send()
                .map_err(|e| format!("HTTP error: {e}"))?;

            if resp.status_code != 200 {
                let err_text = resp.as_str().unwrap_or("unknown");
                return Err(format!("API error {}: {}", resp.status_code, err_text));
            }

            let json: serde_json::Value = resp.json()
                .map_err(|e| format!("JSON parse error: {e}"))?;

            let content = if is_anthropic {
                json["content"][0]["text"]
                    .as_str()
                    .unwrap_or("")
                    .to_string()
            } else {
                let c = json["choices"][0]["message"]["content"]
                    .as_str()
                    .unwrap_or("")
                    .to_string();
                if c.is_empty() {
                    // Fallback: modelos reasoning (deepseek-v4-flash) agotan el presupuesto
                    // en reasoning_content y dejan content vacío (finish=length).
                    json["choices"][0]["message"]["reasoning_content"]
                        .as_str()
                        .unwrap_or("")
                        .to_string()
                } else {
                    c
                }
            };

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
            "lingyi" | "zai" | "yi" => std::env::var("LINGYI_API_KEY").unwrap_or_default(),
            "anthropic" => std::env::var("ANTHROPIC_AUTH_TOKEN").unwrap_or_default(),
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

        let idx = self.next_worker.fetch_add(1, Ordering::Relaxed) % self.workers.len();
        let _ = self.workers[idx].send(item);
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
            "lingyi" | "zai" | "yi" => std::env::var("LINGYI_API_KEY").unwrap_or_default(),
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
            let idx = self.next_worker.fetch_add(1, Ordering::Relaxed) % self.workers.len();
            let _ = self.workers[idx].send(item);
        }
    }
}


// ── FiberBgPool — thread pool para ejecutar M code en background ─
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum FiberBgStatus {
    Pending,
    Resolved(String),
    Rejected(String),
}

#[derive(Clone, Debug)]
struct FiberBgItem {
    id: u64,
    source: String,
    globals: Vec<GlobalEntry>,
    routines: Vec<(String, String)>,
    api_keys: HashMap<String, String>,
    status: Arc<Mutex<FiberBgStatus>>,
}

#[derive(Debug)]
pub struct FiberBgPool {
    next_id: AtomicU64,
    futures: Arc<Mutex<HashMap<u64, Arc<Mutex<FiberBgStatus>>>>>,
    worker_tx: std::sync::mpsc::Sender<FiberBgItem>,
}

/// Process-wide background fiber pool (singleton).
fn global_bg_pool() -> &'static FiberBgPool {
    static POOL: OnceLock<FiberBgPool> = OnceLock::new();
    POOL.get_or_init(|| FiberBgPool::new())
}

impl FiberBgPool {
    pub fn new() -> Self {
        let futures: Arc<Mutex<HashMap<u64, Arc<Mutex<FiberBgStatus>>>>> =
            Arc::new(Mutex::new(HashMap::new()));
        let (tx, rx) = std::sync::mpsc::channel::<FiberBgItem>();
        let worker_futures = futures.clone();

        thread::spawn(move || {
            for item in rx {
                let id = item.id;
                let result = Self::run_m_code(&item);
                let status = match result {
                    Ok(val) => FiberBgStatus::Resolved(val),
                    Err(e) => FiberBgStatus::Rejected(e),
                };
                if let Ok(mut st) = item.status.lock() {
                    *st = status;
                }
            }
        });

        Self { next_id: AtomicU64::new(1), futures, worker_tx: tx }
    }

    fn run_m_code(item: &FiberBgItem) -> Result<String, String> {
        use crate::vm::Vm;
        let program = Compiler::compile(&item.source)
            .map_err(|e| format!("Compile error: {e}"))?;
        let mut host = MemoryHost::from_entries(item.globals.clone());
        for (name, source) in &item.routines {
            host.add_routine(name, source);
        }
        // Set API keys for LLM calls
        for (provider, key) in &item.api_keys {
            std::env::set_var(&format!("{}_API_KEY", provider.to_uppercase()), key);
        }
        let mut vm = Vm::new(program, &mut host);
        let exec = loop {
            match vm.run_slice(100000) {
                crate::vm::Execution::Completed => break crate::vm::Execution::Completed,
                crate::vm::Execution::Halted => break crate::vm::Execution::Halted,
                crate::vm::Execution::Yielded => continue,
                crate::vm::Execution::Error => break crate::vm::Execution::Error,
            }
        };
        let vm_output = vm.state.output.clone();
        std::mem::drop(vm);
        match exec {
            Execution::Completed => {
                // Find ^R global as result
                if let Ok(Some(val)) = host.get("R", &[]) {
                    Ok(val.as_string())
                } else {
                    Ok(vm_output)
                }
            }
            Execution::Error => Err("M runtime error".to_string()),
            _ => Err("Fiber incomplete (gas limit)".to_string()),
        }
    }

    pub fn spawn(&self, source: &str, globals: &[GlobalEntry], routines: &[(String, String)], api_keys: &HashMap<String, String>) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let status = Arc::new(Mutex::new(FiberBgStatus::Pending));
        self.futures.lock().unwrap().insert(id, status.clone());
        let item = FiberBgItem {
            id,
            source: source.to_string(),
            globals: globals.to_vec(),
            routines: routines.to_vec(),
            api_keys: api_keys.clone(),
            status,
        };
        let _ = self.worker_tx.send(item);
        id
    }

    pub fn poll(&self, id: u64) -> Option<String> {
        let futures = self.futures.lock().unwrap();
        if let Some(s) = futures.get(&id) {
            match &*s.lock().unwrap() {
                FiberBgStatus::Pending => None,
                FiberBgStatus::Resolved(v) => Some(v.clone()),
                FiberBgStatus::Rejected(e) => Some(format!("FIBER_ERROR: {e}")),
            }
        } else {
            None  // Unknown to bg pool too
        }
    }

    pub fn cancel(&self, id: u64) -> bool {
        self.futures.lock().unwrap().remove(&id).is_some()
    }

    pub fn exists(&self, id: u64) -> bool {
        self.futures.lock().unwrap().contains_key(&id)
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

    /// Generic device call (HTTP, SQL, etc.). Sync only.
    /// For async devices (LLM), use llm_fork/llm_poll instead.
    fn device_call(&mut self, _device: &str, _action: &str, _args: &[Value]) -> Result<Value, String> {
        Err("Device not supported".to_string())
    }
    fn entries(&self) -> Result<Vec<GlobalEntry>, String> { Ok(vec![]) }
    fn routines_list(&self) -> Result<Vec<(String, String)>, String> { Ok(vec![]) }
    fn fiber_bg_spawn(&self, source: &str, globals: &[GlobalEntry], routines: &[(String, String)], _api_keys: &HashMap<String, String>) -> Result<u64, String> {
        Err("bg fiber not supported".to_string())
    }
    fn fiber_bg_poll(&self, _id: u64) -> Result<Option<String>, String> { Ok(None) }
    fn fiber_bg_exists(&self, _id: u64) -> Result<bool, String> { Ok(false) }
    fn llm_api_keys(&self) -> Result<HashMap<String, String>, String> { Ok(HashMap::new()) }

}

// ── MemoryHost ─────────────────────────────────────────────────────
pub struct MemoryHost {
    pub values: BTreeMap<(String, Vec<Subscript>), Value>,
    transactions: Vec<BTreeMap<(String, Vec<Subscript>), Value>>,
    pub routines: HashMap<String, String>,
    pub input: Vec<String>,
    locks: HashMap<(String, Vec<Subscript>), u64>,
    pub llm_api_keys: HashMap<String, String>,
    /// Conexión SQLite opcional. Cuando está presente, get/set/kill/data/order
    /// operan contra SQLite directamente en vez del BTreeMap en memoria.
    sqlite_db: Option<Arc<Mutex<rusqlite::Connection>>>,
    /// Registry global de sesiones Smith streaming
    pub smith_registry: Arc<crate::smith::SmithRegistry>,
}

impl Default for MemoryHost {
    fn default() -> Self {
        Self {
            values: BTreeMap::new(),
            transactions: Vec::new(),
            routines: HashMap::new(),
            input: Vec::new(),
            locks: HashMap::new(),
            llm_api_keys: HashMap::new(),
            sqlite_db: None,
            smith_registry: Arc::new(global_smith_registry().clone()),
        }
    }
}

impl MemoryHost {
    pub fn from_entries(entries: Vec<GlobalEntry>) -> Self {
        let mut host = Self::default();
        for entry in entries {
            host.values.insert((entry.ns, entry.subs), entry.value);
        }
        host
    }

    /// Crea un MemoryHost con backend SQLite directo.
    /// get/set/kill/data/order operan contra SQLite en vez de BTreeMap.
    pub fn from_sqlite(db_path: &str) -> Result<Self, String> {
        let conn = rusqlite::Connection::open(db_path)
            .map_err(|e| format!("SQLite open({db_path}): {e}"))?;
        conn.execute_batch(
            "PRAGMA journal_mode=WAL;
             PRAGMA busy_timeout=5000;
             CREATE TABLE IF NOT EXISTS _globals (
                 ns TEXT,
                 subkey TEXT,
                 value TEXT,
                 PRIMARY KEY (ns, subkey)
             )"
        )
            .map_err(|e| format!("SQLite pragma/schema: {e}"))?;

        // Load existing data from SQLite into in-memory BTreeMap
        let mut values: BTreeMap<(String, Vec<Subscript>), Value> = BTreeMap::new();
        if let Ok(mut stmt) = conn.prepare("SELECT ns, subkey, value FROM _globals") {
            if let Ok(rows) = stmt.query_map([], |row| {
                let ns: String = row.get(0)?;
                let subkey: Vec<u8> = row.get(1)?;
                let value: String = row.get(2)?;
                Ok((ns, subkey, value))
            }) {
                for row in rows {
                    if let Ok((ns, subkey_bytes, value_str)) = row {
                        let parts = decode_subkey(&subkey_bytes);
                        let subs: Vec<Subscript> = parts.into_iter()
                            .map(|s| if let Ok(n) = s.parse::<f64>() {
                                Subscript::Number(n)
                            } else {
                                Subscript::String(s)
                            })
                            .collect();
                        values.insert((ns, subs), Value::String(value_str));
                    }
                }
            }
        }

        Ok(Self {
            values,
            transactions: Vec::new(),
            routines: HashMap::new(),
            input: Vec::new(),
            locks: HashMap::new(),
            llm_api_keys: HashMap::new(),
            sqlite_db: Some(Arc::new(Mutex::new(conn))),
            smith_registry: Arc::new(global_smith_registry().clone()),
        })
    }

    pub fn is_sqlite(&self) -> bool {
        self.sqlite_db.is_some()
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

/// Device HTTP COMPLETO (F1 2026-08-17 — acceso Internet MVM, sin deuda técnica):
/// GET/HEAD/POST/PUT/DELETE con headers, timeout, User-Agent por defecto y límite de
/// respuesta. Contrato JSON estructurado {status, ok, body, truncated} SIEMPRE.
///   get/head:        (url, [headers_json], [timeout_s])
///   post/put/delete: (url, body, [headers_json], [timeout_s])
#[cfg(feature = "minreq")]
// ── SSRF guard para el device HTTP (2026-08-18, revisión gabinete) ──
// Bloquea hosts locales/privados ANTES de conectar: localhost, IPs literales
// privadas/loopback/link-local/unspecified, y hostnames que resuelvan (todas
// sus IPs) a rangos internos. minreq no sigue redirecciones automáticas, así
// que el guard en la URL inicial cubre el caso base; un redirect manual
// pasaría de nuevo por este guard en cada llamada.
fn is_private_ip(ip: &std::net::IpAddr) -> bool {
    match ip {
        std::net::IpAddr::V4(v4) => {
            v4.is_loopback()
                || v4.is_private()
                || v4.is_link_local()
                || v4.is_broadcast()
                || v4.is_unspecified()
        }
        std::net::IpAddr::V6(v6) => {
            v6.is_loopback()
                || v6.is_unspecified()
                || v6.is_unique_local()
                || v6.is_unicast_link_local()
        }
    }
}

fn ssrf_guard(url: &str) -> Result<(), String> {
    // Extraer host: scheme://[userinfo@]host[:port]/path?query#frag
    let after_scheme = url.split_once("://").map(|(_, r)| r).unwrap_or(url);
    let host_port = after_scheme.split(['/', '?', '#']).next().unwrap_or("");
    let host = host_port.rsplit_once('@').map(|(_, h)| h).unwrap_or(host_port);
    let host = host.split(':').next().unwrap_or(host);
    let host = host.trim_matches(['[', ']']);
    if host.is_empty() {
        return Err("HTTP: host vacío".to_string());
    }
    let lower = host.to_lowercase();
    if lower == "localhost" || lower.ends_with(".localhost") {
        return Err(format!("HTTP: SSRF bloqueado: host local {host}"));
    }
    // IP literal?
    if let Ok(ip) = host.parse::<std::net::IpAddr>() {
        if is_private_ip(&ip) {
            return Err(format!("HTTP: SSRF bloqueado: IP privada {host}"));
        }
        return Ok(());
    }
    // Hostname: resolver y comprobar TODAS las IPs (DNS -> IP interna queda bloqueado)
    let addrs = std::net::ToSocketAddrs::to_socket_addrs(&(host, 443))
        .map_err(|e| format!("HTTP: resolución DNS de {host} falló: {e}"))?;
    for addr in addrs {
        if is_private_ip(&addr.ip()) {
            return Err(format!(
                "HTTP: SSRF bloqueado: {host} resuelve a IP interna {}",
                addr.ip()
            ));
        }
    }
    Ok(())
}

fn http_full_request(action: &str, args: &[Value]) -> Result<Value, String> {
    const MAX_BODY: usize = 200 * 1024;
    let url = args.first().map(|v| v.as_string()).unwrap_or_default();
    if url.trim().is_empty() {
        return Err("HTTP: url requerida".to_string());
    }
    // SSRF guard (revisión gabinete 2026-08-18): bloquear hosts locales/privados
    // ANTES de conectar. Resuelve el hostname y comprueba TODAS las IPs
    // (protege contra DNS que resuelva a IP interna).
    if let Err(e) = ssrf_guard(&url) {
        return Err(e);
    }
    let has_body = matches!(action, "post" | "put" | "delete");
    let body = if has_body {
        args.get(1).map(|v| v.as_string()).unwrap_or_default()
    } else {
        String::new()
    };
    let headers_json = if has_body {
        args.get(2).map(|v| v.as_string()).unwrap_or_default()
    } else {
        args.get(1).map(|v| v.as_string()).unwrap_or_default()
    };
    let timeout_raw = if has_body {
        args.get(3).map(|v| v.as_string()).unwrap_or_default()
    } else {
        args.get(2).map(|v| v.as_string()).unwrap_or_default()
    };
    let timeout_s: u64 = timeout_raw.trim().parse().unwrap_or(30).clamp(1, 300);

    let mut headers: Vec<(String, String)> = Vec::new();
    if !headers_json.trim().is_empty() {
        let parsed: serde_json::Value = serde_json::from_str(&headers_json)
            .map_err(|e| format!("HTTP: headers_json inválido: {e}"))?;
        if let Some(obj) = parsed.as_object() {
            for (k, v) in obj {
                if let Some(s) = v.as_str() {
                    headers.push((k.clone(), s.to_string()));
                } else {
                    headers.push((k.clone(), v.to_string()));
                }
            }
        }
    }
    // Defaults solo si el usuario no los pasa (evita duplicados y WAF 403 por UA de bot)
    if !headers.iter().any(|(k, _)| k.eq_ignore_ascii_case("user-agent")) {
        headers.push((
            "User-Agent".to_string(),
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36".to_string(),
        ));
    }
    if has_body && !headers.iter().any(|(k, _)| k.eq_ignore_ascii_case("content-type")) {
        headers.push(("Content-Type".to_string(), "application/json".to_string()));
    }

    let mut req = match action {
        "get" => minreq::get(&url),
        "head" => minreq::head(&url),
        "post" => minreq::post(&url),
        "put" => minreq::put(&url),
        "delete" => minreq::delete(&url),
        _ => return Err(format!("HTTP: método no soportado: {action}")),
    }
    .with_timeout(timeout_s);
    for (k, v) in &headers {
        req = req.with_header(k.as_str(), v.as_str());
    }
    if has_body {
        req = req.with_body(body);
    }

    let resp = req.send().map_err(|e| format!("HTTP {action} error: {e}"))?;
    let status = resp.status_code;
    let bytes = resp.as_bytes();
    let truncated = bytes.len() > MAX_BODY;
    let body_out = String::from_utf8_lossy(&bytes[..bytes.len().min(MAX_BODY)]).to_string();
    let out = serde_json::json!({
        "status": status,
        "ok": status >= 200 && status < 300,
        "body": body_out,
        "truncated": truncated,
    });
    Ok(Value::String(out.to_string()))
}

impl Host for MemoryHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        // Read from in-memory BTreeMap
        Ok(self.values.get(&(ns.to_string(), subs.to_vec())).cloned())
    }

    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        // Always update in-memory BTreeMap first
        self.values.insert((ns.to_string(), subs.to_vec()), value.clone());
        // Persist to SQLite if available
        if let Some(ref db) = self.sqlite_db {
            let subkey = encode_subkey(subs);
            let val_str = value.as_string();
            let conn = db.lock().map_err(|e| format!("set lock: {e}"))?;
            conn.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?1, ?2, ?3)",
                rusqlite::params![ns, subkey, val_str],
            )
            .map_err(|e| format!("set: {e}"))?;
        }
        Ok(())
    }

    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        // Always update in-memory BTreeMap
        let before = self.values.len();
        self.values.retain(|(candidate_ns, candidate), _| {
            candidate_ns != ns || !is_prefix(subs, candidate)
        });
        let count = (before - self.values.len()) as u64;
        // Persist deletion to SQLite if available
        if let Some(ref db) = self.sqlite_db {
            let subkey = encode_subkey(subs);
            let conn = db.lock().map_err(|e| format!("kill lock: {e}"))?;
            if subs.is_empty() {
                conn.execute("DELETE FROM _globals WHERE ns=?1", rusqlite::params![ns])
                    .map_err(|e| format!("kill ns: {e}"))?;
            } else {
                let _ = conn
                    .execute("DELETE FROM _globals WHERE ns=?1 AND subkey=?2",
                        rusqlite::params![ns, subkey]);
                let _ = conn
                    .execute("DELETE FROM _globals WHERE ns=?1 AND subkey>?2 AND subkey LIKE ?3",
                        rusqlite::params![ns, subkey, {
                            let mut p = subkey.clone();
                            p.push(b'%');
                            p
                        }]);
            }
        }
        Ok(count)
    }

    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        let own = self.values.contains_key(&(ns.to_string(), subs.to_vec()));
        let child = self.values.keys().any(|(candidate_ns, candidate)| {
            candidate_ns == ns && candidate.len() > subs.len() && is_prefix(subs, candidate)
        });
        Ok(match (own, child) {
            (true, true) => 11, (true, false) => 1,
            (false, true) => 10, (false, false) => 0,
        })
    }

    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        // Collect all subscripts for this ns that are descendants of parent
        let mut decoded: Vec<Vec<Subscript>> = self.values.keys()
            .filter(|(candidate_ns, subs)| {
                candidate_ns == ns && is_prefix(parent, subs) && subs.len() > parent.len()
            })
            .map(|(_, subs)| subs.clone())
            .collect();

        // Sort using canonical MUMPS ordering (numbers before strings, ASCII byte compare)
        decoded.sort_by(|a, b| compare_subscripts(a, b));

        let current_vec: Option<Vec<Subscript>> = current.map(|c| {
            let mut v = parent.to_vec();
            v.push(c.clone());
            v
        });

        if direction >= 0 {
            for subs in decoded.iter() {
                let candidate = &subs[parent.len()];
                if let Some(ref cur) = current {
                    if candidate.canonical_cmp(cur) != std::cmp::Ordering::Greater {
                        continue;
                    }
                }
                return Ok(Some(candidate.clone()));
            }
        } else {
            for subs in decoded.iter().rev() {
                let candidate = &subs[parent.len()];
                if let Some(ref cur) = current {
                        if candidate.canonical_cmp(cur) != std::cmp::Ordering::Less {
                            continue;
                        }
                    }
                    return Ok(Some(candidate.clone()));
                }
            }
            return Ok(None);
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
        // First check LLM futures — None = pending, Some("FUTURE_NOT_FOUND") = unknown
        let r = self.pool().poll(future_id);
        if r != Some("FUTURE_NOT_FOUND".to_string()) {
            return Ok(r);
        }
        // Not an LLM future, check bg fibers
        Ok(global_bg_pool().poll(future_id))
    }

    fn llm_cancel(&self, future_id: u64) -> Result<bool, String> {
        Ok(self.pool().cancel(future_id))
    }

    fn llm_chain(&self, parent_id: u64, provider: &str, model: &str, prompt: &str, system: &str) -> Result<u64, String> {
        Ok(self.pool().chain(parent_id, provider, model, prompt, system))
    }

    // ── Generic device call (HTTP, future devices) ────────────
    fn entries(&self) -> Result<Vec<GlobalEntry>, String> {
        if let Some(ref db) = self.sqlite_db {
            let conn = db.lock().map_err(|e| format!("entries lock: {e}"))?;
            let mut stmt = conn
                .prepare("SELECT ns, subkey, value FROM _globals ORDER BY ns, subkey")
                .map_err(|e| format!("entries prepare: {e}"))?;
            let rows = stmt
                .query_map([], |row| {
                    let ns: String = row.get(0)?;
                    let subkey: Vec<u8> = row.get(1)?;
                    let value: String = row.get(2)?;
                    Ok((ns, subkey, value))
                })
                .map_err(|e| format!("entries query: {e}"))?;
            let mut entries = Vec::new();
            for row in rows {
                let (ns, subkey, value) = row.map_err(|e| format!("entries row: {e}"))?;
                let subs = decode_subkey(&subkey);
                let subs_enum: Vec<Subscript> = subs.into_iter()
                    .map(|s| if let Ok(n) = s.parse::<f64>() { Subscript::Number(n) } else { Subscript::String(s) })
                    .collect();
                let val = if let Ok(n) = value.trim().parse::<f64>() { Value::Number(n) } else { Value::String(value) };
                entries.push(GlobalEntry { ns, subs: subs_enum, value: val });
            }
            Ok(entries)
        } else {
            Ok(MemoryHost::entries(self))
        }
    }

    fn routines_list(&self) -> Result<Vec<(String, String)>, String> {
        Ok(self.routines.iter().map(|(k, v)| (k.clone(), v.clone())).collect())
    }

    fn fiber_bg_spawn(&self, source: &str, globals: &[GlobalEntry], routines: &[(String, String)], _api_keys: &HashMap<String, String>) -> Result<u64, String> {
        Ok(global_bg_pool().spawn(source, globals, routines, &self.llm_api_keys))
    }

    fn fiber_bg_poll(&self, id: u64) -> Result<Option<String>, String> {
        Ok(global_bg_pool().poll(id))
    }

    fn fiber_bg_exists(&self, id: u64) -> Result<bool, String> {
        Ok(global_bg_pool().exists(id))
    }

    fn llm_api_keys(&self) -> Result<HashMap<String, String>, String> {
        Ok(self.llm_api_keys.clone())
    }

    fn device_call(&mut self, device: &str, action: &str, args: &[Value]) -> Result<Value, String> {
        match device {
            #[cfg(feature = "minreq")]
            "http" => {
                // Device HTTP COMPLETO (2026-08-17 — F1 acceso Internet MVM, sin deuda técnica):
                //   $DEVICE("http:get", url, [headers_json], [timeout_s])
                //   $DEVICE("http:post", url, body, [headers_json], [timeout_s])
                //   $DEVICE("http:put"|"http:delete"|"http:head", ...)   (igual que post/get)
                // Devuelve SIEMPRE JSON: {"status":N,"ok":bool,"body":"..."} (body truncado a 200KB).
                // Compat: el antiguo "get"/"post" plano se sustituye por este contrato estructurado
                // (ninguna rutina en producción usaba el plano — verificado 17-08).
                match action {
                    "get" | "head" | "post" | "put" | "delete" => {
                        http_full_request(action, &args)
                    }
                    _ => Err(format!("Unknown HTTP action: {action}")),
                }
            }
            "ddp" => {
                match action {
                    "get" => {
                        let space = args.first().map(|v| v.as_string()).unwrap_or_default();
                        let global = args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        let key = args.get(2).map(|v| v.as_string()).unwrap_or_default();
                        
                        // Lookup host/port from globals
                        let sub_host = Subscript::String(format!("{}", "host"));
                        let sub_port = Subscript::String(format!("{}", "port"));
                        let key_host = [
                            Subscript::String("SPACE".to_string()),
                            Subscript::String(space.clone()),
                            sub_host,
                        ];
                        let key_port = [
                            Subscript::String("SPACE".to_string()),
                            Subscript::String(space.clone()),
                            sub_port,
                        ];
                        let host = match self.get("", &key_host) {
                            Ok(Some(Value::String(s))) => s.clone(),
                            _ => "127.0.0.1".to_string(),
                        };
                        let port = match self.get("", &key_port) {
                            Ok(Some(Value::String(s))) => s.clone(),
                            Ok(Some(Value::Number(n))) => n.to_string(),
                            _ => "9102".to_string(),
                        };
                        
                        let addr = format!("{}:{}", host, port);
                        match std::net::TcpStream::connect(&addr) {
                            Ok(mut stream) => {
                                use std::io::{Read, Write};
                                let req = serde_json::json!({
                                    "op": "GET",
                                    "global": global,
                                    "subs": [key]
                                }).to_string();
                                let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(5)));
                                let _ = stream.write_all(req.as_bytes());
                                let mut buf = Vec::new();
                                let _ = stream.read_to_end(&mut buf);
                                let txt = String::from_utf8_lossy(&buf).to_string();
                                Ok(Value::String(txt))
                            }
                            Err(e) => Err(format!("DDP TCP error: {e}")),
                        }
                    }
                    _ => Err(format!("Unknown DDP action: {action}")),
                }
            }
            #[cfg(feature = "minreq")]
            "agent" => {
                match action {
                    "call" | "notify" => {
                        let peer = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let method = args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        let params = args.get(2).map(|v| v.as_string()).unwrap_or_default();
                        
                        // Lookup peer in Space Registry (^SYS("SPACE",peer,key))
                        let transport = match self.get("SYS", &[Subscript::String("SPACE".into()), Subscript::String(peer.clone()), Subscript::String("transport".into())]) {
                            Ok(Some(Value::String(s))) => s.clone(),
                            _ => "edge".to_string(),
                        };
                        let url = match self.get("SYS", &[Subscript::String("SPACE".into()), Subscript::String(peer.clone()), Subscript::String("url".into())]) {
                            Ok(Some(Value::String(s))) => s.clone(),
                            _ => String::new(),
                        };
                        let hmac_key = match self.get("SYS", &[Subscript::String("SPACE".into()), Subscript::String(peer.clone()), Subscript::String("hmac_key".into())]) {
                            Ok(Some(Value::String(s))) => s.clone(),
                            _ => String::new(),
                        };
                        
                        if transport == "edge" && !url.is_empty() {
                            // Build JSON-RPC 2.0 request
                            let body = serde_json::json!({
                                "jsonrpc": "2.0",
                                "method": method,
                                "params": params,
                                "id": 1,
                            }).to_string();
                            
                            // Add HMAC auth if key is available
                            let ts_str;
                            let sig_str;
                            let (headers, body_for_req) = if !hmac_key.is_empty() {
                                use std::time::{SystemTime, UNIX_EPOCH};
                                let ts = SystemTime::now()
                                    .duration_since(UNIX_EPOCH)
                                    .unwrap_or_default()
                                    .as_secs()
                                    .to_string();
                                let sig = hmac_sha256(&hmac_key, &format!("{ts}{body}{hmac_key}"));
                                ts_str = ts;
                                sig_str = sig;
                                (vec![
                                    ("X-DDP-Timestamp", ts_str.as_str()),
                                    ("X-DDP-HMAC", sig_str.as_str()),
                                ], body.clone())
                            } else {
                                (vec![], body.clone())
                            };
                            // RAW TCP HTTP POST (reemplaza minreq)
                            use std::io::{Read, Write};
                            let (edge_host, edge_port, edge_path) = if let Some(rest) = url.strip_prefix("http://") {
                                let (h, rest2) = rest.split_once('/').unwrap_or((rest, ""));
                                let p = if let Some(c) = h.rfind(':') { (&h[..c], h[c+1..].to_string()) } else { (h, "80".to_string()) };
                                (p.0.to_string(), p.1, format!("/{rest2}"))
                            } else {
                                // HTTPS or other: keep using minreq for TLS
                                let resp = minreq::post(&url)
                                    .with_header("Content-Type", "application/json");
                                let resp = headers.iter().fold(resp, |r, (k,v)| r.with_header(*k, *v));
                                let resp = resp.with_body(body_for_req).send()
                                    .map_err(|e| format!("AGENT {peer} POST error: {e}"))?;
                                let text = resp.as_str().unwrap_or("").to_string();
                                return if action == "notify" { Ok(Value::Bool(true)) } else { Ok(Value::String(text)) };
                            };
                            let edge_addr = format!("{edge_host}:{edge_port}");
                            let http_body = body_for_req;
                            let http_request = format!(
                                "POST {edge_path} HTTP/1.1\r\nHost: {edge_host}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n{}Connection: close\r\n\r\n{}",
                                http_body.len(),
                                headers.iter().map(|(k,v)| format!("{k}: {v}\r\n")).collect::<String>(),
                                http_body
                            );
                            match std::net::TcpStream::connect(&edge_addr) {
                                Ok(mut stream) => {
                                    let _ = stream.set_nodelay(true);
                                    let _ = stream.set_write_timeout(Some(std::time::Duration::from_secs(10)));
                                    let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(30)));
                                    if let Err(e) = stream.write_all(http_request.as_bytes()) {
                                        Err(format!("AGENT {peer} write error: {e}"))
                                    } else {
                                        let _ = stream.flush();
                                        let mut edge_buf = [0u8; 65536];
                                        match stream.read(&mut edge_buf) {
                                            Ok(n) => {
                                                let raw = String::from_utf8_lossy(&edge_buf[..n]).to_string();
                                                // Extract body after \r\n\r\n
                                                let text = if let Some(pos) = raw.find("\r\n\r\n") {
                                                    raw[pos+4..].to_string()
                                                } else { raw };
                                                if action == "notify" {
                                                    Ok(Value::Bool(true))
                                                } else {
                                                    Ok(Value::String(text))
                                                }
                                            }
                                            Err(e) => Err(format!("AGENT {peer} read error: {e}"))
                                        }
                                    }
                                }
                                Err(e) => Err(format!("AGENT {peer} connect error: {e}"))
                            }
                        } else if transport == "local" {
                            // Local SHM transport: raw TCP (like DDP device)
                            use std::io::{Read, Write};
                            let (host_str, port_str) = if let Some(rest) = url.strip_prefix("tcp://") {
                                if let Some(colon) = rest.rfind(':') {
                                    let h = &rest[..colon];
                                    let p = &rest[colon+1..];
                                    (h.to_string(), p.to_string())
                                } else {
                                    (rest.to_string(), "9090".to_string())
                                }
                            } else if let Some(rest) = url.strip_prefix("http://") {
                                if let Some(colon) = rest.rfind(':') {
                                    let h = &rest[..colon];
                                    let p = rest[colon+1..].split('/').next().unwrap_or("9090");
                                    (h.to_string(), p.to_string())
                                } else {
                                    (rest.split('/').next().unwrap_or("localhost").to_string(), "9090".to_string())
                                }
                            } else {
                                ("localhost".to_string(), "9090".to_string())
                            };
                            let addr = format!("{host_str}:{port_str}");
                            let body = serde_json::json!({
                                "jsonrpc": "2.0",
                                "method": method,
                                "params": params,
                                "id": 1,
                            }).to_string();
                            match std::net::TcpStream::connect(&addr) {
                                Ok(mut stream) => {
                                    let _ = stream.set_nodelay(true);
                                    let _ = stream.set_write_timeout(Some(std::time::Duration::from_secs(5)));
                                    let _ = stream.set_read_timeout(Some(std::time::Duration::from_secs(15)));
                                    if let Err(e) = stream.write_all(body.as_bytes()) {
                                        Err(format!("AGENT local {peer} write error: {e}"))
                                    } else {
                                        let _ = stream.flush();
                                        let mut buf = [0u8; 65536];
                                        match stream.read(&mut buf) {
                                            Ok(n) => {
                                                let text = String::from_utf8_lossy(&buf[..n]).to_string();
                                                if action == "notify" {
                                                    Ok(Value::Bool(true))
                                                } else {
                                                    Ok(Value::String(text))
                                                }
                                            }
                                            Err(e) => Err(format!("AGENT local {peer} read error: {e}"))
                                        }
                                    }
                                }
                                Err(e) => Err(format!("AGENT local {peer} connect error: {e}"))
                            }
                        } else {
                            Err(format!("AGENT peer '{peer}' not found in Space Registry"))
                        }
                    }
                    "peers" => {
                        // List peers from Space Registry (^SYS("SPACE"))
                        let mut peers = Vec::new();
                        let mut cursor: Option<Subscript> = None;
                        loop {
                            match self.order("SYS", &[Subscript::String("SPACE".into())], cursor.as_ref(), 1) {
                                Ok(Some(sub)) => {
                                    if let Subscript::String(name) = &sub {
                                        let t_key = [
                                            Subscript::String("SYS".to_string()),
                                            Subscript::String("SPACE".to_string()),
                                            Subscript::String(name.clone()),
                                            Subscript::String("transport".to_string()),
                                        ];
                                        let transport = match self.get("SYS", &[Subscript::String("SPACE".into()), Subscript::String(name.clone()), Subscript::String("transport".into())]) {
                                            Ok(Some(Value::String(s))) => s.clone(),
                                            _ => "unknown".to_string(),
                                        };
                                        peers.push(format!("{name}\t{transport}"));
                                    }
                                    cursor = Some(sub);
                                }
                                Ok(None) => break,
                                Err(_) => break,
                            }
                        }
                        Ok(Value::String(peers.join("\n")))
                    }
                    _ => Err(format!("Unknown LUMEN action: {action}")),
                }
            }
            #[cfg(not(feature = "minreq"))]
            "agent" => {
                Err("LUMEN device requires minreq feature".to_string())
            }
            "smith" => {
                match action {
                    "orchestrate" => {
                        // ── Modo legacy (bloqueante) ────────────────────────
                        let msg = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let domains_str = args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        let domains: Vec<&str> = domains_str.split(',').map(|s| s.trim()).filter(|s| !s.is_empty()).collect();
                        if domains.is_empty() {
                            return Err("Smith: al menos 1 dominio requerido".to_string());
                        }
                        let mut results: Vec<String> = Vec::new();
                        let mut fids: Vec<(String, u64)> = Vec::new();
                        for domain in &domains {
                            let id_key = [
                                Subscript::String("PERSONALITY".to_string()),
                                Subscript::String(domain.to_string()),
                                Subscript::String("identity".to_string()),
                            ];
                            let identity = match self.get("", &id_key) {
                                Ok(Some(Value::String(s))) => s.clone(),
                                _ => format!("Eres un asesor experto en {domain}. Responde con claridad."),
                            };
                            let prov_key = [
                                Subscript::String("PERSONALITY".to_string()),
                                Subscript::String(domain.to_string()),
                                Subscript::String("provider".to_string()),
                            ];
                            let provider = match self.get("", &prov_key) {
                                Ok(Some(Value::String(s))) if !s.is_empty() && s != "symbolic" => s.clone(),
                                _ => "deepseek".to_string(),
                            };
                            let model_key = [
                                Subscript::String("PERSONALITY".to_string()),
                                Subscript::String(domain.to_string()),
                                Subscript::String("model".to_string()),
                            ];
                            let model = match self.get("", &model_key) {
                                Ok(Some(Value::String(s))) if !s.is_empty() && s != "0" => s.clone(),
                                _ => "deepseek-v4-flash".to_string(),
                            };
                            match self.llm_fork(&provider, &model, &msg, &identity) {
                                Ok(fid) => fids.push((domain.to_string(), fid)),
                                Err(e) => results.push(format!("[{domain}]: ERROR: {e}")),
                            }
                        }
                        let mut pending: Vec<(String, u64)> = fids;
                        let mut attempts: u32 = 0;
                        while !pending.is_empty() && attempts < 600 {
                            attempts += 1;
                            let mut still: Vec<(String, u64)> = Vec::new();
                            for (domain, fid) in pending {
                                match self.llm_poll(fid) {
                                    Ok(Some(r)) => results.push(format!("[{domain}]: {r}")),
                                    Ok(None) => still.push((domain, fid)),
                                    Err(e) => results.push(format!("[{domain}]: ERROR: {e}")),
                                }
                            }
                            pending = still;
                            if !pending.is_empty() {
                                std::thread::sleep(std::time::Duration::from_millis(100));
                            }
                        }
                        for (domain, _) in pending {
                            results.push(format!("[{domain}]: TIMEOUT"));
                        }
                        // Síntesis: unificar resultados con LLM final
                        if results.len() <= 1 {
                            Ok(Value::String(
                                results.into_iter().next().unwrap_or_default()
                            ))
                        } else {
                            // Shorten each result for synthesis prompt (first 300 CHARS, not bytes)
                            use std::iter::FromIterator;
                            let short_results: Vec<String> = results.iter().map(|r| {
                                let chars: Vec<char> = r.chars().collect();
                                if chars.len() > 310 {
                                    format!("{}...", String::from_iter(&chars[..300]))
                                } else {
                                    r.clone()
                                }
                            }).collect();
                            let joined = short_results.join("\n---\n");
                            let total = results.len();
                            let syn_msg = format!(
                                "Synthesize {} expert perspectives into ONE unified, coherent response. \
                                 Find common ground and integrate viewpoints. Respond naturally:\n\n{}",
                                total, joined
                            );
                            let syn_sys = "You synthesize multiple expert perspectives into one coherent answer. \
                                Keep it concise and natural. Respond in the same language as the question.";
                            match self.llm_fork("deepseek", "deepseek-v4-flash", &syn_msg, syn_sys) {
                                Ok(syn_fid) => {
                                    let mut attempts = 0u32;
                                    let syn_result = loop {
                                        attempts += 1;
                                        match self.llm_poll(syn_fid) {
                                            Ok(Some(r)) => break r,
                                            Ok(None) if attempts < 150 => {
                                                std::thread::sleep(std::time::Duration::from_millis(100));
                                            }
                                            _ => break joined,
                                        }
                                    };
                                    Ok(Value::String(syn_result))
                                }
                                Err(_) => Ok(Value::String(joined)),
                            }
                        }
                    }
                    "stream" => {
                        // Crear nueva sesión Smith con streaming
                        let domains_str = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let msg = args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        let domains: Vec<String> = domains_str.split(',')
                            .map(|s| s.trim().to_string())
                            .filter(|s| !s.is_empty())
                            .collect();
                        if domains.is_empty() {
                            return Err("Smith stream: al menos 1 dominio requerido".to_string());
                        }
                        let registry = global_smith_registry();
                        let session_id = registry.create_session(&domains);
                        // Iniciar forks para cada dominio en threads separados
                        for domain in &domains {
                            let id_key = [
                                Subscript::String("PERSONALITY".to_string()),
                                Subscript::String(domain.clone()),
                                Subscript::String("identity".to_string()),
                            ];
                            let identity = match self.get("", &id_key) {
                                Ok(Some(Value::String(s))) => s.clone(),
                                _ => format!("Eres un asesor experto en {domain}. Responde con claridad."),
                            };
                            let prov_key = [
                                Subscript::String("PERSONALITY".to_string()),
                                Subscript::String(domain.clone()),
                                Subscript::String("provider".to_string()),
                            ];
                            let provider = match self.get("", &prov_key) {
                                Ok(Some(Value::String(s))) if !s.is_empty() && s != "symbolic" => s.clone(),
                                _ => "deepseek".to_string(),
                            };
                            let model_key = [
                                Subscript::String("PERSONALITY".to_string()),
                                Subscript::String(domain.clone()),
                                Subscript::String("model".to_string()),
                            ];
                            let model = match self.get("", &model_key) {
                                Ok(Some(Value::String(s))) if !s.is_empty() && s != "0" => s.clone(),
                                _ => "deepseek-v4-flash".to_string(),
                            };
                            // Marcar como Pending en el coordinator
                            global_smith_registry().start_fork(session_id, domain);
                            // Fork en thread separado
                            let d = domain.clone();
                            let p = provider.clone();
                            let m = model.clone();
                            let ident = identity.clone();
                            let q = msg.to_string();
                            std::thread::spawn(move || {
                                // Emitir thinking pulse inicial
                                global_smith_registry().fork_thinking(session_id, &d, &format!("Analizando como {}...", &d));
                                match crate::host::smith_llm_call(&p, &m, &q, &ident) {
                                    Ok(response) => {
                                        global_smith_registry().fork_complete(session_id, &d, &response);
                                    }
                                    Err(e) => {
                                        global_smith_registry().fork_error(session_id, &d, &e);
                                    }
                                }
                            });
                        }
                        Ok(Value::String(format!("{}", session_id)))
                    }
                    "poll" => {
                        // Obtener eventos de una sesión
                        let sid_str = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let session_id: u64 = sid_str.parse().map_err(|_| "Smith poll: session_id inválido".to_string())?;
                        // Check timeouts first
                        global_smith_registry().check_session_timeouts(session_id);
                        match global_smith_registry().poll_session(session_id) {
                            Some(events) => {
                                let json_lines: Vec<String> = events.iter().map(|e| e.to_ndjson()).collect();
                                Ok(Value::String(json_lines.join("\n")))
                            }
                            None => Err(format!("Smith: sesión {} no encontrada", session_id)),
                        }
                    }
                    "collect" => {
                        // Obtener resultados finales y síntesis
                        let sid_str = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let session_id: u64 = sid_str.parse().map_err(|_| "Smith collect: session_id inválido".to_string())?;
                        let done = global_smith_registry().session_done(session_id).unwrap_or(true);
                        if !done {
                            return Err("Smith collect: forks aún en progreso".to_string());
                        }
                        let results = global_smith_registry().session_results(session_id).unwrap_or_default();
                        let results_str: Vec<String> = results.iter()
                            .filter_map(|r| r.response.as_ref().map(|resp| format!("[{}]: {}", r.domain, resp)))
                            .collect();
                        if results_str.is_empty() {
                            global_smith_registry().remove_session(session_id);
                            return Ok(Value::String("(sin resultados)".to_string()));
                        }
                        // Síntesis
                        use std::iter::FromIterator;
                        let short_results: Vec<String> = results_str.iter().map(|r| {
                            let chars: Vec<char> = r.chars().collect();
                            if chars.len() > 310 {
                                format!("{}...", String::from_iter(&chars[..300]))
                            } else {
                                r.clone()
                            }
                        }).collect();
                        let joined = short_results.join("\n---\n");
                        let total = results_str.len();
                        let syn_msg = format!(
                            "Synthesize {} expert perspectives into ONE unified, coherent response. \
                             Find common ground and integrate viewpoints. Respond naturally:\n\n{}",
                            total, joined
                        );
                        let syn_sys = "You synthesize multiple expert perspectives into one coherent answer. \
                            Keep it concise and natural.";
                        let synthesis = match self.llm_fork("deepseek", "deepseek-v4-flash", &syn_msg, syn_sys) {
                            Ok(syn_fid) => {
                                let mut attempts = 0u32;
                                loop {
                                    attempts += 1;
                                    match self.llm_poll(syn_fid) {
                                        Ok(Some(r)) => break r,
                                        Ok(None) if attempts < 150 => {
                                            std::thread::sleep(std::time::Duration::from_millis(100));
                                        }
                                        _ => break joined,
                                    }
                                }
                            }
                            Err(_) => joined.clone(),
                        };
                        global_smith_registry().set_synthesis(session_id, &synthesis);
                        global_smith_registry().remove_session(session_id);
                        Ok(Value::String(synthesis))
                    }
                    "status" => {
                        let sid_str = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                        let session_id: u64 = sid_str.parse().unwrap_or(0);
                        if session_id == 0 {
                            Err("Smith status: session_id requerido".to_string())
                        } else {
                            match global_smith_registry().session_status(session_id) {
                                Some(status) => {
                                    let lines: Vec<String> = status.iter()
                                        .map(|(d, s, t)| format!("{}:{}:{}", d, s, if *t { "1" } else { "0" }))
                                        .collect();
                                    Ok(Value::String(lines.join("\n")))
                                }
                                None => Err(format!("Smith: sesión {} no encontrada", session_id)),
                            }
                        }
                    }
                    _ => Err(format!("Unknown Smith action: {action}")),
                }
            }
            _ => Err(format!("Device '{device}:{action}' not supported")),
        }
    }
}

// ── Smith fork helper (standalone LLM call para smith:stream threads) ──

/// Función standalone para hacer una LLM call desde un thread Smith.
/// Usa las env vars OPENROUTER_API_KEY / DEEPSEEK_API_KEY
pub fn smith_llm_call(provider: &str, model: &str, prompt: &str, system: &str) -> Result<String, String> {
    let url = match provider.to_lowercase().as_str() {
        "openrouter" => "https://openrouter.ai/api/v1/chat/completions",
        "deepseek" => "https://api.deepseek.com/v1/chat/completions",
        "lingyi" | "zai" | "yi" | "01ai" => "https://api.lingyiwanwu.com/v1/chat/completions",
        "anthropic" => "https://api.z.ai/api/anthropic/v1/messages",
        _ => return Err(format!("unknown provider: {provider}")),
    };
    let key_env = match provider.to_lowercase().as_str() {
        "openrouter" => "OPENROUTER_API_KEY",
        "deepseek" => "DEEPSEEK_API_KEY",
        "lingyi" | "zai" | "yi" | "01ai" => "LINGYI_API_KEY",
        "anthropic" => "ANTHROPIC_AUTH_TOKEN",
        _ => return Err(format!("unknown provider: {provider}")),
    };
    let api_key = std::env::var(key_env).unwrap_or_default();
    if api_key.is_empty() {
        return Err(format!("{key_env} no configurada"));
    }
    #[cfg(feature = "minreq")]
    {
        let is_anthropic = provider.to_lowercase() == "anthropic";
        
        let body = if is_anthropic {
            serde_json::json!({
                "model": model,
                "max_tokens": 4096,
                "system": system,
                "messages": [
                    {"role": "user", "content": prompt}
                ],
            })
        } else {
            serde_json::json!({
                "model": model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": prompt}
                ],
                "max_tokens": 4096,
                "temperature": 0.7,
            })
        };
        let body_str = serde_json::to_string(&body)
            .map_err(|e| format!("JSON serialize: {e}"))?;
        
        let mut req = minreq::post(url)
            .with_header("Content-Type", "application/json")
            .with_timeout(120)
            .with_body(body_str);
        
        if is_anthropic {
            req = req.with_header("x-api-key", &api_key)
                     .with_header("anthropic-version", "2023-06-01");
        } else {
            req = req.with_header("Authorization", &format!("Bearer {api_key}"));
        }
        let resp = req.send()
            .map_err(|e| format!("HTTP error: {e}"))?;
        if resp.status_code != 200 {
            let err_text = resp.as_str().unwrap_or("unknown");
            return Err(format!("API error {}: {}", resp.status_code, err_text));
        }
        let json: serde_json::Value = resp.json()
            .map_err(|e| format!("JSON parse: {e}"))?;
        let content = if is_anthropic {
            json["content"][0]["text"]
                .as_str()
                .unwrap_or("")
                .to_string()
        } else {
            let c = json["choices"][0]["message"]["content"]
                .as_str()
                .unwrap_or("")
                .to_string();
            if c.is_empty() {
                // Fallback: modelos reasoning (deepseek-v4-flash) agotan el presupuesto
                // en reasoning_content y dejan content vacío (finish=length).
                json["choices"][0]["message"]["reasoning_content"]
                    .as_str()
                    .unwrap_or("")
                    .to_string()
            } else {
                c
            }
        };
        Ok(content)
    }
    #[cfg(not(feature = "minreq"))]
    {
        Err("smith_llm_call requires minreq feature".to_string())
    }
}

// ── HMAC helper ────────────────────────────────────────────────
fn hmac_sha256(key: &str, data: &str) -> String {
    use hmac::{Hmac, Mac};
    use sha2::Sha256;
    type HmacSha256 = Hmac<Sha256>;
    let mut mac = HmacSha256::new_from_slice(key.as_bytes())
        .expect("HMAC key");
    mac.update(data.as_bytes());
    hex::encode(mac.finalize().into_bytes())
}

// ── SQLite helper functions ────────────────────────────────────

/// Codificar un Subscript a formato MUMPS binario.
fn encode_one_sub(sub: &Subscript) -> Vec<u8> {
    let mut out = Vec::new();
    match sub {
        Subscript::Number(v) => {
            out.push(0x01);
            out.extend_from_slice(v.to_string().as_bytes());
            out.push(0xFF);
        }
        Subscript::String(s) => {
            out.push(0x02);
            out.extend_from_slice(s.as_bytes());
            out.push(0xFF);
        }
    }
    out
}

/// Codificar vector de subscripts a formato MUMPS binario.
fn encode_subkey(subs: &[Subscript]) -> Vec<u8> {
    let mut out = Vec::new();
    for sub in subs {
        out.extend(encode_one_sub(sub));
    }
    out
}

/// Decodificar subkey binaria a vector de strings MUMPS.
fn decode_subkey(subkey: &[u8]) -> Vec<String> {
    let mut result = Vec::new();
    let mut i = 0;
    while i + 1 < subkey.len() {
        let _typ = subkey[i];
        i += 1;
        let end = subkey[i..].iter().position(|&b| b == 0xFF)
            .map(|p| i + p)
            .unwrap_or(subkey.len());
        let raw = &subkey[i..end];
        result.push(String::from_utf8_lossy(raw).to_string());
        i = end + 1;
    }
    result
}

/// Extraer el primer subscript de una subkey binaria.
fn decode_first_sub(subkey: &[u8]) -> Option<Subscript> {
    let parts = decode_subkey(subkey);
    parts.into_iter().next().map(|s| {
        if let Ok(n) = s.parse::<f64>() {
            Subscript::Number(n)
        } else {
            Subscript::String(s)
        }
    })
}

/// Extraer el subscript en un nivel especifico de una subkey.
fn extract_sub_at_level(subkey: &[u8], level: usize) -> Option<Subscript> {
    let parts = decode_subkey(subkey);
    parts.get(level).map(|s| {
        if let Ok(n) = s.parse::<f64>() {
            Subscript::Number(n)
        } else {
            Subscript::String(s.clone())
        }
    })
}

/// Extension trait para convertir QueryReturnedNoRows en None.
trait OptionalExt<T> {
    fn optional(self) -> Result<Option<T>, rusqlite::Error>;
}

impl<T> OptionalExt<T> for Result<T, rusqlite::Error> {
    fn optional(self) -> Result<Option<T>, rusqlite::Error> {
        match self {
            Ok(v) => Ok(Some(v)),
            Err(rusqlite::Error::QueryReturnedNoRows) => Ok(None),
            Err(e) => Err(e),
        }
    }
}

impl std::fmt::Debug for MemoryHost {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MemoryHost")
            .field("values", &self.values.len())
            .field("has_sqlite", &self.sqlite_db.is_some())
            .field("routines", &self.routines.len())
            .finish()
    }
}

impl Clone for MemoryHost {
    fn clone(&self) -> Self {
        Self {
            values: self.values.clone(),
            transactions: self.transactions.clone(),
            routines: self.routines.clone(),
            input: self.input.clone(),
            locks: self.locks.clone(),
            llm_api_keys: self.llm_api_keys.clone(),
            sqlite_db: None, // SQLite connections can't be cloned
            smith_registry: self.smith_registry.clone(),
        }
    }
}
