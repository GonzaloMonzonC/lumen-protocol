use crate::compiler::Compiler;
use crate::vm::{Execution, FiberState, VmState};
use crate::{smith::SmithRegistry, Subscript, Value};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::collections::HashMap;
use crate::atomic64::Atomic64 as AtomicU64;
use std::sync::atomic::Ordering;
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

// ── LLM device en WASM: sin threads — el JS del host inyecta los resultados ──
// (fix 2026-08-27: $DEVICE("llm:call") panica en wasm32 porque pool() usa threads)
// NOTA: los statics deben ser DE MÓDULO (no dentro de cada fn — en Rust cada fn
// tiene su propio static; fork escribía en uno y pending leía de otro).
#[cfg(feature = "wasm")]
static WASM_LLM_NEXT: OnceLock<std::sync::atomic::AtomicU64> = OnceLock::new();
#[cfg(feature = "wasm")]
static WASM_LLM_PENDING: OnceLock<Mutex<Vec<(u64, String, String, String, String)>>> = OnceLock::new();
#[cfg(feature = "wasm")]
static WASM_LLM_RESULTS: OnceLock<Mutex<std::collections::HashMap<u64, String>>> = OnceLock::new();

// ── USER device en WASM (2026-08-28): $DEVICE("user:ask", pregunta) ──
// Mismo contrato que LLM: fork → pending (el JS abre un modal al humano)
// → inject (respuesta) → poll (el VM continúa con la respuesta).
#[cfg(feature = "wasm")]
static WASM_USER_NEXT: OnceLock<std::sync::atomic::AtomicU64> = OnceLock::new();
#[cfg(feature = "wasm")]
static WASM_USER_PENDING: OnceLock<Mutex<Vec<(u64, String)>>> = OnceLock::new();
#[cfg(feature = "wasm")]
static WASM_USER_RESULTS: OnceLock<Mutex<std::collections::HashMap<u64, String>>> = OnceLock::new();

#[cfg(feature = "wasm")]
pub fn wasm_user_fork(prompt: &str) -> u64 {
    let next = WASM_USER_NEXT.get_or_init(|| std::sync::atomic::AtomicU64::new(1));
    let id = next.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let p = WASM_USER_PENDING.get_or_init(|| Mutex::new(Vec::new()));
    p.lock().unwrap().push((id, prompt.to_string()));
    id
}

#[cfg(feature = "wasm")]
pub fn wasm_user_pending() -> Vec<(u64, String)> {
    let p = WASM_USER_PENDING.get_or_init(|| Mutex::new(Vec::new()));
    let mut guard = p.lock().unwrap();
    std::mem::take(&mut *guard)
}

#[cfg(feature = "wasm")]
pub fn wasm_user_inject(id: u64, answer: &str) {
    let r = WASM_USER_RESULTS.get_or_init(|| Mutex::new(std::collections::HashMap::new()));
    r.lock().unwrap().insert(id, answer.to_string());
}

#[cfg(feature = "wasm")]
pub fn wasm_user_poll(id: u64) -> Option<String> {
    let r = WASM_USER_RESULTS.get_or_init(|| Mutex::new(std::collections::HashMap::new()));
    r.lock().unwrap().get(&id).cloned()
}

#[cfg(feature = "wasm")]
pub fn wasm_user_cancel(id: u64) -> bool {
    let r = WASM_USER_RESULTS.get_or_init(|| Mutex::new(std::collections::HashMap::new()));
    r.lock().unwrap().remove(&id).is_some()
}

#[cfg(feature = "wasm")]
pub fn wasm_llm_fork(provider: &str, model: &str, prompt: &str, system: &str) -> u64 {
    let next = WASM_LLM_NEXT.get_or_init(|| std::sync::atomic::AtomicU64::new(1));
    let id = next.fetch_add(1, std::sync::atomic::Ordering::SeqCst);
    let p = WASM_LLM_PENDING.get_or_init(|| Mutex::new(Vec::new()));
    p.lock().unwrap().push((id, provider.to_string(), model.to_string(), prompt.to_string(), system.to_string()));
    id
}

#[cfg(feature = "wasm")]
pub fn wasm_llm_pending() -> Vec<(u64, String, String, String)> {
    let p = WASM_LLM_PENDING.get_or_init(|| Mutex::new(Vec::new()));
    let mut guard = p.lock().unwrap();
    let jobs = std::mem::take(&mut *guard);
    jobs.into_iter().map(|(id, _p, _m, _s, _sys)| (id, _p, _m, _s)).collect()
}

#[cfg(feature = "wasm")]
pub fn wasm_llm_inject(id: u64, result: &str) {
    let r = WASM_LLM_RESULTS.get_or_init(|| Mutex::new(std::collections::HashMap::new()));
    r.lock().unwrap().insert(id, result.to_string());
}

#[cfg(feature = "wasm")]
pub fn wasm_llm_poll(id: u64) -> Option<String> {
    let r = WASM_LLM_RESULTS.get_or_init(|| Mutex::new(std::collections::HashMap::new()));
    r.lock().unwrap().get(&id).cloned()
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
            "local" => "http://127.0.0.1:58099/v1/chat/completions",
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
            } else if item.provider.to_lowercase() == "local" {
                // llama-server: los modelos de razonamiento (qwen3.5+) mandan
                // todo a reasoning_content si no se desactiva el thinking.
                serde_json::json!({
                    "model": item.model,
                    "messages": [
                        {"role": "system", "content": item.system},
                        {"role": "user", "content": item.prompt}
                    ],
                    "max_tokens": 8192,
                    "temperature": 0.7,
                    "chat_template_kwargs": {"enable_thinking": false},
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
            
            let build = || {
                let mut req = minreq::post(url)
                    .with_header("Content-Type", "application/json")
                    .with_timeout(120)
                    .with_body(body_str.clone());

                if is_anthropic {
                    req = req.with_header("x-api-key", &item.api_key)
                             .with_header("anthropic-version", "2023-06-01");
                } else if !item.api_key.is_empty() {
                    req = req.with_header("Authorization", &format!("Bearer {}", item.api_key));
                }
                req
            };

            let resp = minreq_send_retry(build)
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
    /// ¿El próximo `read()` va a bloquear leyendo stdin vivo? (consola web
    /// vía pty / REPL). El VM vuelca entonces la salida pendiente para que
    /// la pregunta (p.ej. «Elige 1/2/3») se vea MIENTRAS espera respuesta.
    fn read_will_block(&self) -> bool {
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

    // ── User Device (pregunta al humano) ────────────────────
    // Async como LLM: la rutina M pregunta ($DEVICE("user:ask", pregunta)),
    // el host (JS/CLI) abre un modal/prompt, y la respuesta se inyecta.
    fn user_ask(&self, _prompt: &str) -> Result<u64, String> {
        Err("User device not implemented".to_string())
    }

    /// Poll: None = el humano aún no ha respondido, Some = respuesta.
    fn user_poll(&self, _future_id: u64) -> Result<Option<String>, String> {
        Ok(None)
    }

    /// Cancela una pregunta en curso.
    fn user_cancel(&self, _future_id: u64) -> Result<bool, String> {
        Ok(false)
    }

    /// Generic device call (HTTP, SQL, etc.). Sync only.
    /// For async devices (LLM), use llm_fork/llm_poll instead.
    fn device_call(&mut self, _device: &str, _action: &str, _args: &[Value]) -> Result<Value, String> {
        Err("Device not supported".to_string())
    }
    fn is_sandbox(&self) -> bool {
        false
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
    /// READ vivo (14-sep-2026): en el REPL interactivo, `R/READ` bloquea y lee
    /// la siguiente línea real de stdin cuando la cola de input está vacía
    /// (la consola web vía pty puede así responder a la máquina).
    pub live_stdin: bool,
    locks: HashMap<(String, Vec<Subscript>), u64>,
    pub llm_api_keys: HashMap<String, String>,
    /// Modo sandbox: deshabilita TODOS los devices (HTTP, LLM, DDP).
    /// Para endpoints públicos que ejecutan M arbitrario (/vm/verify).
    pub sandbox: bool,
    /// Conexión SQLite opcional. Cuando está presente, get/set/kill/data/order    /// operan contra SQLite directamente en vez del BTreeMap en memoria.
    /// (feature "sqlite" — no disponible en builds WASM)
    #[cfg(feature = "sqlite")]
    sqlite_db: Option<Arc<Mutex<rusqlite::Connection>>>,
    /// Registry global de sesiones Smith streaming
    pub smith_registry: Arc<crate::smith::SmithRegistry>,
    /// Caché acotada de namespaces montados como referencia DDP (F2c).
    /// NO se persiste en SQLite: memoria pura, evictable (FIFO por chunks).
    remote_cache: std::sync::Mutex<RemoteCache>,
}

impl Default for MemoryHost {
    fn default() -> Self {
        Self {
            values: BTreeMap::new(),
            transactions: Vec::new(),
            routines: HashMap::new(),
            input: Vec::new(),
            live_stdin: false,
            locks: HashMap::new(),
            llm_api_keys: HashMap::new(),
            sandbox: false,
            #[cfg(feature = "sqlite")]
            sqlite_db: None,
            smith_registry: Arc::new(global_smith_registry().clone()),
            remote_cache: std::sync::Mutex::new(RemoteCache::default()),
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
    #[cfg(feature = "sqlite")]
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
                        let subs = decode_subkey(&subkey_bytes);
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
            live_stdin: false,
            locks: HashMap::new(),
            llm_api_keys: HashMap::new(),
            sandbox: false,
            sqlite_db: Some(Arc::new(Mutex::new(conn))),
            smith_registry: Arc::new(global_smith_registry().clone()),
            remote_cache: std::sync::Mutex::new(RemoteCache::default()),
        })
    }

    pub fn is_sqlite(&self) -> bool {
        #[cfg(feature = "sqlite")]
        { self.sqlite_db.is_some() }
        #[cfg(not(feature = "sqlite"))]
        { false }
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

    /// Chunk remoto (F2c): caché o fetch bajo demanda. `parent` = subíndices
    /// del padre; devuelve sus hijos como [(subs, valor, has_children)].
    fn remote_chunk(
        &self,
        rns: &str,
        parent: &[Subscript],
    ) -> Result<Vec<(Vec<String>, String, bool, bool)>, String> {
        let parent_texts: Vec<String> = parent.iter().map(sub_text).collect();
        if let Ok(mut c) = self.remote_cache.lock() {
            let hit = c.chunks.get(&(rns.to_string(), parent_texts.clone())).cloned();
            match hit {
                Some(h) => {
                    c.hits += 1;
                    return Ok(h);
                }
                None => {
                    c.misses += 1;
                    c.fetches += 1;
                }
            }
        }
        remote_fetch_chunk(self, rns, parent)
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

// ── RAG (F7, 14-sep-2026): recuperación TF-IDF local sobre ^RAG ──────

fn rag_sub_text(s: &Subscript) -> String {
    match s {
        Subscript::String(x) => x.clone(),
        Subscript::Number(n) => format!("{n}"),
    }
}

fn rag_tokens(s: &str) -> Vec<String> {
    const STOP: &[&str] = &[
        "de","la","el","los","las","del","al","un","una","unos","unas","que","qué","y","o","en",
        "es","por","con","para","se","su","sus","lo","como","cómo","mas","más","pero","le","ya",
        "este","esta","esto","si","sí","porque","entre","cuando","cuándo","muy","sin","sobre",
        "también","tambien","me","hasta","hay","donde","dónde","quien","quién","desde","todo",
        "nos","durante","todos","les","ni","contra","otros","otra","otro","otras","ese","esa",
        "eso","ante","ellos","ella","mi","antes","algunos","yo","tanto","estos","estas","mucho",
        "quienes","nada","muchos","cual","poco","estar","algo","solo","sólo","ser","fue","son",
        "han","pues","así","aqui","aquí","alli","allí",
    ];
    let low = s.to_lowercase();
    let mut t = String::with_capacity(low.len());
    for c in low.chars() {
        if c.is_alphanumeric() {
            t.push(c);
        } else {
            t.push(' ');
        }
    }
    t.split_whitespace()
        .filter(|w| w.chars().count() >= 3 && !STOP.contains(w))
        .map(|w| w.to_string())
        .collect()
}

/// Documentos de ^NS("doc",id,"texto") → [(id, texto)]
fn rag_docs(host: &MemoryHost, ns: &str) -> Vec<(String, String)> {
    let mut out: Vec<(String, String)> = Vec::new();
    for ((n, subs), v) in host.values.iter() {
        if n.as_str() != ns || subs.len() != 3 {
            continue;
        }
        let es_doc = matches!(&subs[0], Subscript::String(x) if x.as_str() == "doc");
        let es_texto = matches!(&subs[2], Subscript::String(x) if x.as_str() == "texto");
        if es_doc && es_texto {
            let txt = v.as_string();
            if !txt.trim().is_empty() {
                out.push((rag_sub_text(&subs[1]), txt));
            }
        }
    }
    out
}

fn rag_query(host: &MemoryHost, args: &[Value]) -> String {
    let q = args.first().map(|v| v.as_string()).unwrap_or_default();
    let ns = args
        .get(1)
        .map(|v| v.as_string())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "RAG".to_string());
    let k = args
        .get(2)
        .map(|v| v.as_number() as usize)
        .unwrap_or(4)
        .clamp(1, 20);
    let filtro = args
        .get(3)
        .map(|v| v.as_string())
        .unwrap_or_default();
    if q.trim().is_empty() {
        return "uso: $DEVICE(\"rag:query\",\"pregunta\",[ns],[k],[filtro])".to_string();
    }
    let mut docs = rag_docs(host, &ns);
    let filtros: Vec<&str> = filtro.split('|').filter(|s| !s.trim().is_empty()).collect();
    if !filtros.is_empty() {
        // ── F8 (14-sep-2026): alcance por libro — el prefijo del id (p.ej. "V10-") ──
        docs.retain(|(id, _)| filtros.iter().any(|f| id.starts_with(*f)));
    }
    if docs.is_empty() {
        return String::new();
    }
    let mut df: HashMap<String, u32> = HashMap::new();
    let mut tfs: Vec<HashMap<String, u32>> = Vec::with_capacity(docs.len());
    for (_, txt) in docs.iter() {
        let mut tf: HashMap<String, u32> = HashMap::new();
        for t in rag_tokens(txt) {
            *tf.entry(t).or_insert(0) += 1;
        }
        for t in tf.keys() {
            *df.entry(t.clone()).or_insert(0) += 1;
        }
        tfs.push(tf);
    }
    let n = docs.len() as f64;
    let mut q_set: Vec<String> = Vec::new();
    for t in rag_tokens(&q) {
        if !q_set.contains(&t) {
            q_set.push(t);
        }
    }
    let mut scored: Vec<(f64, usize)> = Vec::new();
    for (i, tf) in tfs.iter().enumerate() {
        let len: u32 = tf.values().sum();
        if len == 0 {
            continue;
        }
        let mut score = 0.0f64;
        for t in q_set.iter() {
            if let Some(&f) = tf.get(t) {
                let d = *df.get(t).unwrap_or(&1) as f64;
                let idf = (1.0 + n / d).ln();
                score += (f as f64 / len as f64) * idf * idf;
            }
        }
        if score > 0.0 {
            scored.push((score, i));
        }
    }
    scored.sort_by(|a, b| b.0.partial_cmp(&a.0).unwrap_or(std::cmp::Ordering::Equal));
    let mut out = String::new();
    for (score, i) in scored.iter().take(k) {
        let (id, txt) = &docs[*i];
        let short: String = txt.chars().take(280).collect();
        out.push_str(&format!(
            "— [{}] (s={:.2}) {}\n",
            id,
            score,
            short.replace(['\n', '\r'], " ")
        ));
    }
    out.trim_end().to_string()
}

fn rag_stats(host: &MemoryHost, args: &[Value]) -> String {
    let ns = args
        .first()
        .map(|v| v.as_string())
        .filter(|s| !s.trim().is_empty())
        .unwrap_or_else(|| "RAG".to_string());
    let docs = rag_docs(host, &ns);
    let chars: usize = docs.iter().map(|(_, t)| t.chars().count()).sum();
    format!("docs={};chars={}", docs.len(), chars)
}

/// F6 (14-sep-2026): datos vivos del proceso/sistema para %SS («top» del nodo).
/// Linux: /proc (status/stat/loadavg/meminfo/uptime/fd). Otros S.O.: lo básico (pid).
fn sys_top() -> String {
    #[allow(unused_mut)]
    let mut s = format!("pid={}", std::process::id());
    #[cfg(target_os = "linux")]
    {
        fn campo(texto: &str, clave: &str) -> String {
            texto
                .lines()
                .find(|l| l.starts_with(clave))
                .and_then(|l| l.split_whitespace().nth(1))
                .unwrap_or_default()
                .to_string()
        }
        if let Ok(st) = std::fs::read_to_string("/proc/self/status") {
            let rss = campo(&st, "VmRSS:");
            let hwm = campo(&st, "VmHWM:");
            let thr = campo(&st, "Threads:");
            if !rss.is_empty() {
                s.push_str(&format!(";rss_kb={rss}"));
            }
            if !hwm.is_empty() {
                s.push_str(&format!(";hwm_kb={hwm}"));
            }
            if !thr.is_empty() {
                s.push_str(&format!(";threads={thr}"));
            }
        }
        if let Ok(stat) = std::fs::read_to_string("/proc/self/stat") {
            if let Some((_, tras)) = stat.rsplit_once(')') {
                let f: Vec<&str> = tras.split_whitespace().collect();
                if f.len() > 20 {
                    let ut: u64 = f[11].parse().unwrap_or(0);
                    let st_: u64 = f[12].parse().unwrap_or(0);
                    let inicio: u64 = f[19].parse().unwrap_or(0);
                    let ticks = ut + st_;
                    s.push_str(&format!(";cpu_ticks={ticks}"));
                    if let Ok(up) = std::fs::read_to_string("/proc/uptime") {
                        if let Some(sys_up) =
                            up.split_whitespace().next().and_then(|x| x.parse::<f64>().ok())
                        {
                            let proc_up = sys_up - (inicio as f64 / 100.0);
                            if proc_up > 0.5 {
                                s.push_str(&format!(";uptime_s={}", proc_up as u64));
                                let pct = (ticks as f64 / 100.0) / proc_up * 100.0;
                                s.push_str(&format!(";cpu_pct={pct:.1}"));
                            }
                        }
                    }
                }
            }
        }
        if let Ok(ld) = std::fs::read_to_string("/proc/loadavg") {
            let p: Vec<&str> = ld.split_whitespace().collect();
            if p.len() >= 3 {
                s.push_str(&format!(";load1={};load5={};load15={}", p[0], p[1], p[2]));
            }
        }
        if let Ok(mi) = std::fs::read_to_string("/proc/meminfo") {
            let tot = campo(&mi, "MemTotal:");
            let mut av = campo(&mi, "MemAvailable:");
            if av.is_empty() {
                // kernels viejos (DSM 3.10) sin MemAvailable → MemFree
                av = campo(&mi, "MemFree:");
            }
            if !tot.is_empty() {
                s.push_str(&format!(";mem_total_kb={tot}"));
            }
            if !av.is_empty() {
                s.push_str(&format!(";mem_avail_kb={av}"));
            }
        }
        if let Ok(rd) = std::fs::read_dir("/proc/self/fd") {
            s.push_str(&format!(";fds={}", rd.count()));
        }
    }
    s
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

#[cfg(feature = "minreq")]
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
    // Allowlist explícita: LUMEN_HTTP_ALLOW="host1,host2" permite esos hosts
    // aunque sean locales/privados (caso legítimo: la MVM llamando a SU propio
    // poli_server vía 127.0.0.1 — rutinas LLMFREE/FIXER). Solo si se configura.
    if let Ok(allow_raw) = std::env::var("LUMEN_HTTP_ALLOW") {
        let lower_host = host.to_lowercase();
        for allowed in allow_raw.split(',').map(|s| s.trim().to_lowercase()) {
            if !allowed.is_empty() && allowed == lower_host {
                return Ok(());
            }
        }
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
    // 14-sep-2026: retry — los hipos DNS esporádicos de la LAN (~1/N «Try again»)
    // abortaban el fetch justo aquí (medido: T08CADENA en la NAS).
    let mut addrs: Option<Vec<std::net::SocketAddr>> = None;
    let mut last_err = String::new();
    for attempt in 1..=3u64 {
        match std::net::ToSocketAddrs::to_socket_addrs(&(host, 443)) {
            Ok(a) => {
                addrs = Some(a.collect());
                break;
            }
            Err(e) => {
                last_err = format!("HTTP: resolución DNS de {host} falló: {e}");
                if attempt < 3 {
                    std::thread::sleep(std::time::Duration::from_millis(250 * attempt));
                }
            }
        }
    }
    let addrs = addrs.ok_or(last_err)?;
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

#[cfg(feature = "minreq")]
// ── SEARCH device (2026-09-04): $DEVICE("search:web", query, [n], [include_answer]) ──
// Búsqueda web vía endpoint estilo Tavily (POST + Authorization: Bearer).
// Config por env del proceso (NUNCA en el repo): LUMEN_SEARCH_API_KEY (obligatoria),
// LUMEN_SEARCH_URL (default: https://api.tavily.com/search) → permite conectar
// cualquier fuente compatible (Tom /v1/search, otra API, etc.) cambiando la URL.
// Contrato (idéntico a Tom /v1/search):
//   $DEVICE("search:web", ...)   → {"ok":true,"count":N,"results":[{"title","url","content","score"}],"answer":?}
//   $DEVICE("search:text", ...)  → texto legible listo para personalidades:
//                                    "1. Titulo\n   URL\n   snippet..." ("ERROR: ..." si falla)
fn search_web_common(args: &[Value], as_text: bool) -> Result<Value, String> {
    let query = args.first().map(|v| v.as_string()).unwrap_or_default().trim().to_string();
    if query.is_empty() {
        return Err("SEARCH: query requerida".to_string());
    }
    let n = args
        .get(1)
        .map(|v| v.as_string().parse::<usize>().unwrap_or(5))
        .unwrap_or(5)
        .clamp(1, 10);
    let include_answer = args
        .get(2)
        .map(|v| {
            let s = v.as_string();
            s == "1" || s.eq_ignore_ascii_case("true")
        })
        .unwrap_or(false);
    let key = std::env::var("LUMEN_SEARCH_API_KEY").unwrap_or_default();
    if key.is_empty() {
        return Err("SEARCH: LUMEN_SEARCH_API_KEY no configurada (env del proceso)".to_string());
    }
    let url = std::env::var("LUMEN_SEARCH_URL")
        .unwrap_or_else(|_| "https://api.tavily.com/search".to_string());
    let body_obj = serde_json::json!({
        "query": query,
        "max_results": n,
        "search_depth": "basic",
        "topic": "general",
        "include_answer": include_answer,
        "include_raw_content": false,
    });
    let headers = serde_json::json!({
        "Authorization": format!("Bearer {}", key),
        "Content-Type": "application/json",
    });
    let call_args = vec![
        Value::String(url),
        Value::String(body_obj.to_string()),
        Value::String(headers.to_string()),
        Value::String("20".to_string()),
    ];
    let resp = http_full_request("post", &call_args)?;
    let parsed: serde_json::Value = serde_json::from_str(&resp.as_string())
        .map_err(|e| format!("SEARCH: respuesta device inválida: {e}"))?;
    let status = parsed.get("status").and_then(|v| v.as_i64()).unwrap_or(0);
    let body_str = parsed.get("body").and_then(|v| v.as_str()).unwrap_or("");
    if status != 200 {
        let err = if body_str.is_empty() {
            format!("HTTP {status}")
        } else {
            let short: String = body_str.chars().take(300).collect();
            format!("HTTP {status}: {short}")
        };
        let json_err = serde_json::json!({"ok": false, "error": err}).to_string();
        return Ok(Value::String(if as_text {
            format!("ERROR: SEARCH {err}")
        } else {
            json_err
        }));
    }
    let tav: serde_json::Value = serde_json::from_str(body_str)
        .map_err(|e| format!("SEARCH: body del endpoint inválido: {e}"))?;
    let results: Vec<serde_json::Value> = tav
        .get("results")
        .and_then(|r| r.as_array())
        .map(|arr| {
            arr.iter()
                .map(|r| {
                    serde_json::json!({
                        "title": r.get("title").and_then(|v| v.as_str()).unwrap_or(""),
                        "url": r.get("url").and_then(|v| v.as_str()).unwrap_or(""),
                        "content": r.get("content").and_then(|v| v.as_str()).unwrap_or("").chars().take(2000).collect::<String>(),
                        "score": r.get("score").and_then(|v| v.as_f64()),
                    })
                })
                .collect()
        })
        .unwrap_or_default();
    if as_text {
        let mut out = String::new();
        for (i, r) in results.iter().enumerate() {
            let title = r.get("title").and_then(|v| v.as_str()).unwrap_or("");
            let url = r.get("url").and_then(|v| v.as_str()).unwrap_or("");
            let content: String = r
                .get("content")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .chars()
                .take(300)
                .collect();
            out.push_str(&format!("{}. {}\n   {}\n   {}\n", i + 1, title, url, content.trim()));
        }
        if out.is_empty() {
            out = "Sin resultados para la búsqueda.".to_string();
        }
        return Ok(Value::String(out));
    }
    Ok(Value::String(
        serde_json::json!({
            "ok": true,
            "count": results.len(),
            "results": results,
            "answer": tav.get("answer").and_then(|v| v.as_str()),
        })
        .to_string(),
    ))
}

#[cfg(feature = "minreq")]
fn search_web(args: &[Value]) -> Result<Value, String> {
    search_web_common(args, false)
}

#[cfg(feature = "minreq")]
fn search_web_text(args: &[Value]) -> Result<Value, String> {
    search_web_common(args, true)
}

/// 14-sep-2026 — Retry de minreq ante fallos ESPORÁDICOS de resolución DNS de la
/// NAS (musl + kernel 3.2: «Try again»/EAI_AGAIN ~1 de cada N lookups; medido
/// con la sonda dnsprobe: un fallo aislado y el MISMO lookup 20 ms después OK).
/// Reconstruye la request (el builder es FnMut) y reintenta SOLO errores de
/// lookup/conexión — los errores HTTP no se reintentan.
#[cfg(feature = "minreq")]
fn minreq_send_retry<F>(mut build: F) -> Result<minreq::Response, minreq::Error>
where
    F: FnMut() -> minreq::Request,
{
    let mut last: Option<minreq::Error> = None;
    for attempt in 1..=3u64 {
        match build().send() {
            Ok(r) => return Ok(r),
            Err(e) => {
                let msg = format!("{e}");
                let retryable = msg.contains("lookup")
                    || msg.contains("Try again")
                    || msg.contains("efused")
                    || msg.contains("eset");
                if attempt < 3 && retryable {
                    std::thread::sleep(std::time::Duration::from_millis(250 * attempt));
                    last = Some(e);
                    continue;
                }
                return Err(e);
            }
        }
    }
    Err(last.expect("retry loop: last error"))
}

#[cfg(feature = "minreq")]
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

    let build = || {
        let mut req = match action {
            "get" => minreq::get(&url),
            "head" => minreq::head(&url),
            "post" => minreq::post(&url),
            "put" => minreq::put(&url),
            "delete" => minreq::delete(&url),
            _ => minreq::get(&url),
        }
        .with_timeout(timeout_s);
        for (k, v) in &headers {
            req = req.with_header(k.as_str(), v.as_str());
        }
        if has_body {
            req = req.with_body(body.clone());
        }
        req
    };
    if !matches!(action, "get" | "head" | "post" | "put" | "delete") {
        return Err(format!("HTTP: método no soportado: {action}"));
    }

    let resp = minreq_send_retry(build).map_err(|e| format!("HTTP {action} error: {e}"))?;
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

/// Stub sin `minreq`: builds nativos mínimos (NAS/edge) sin HTTP compilan igual;
/// el device responde con error claro en vez de romper la compilación.
#[cfg(not(feature = "minreq"))]
fn http_full_request(_action: &str, _args: &[Value]) -> Result<Value, String> {
    Err("HTTP device no disponible en este build (feature minreq off)".to_string())
}

/// MCP JSON-RPC 2.0 request (transporte HTTP, estilo streamable POST).
/// Devuelve SIEMPRE {"ok":true,"result":...} | {"ok":false,"error":"..."}.
/// Sin ssrf_guard a proposito: los servidores MCP viven registrados en
/// ^SYS("MCP",<server>,url) de la PDB — vecindario de confianza del ambito
/// (mismo principio que el device agent), no URLs arbitrarias del M.
#[cfg(feature = "minreq")]
fn mcp_http_request(
    url: &str,
    method: &str,
    params: &serde_json::Value,
    hmac_key: &str,
    auth: &str,
    extra: &[(String, String)],
) -> Result<Value, String> {
    const MAX_BODY: usize = 300 * 1024;
    let body = serde_json::json!({
        "jsonrpc": "2.0",
        "method": method,
        "params": params,
        "id": 1,
    }).to_string();
    let mut req = minreq::post(url)
        .with_timeout(20)
        .with_header("Content-Type", "application/json")
        .with_header("Accept", "application/json, text/event-stream")
        .with_body(body.clone());
    for (k, v) in extra {
        req = req.with_header(k.as_str(), v.as_str());
    }
    if !auth.is_empty() {
        req = req.with_header("Authorization", auth);
    }
    if !hmac_key.is_empty() {
        // Firma del ecosistema: HMAC-SHA256(ts + body + secret) en hex
        // (mismo esquema que el device agent edge y mcp_bridge.py).
        let ts = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs()
            .to_string();
        let sig = hmac_sha256(hmac_key, &format!("{ts}{body}{hmac_key}"));
        req = req.with_header("X-DDP-HMAC", &sig);
        req = req.with_header("X-DDP-Timestamp", &ts);
    }
    let resp = req.send().map_err(|e| format!("MCP {method} error: {e}"))?;
    let status = resp.status_code;
    let bytes = resp.as_bytes();
    let text = String::from_utf8_lossy(&bytes[..bytes.len().min(MAX_BODY)]).to_string();
    let parsed: serde_json::Value = match serde_json::from_str(&text) {
        Ok(v) => v,
        Err(_) => {
            return Ok(Value::String(serde_json::json!({
                "ok": status >= 200 && status < 300,
                "error": format!("respuesta no JSON-RPC (status {status})"),
                "raw": text,
            }).to_string()));
        }
    };
    if let Some(err) = parsed.get("error") {
        return Ok(Value::String(serde_json::json!({"ok": false, "error": err}).to_string()));
    }
    Ok(Value::String(serde_json::json!({"ok": true, "result": parsed.get("result")}).to_string()))
}

/// Stub sin `minreq` (misma razón que `http_full_request`): el device MCP
/// solo existe con transporte HTTP; sin la feature, error claro.
#[cfg(not(feature = "minreq"))]
fn mcp_http_request(
    _url: &str,
    _method: &str,
    _params: &serde_json::Value,
    _hmac_key: &str,
    _auth: &str,
    _extra: &[(String, String)],
) -> Result<Value, String> {
    Err("MCP device no disponible en este build (feature minreq off)".to_string())
}

/// Lee `^CONFIG("ddp_peer")` + `^CONFIG("ddp_hmac_key")` del host (F2 — hub DDP).
fn ddp_cfg(host: &MemoryHost) -> Result<(String, String), String> {
    let peer = match host.get("CONFIG", &[Subscript::String("ddp_peer".to_string())]) {
        Ok(Some(v)) => v.as_string(),
        _ => String::new(),
    };
    if peer.is_empty() {
        return Err(
            "DDP: configura ^CONFIG(\"ddp_peer\") (ej: S ^CONFIG(\"ddp_peer\")=\"http://192.168.1.10:8081\")"
                .to_string(),
        );
    }
    let key = match host.get("CONFIG", &[Subscript::String("ddp_hmac_key".to_string())]) {
        Ok(Some(v)) => v.as_string(),
        _ => String::new(),
    };
    Ok((peer, key))
}

/// Texto canónico de un subscript para JSON de DDP.
fn sub_text(s: &Subscript) -> String {
    match s {
        Subscript::Number(n) => {
            if n.fract() == 0.0 {
                format!("{}", *n as i64)
            } else {
                format!("{n}")
            }
        }
        Subscript::String(x) => x.clone(),
    }
}

/// ── F2c (14-sep-2026): referencias DDP — namespaces remotos montados ──
/// Un ns con `^CONFIG("mount",NS)` definido se lee POR REFERENCIA: los reads
/// ($G/$O/$D) que no están en local se traen del hub BAJO DEMANDA y se cachean
/// en RAM de forma acotada (nunca se vuelcan a la PDB local → el nodo no
/// materializa los datos). Los writes siguen siendo locales (bandeja de salida:
/// `%DS("NS","U")` los sube al hub después).
#[derive(Default)]
struct RemoteCache {
    /// chunk = hijos de un padre remoto:
    /// (ns_remoto, padre) → [(subs, valor, has_children, has_value)]
    chunks: std::collections::BTreeMap<(String, Vec<String>), Vec<(Vec<String>, String, bool, bool)>>,
    /// orden de inserción para evicción FIFO (≈LRU)
    lru: std::collections::VecDeque<(String, Vec<String>)>,
    count: usize,
    hits: u64,
    misses: u64,
    fetches: u64,
}

impl RemoteCache {
    fn clear(&mut self) -> usize {
        let n = self.chunks.len();
        self.chunks.clear();
        self.lru.clear();
        self.count = 0;
        n
    }
    fn stats(&self) -> String {
        format!(
            "chunks={} nodos={} hits={} misses={} fetches={}",
            self.chunks.len(),
            self.count,
            self.hits,
            self.misses,
            self.fetches
        )
    }
}

/// ¿Está la ns montada como referencia? Devuelve el nombre remoto (o None).
fn remote_mount(host: &MemoryHost, ns: &str) -> Option<String> {
    if host.sandbox || ns == "CONFIG" || ns == "SYSINFO" {
        return None;
    }
    let key = (
        "CONFIG".to_string(),
        vec![
            Subscript::String("mount".to_string()),
            Subscript::String(ns.to_string()),
        ],
    );
    match host.values.get(&key) {
        Some(v) => {
            let r = v.as_string();
            if r.trim().is_empty() {
                Some(ns.to_string())
            } else {
                Some(r.trim().to_string())
            }
        }
        None => None,
    }
}

fn cache_max(host: &MemoryHost) -> usize {
    host.values
        .get(&(
            "CONFIG".to_string(),
            vec![Subscript::String("cache_max".to_string())],
        ))
        .map(|v| v.as_number() as usize)
        .filter(|n| *n >= 16)
        .unwrap_or(4096)
}

fn cache_fetch_limit(host: &MemoryHost) -> usize {
    host.values
        .get(&(
            "CONFIG".to_string(),
            vec![Subscript::String("cache_limit".to_string())],
        ))
        .map(|v| v.as_number() as usize)
        .filter(|n| *n >= 1)
        .unwrap_or(500)
}

/// Mete un chunk en la caché con evicción FIFO acotada.
fn insert_chunk(
    host: &MemoryHost,
    rns: &str,
    parent_texts: &[String],
    entries: Vec<(Vec<String>, String, bool, bool)>,
) {
    let max = cache_max(host);
    if let Ok(mut c) = host.remote_cache.lock() {
        let key = (rns.to_string(), parent_texts.to_vec());
        if let Some(old) = c.chunks.remove(&key) {
            c.count = c.count.saturating_sub(old.len());
        }
        c.lru.retain(|k| k != &key);
        c.count += entries.len();
        c.chunks.insert(key.clone(), entries);
        c.lru.push_back(key);
        while c.count > max {
            match c.lru.pop_front() {
                Some(k) => {
                    if let Some(old) = c.chunks.remove(&k) {
                        c.count = c.count.saturating_sub(old.len());
                    }
                }
                None => break,
            }
        }
    }
}

/// Fetch de un chunk remoto (hijos de `parent`) con pull depth=0. Solo en miss.
fn remote_fetch_chunk(
    host: &MemoryHost,
    rns: &str,
    parent: &[Subscript],
) -> Result<Vec<(Vec<String>, String, bool, bool)>, String> {
    let (peer, key) = ddp_cfg(host)?;
    let parent_texts: Vec<String> = parent.iter().map(sub_text).collect();
    let limit = cache_fetch_limit(host);
    let path = if parent_texts.is_empty() {
        format!(
            "/ddp/pull?ns={}&limit={}&depth=0",
            crate::ddp_client::urlenc(rns),
            limit
        )
    } else {
        let prefix = parent_texts
            .iter()
            .map(|s| crate::ddp_client::urlenc(s))
            .collect::<Vec<_>>()
            .join(",");
        format!(
            "/ddp/pull?ns={}&limit={}&depth=0&prefix={}",
            crate::ddp_client::urlenc(rns),
            limit,
            prefix
        )
    };
    let (status, body) = crate::ddp_client::get_signed(&peer, &path, &key)?;
    if status != 200 {
        return Err(format!(
            "DDP refs: pull HTTP {status}: {}",
            body.chars().take(200).collect::<String>()
        ));
    }
    let parsed: serde_json::Value =
        serde_json::from_str(&body).map_err(|e| format!("DDP refs: JSON inválido: {e}"))?;
    let mut out: Vec<(Vec<String>, String, bool, bool)> = Vec::new();
    if let Some(entries) = parsed.get("entries").and_then(|e| e.as_array()) {
        for e in entries {
            let subs: Vec<String> = e
                .get("subs")
                .and_then(|s| s.as_array())
                .map(|arr| {
                    arr.iter()
                        .map(|x| x.as_str().unwrap_or("").to_string())
                        .collect()
                })
                .unwrap_or_default();
            let val = e
                .get("value")
                .and_then(|v| v.as_str())
                .unwrap_or("")
                .to_string();
            let hc = e
                .get("has_children")
                .and_then(|h| h.as_bool())
                .unwrap_or(false);
            // Fallback si el server no manda has_value (pre 14-sep): valor no vacío.
            let hv = e
                .get("has_value")
                .and_then(|h| h.as_bool())
                .unwrap_or(!val.is_empty());
            out.push((subs, val, hc, hv));
        }
    }
    insert_chunk(host, rns, &parent_texts, out.clone());
    Ok(out)
}

impl Host for MemoryHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        // Read from in-memory BTreeMap
        if let Some(v) = self.values.get(&(ns.to_string(), subs.to_vec())) {
            return Ok(Some(v.clone()));
        }
        // F2c: ns montada → chunk del padre (fetch bajo demanda + caché acotada)
        if let Some(rns) = remote_mount(self, ns) {
            let parent: &[Subscript] = if subs.is_empty() { &[] } else { &subs[..subs.len() - 1] };
            let path: Vec<String> = subs.iter().map(sub_text).collect();
            let chunk = self.remote_chunk(&rns, parent)?;
            for (c_subs, c_val, _hc, _hv) in chunk.iter() {
                if c_subs == &path {
                    return Ok(Some(Value::String(c_val.clone())));
                }
            }
        }
        Ok(None)
    }

    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        // Always update in-memory BTreeMap first
        self.values.insert((ns.to_string(), subs.to_vec()), value.clone());
        // Persist to SQLite if available
        #[cfg(feature = "sqlite")]
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
        #[cfg(feature = "sqlite")]
        if let Some(ref db) = self.sqlite_db {
            let subkey = encode_subkey(subs);
            let conn = db.lock().map_err(|e| format!("kill lock: {e}"))?;
            if subs.is_empty() {
                conn.execute("DELETE FROM _globals WHERE ns=?1", rusqlite::params![ns])
                    .map_err(|e| format!("kill ns: {e}"))?;
            } else {
                conn.execute("DELETE FROM _globals WHERE ns=?1 AND subkey=?2",
                        rusqlite::params![ns, subkey])
                    .map_err(|e| format!("kill node: {e}"))?;
                // Fix 2026-09-10 (bug kill-subarbol vs SQLite): los subkey son BLOB
                // (02+ascii+ff) y LIKE no matchea sobre BLOB — los descendientes
                // quedaban huerfanos tras un K de subarbol. Prefijo binario exacto
                // via substr. OJO: encode_subkey añade el terminador \xff final;
                // para matchear descendientes el prefijo va SIN ese terminador.
                let prefix: Vec<u8> = subs.iter().flat_map(|s| encode_one_sub(s)).collect();
                let prefix_len = prefix.len() as i64;
                conn.execute("DELETE FROM _globals WHERE ns=?1 AND subkey>?2 AND substr(subkey,1,?3)=?2",
                        rusqlite::params![ns, prefix, prefix_len])
                    .map_err(|e| format!("kill subtree: {e}"))?;
            }
        }
        Ok(count)
    }

    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        let own = self.values.contains_key(&(ns.to_string(), subs.to_vec()));
        let child = self.values.keys().any(|(candidate_ns, candidate)| {
            candidate_ns == ns && candidate.len() > subs.len() && is_prefix(subs, candidate)
        });
        if own || child {
            return Ok(match (own, child) {
                (true, true) => 11, (true, false) => 1,
                (false, true) => 10, (false, false) => 0,
            });
        }
        // F2c: ns montada → $D por referencia (has_value/has_children del server)
        if let Some(rns) = remote_mount(self, ns) {
            let parent: &[Subscript] = if subs.is_empty() { &[] } else { &subs[..subs.len() - 1] };
            let path: Vec<String> = subs.iter().map(sub_text).collect();
            let chunk = self.remote_chunk(&rns, parent)?;
            let mut own_r = false;
            let mut child_r = false;
            for (c_subs, _c_val, hc, hv) in chunk.iter() {
                if c_subs == &path {
                    own_r = *hv;
                    child_r = *hc;
                }
            }
            return Ok(match (own_r, child_r) {
                (true, true) => 11, (true, false) => 1,
                (false, true) => 10, (false, false) => 0,
            });
        }
        Ok(0)
    }

    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        // Candidatos locales: subíndices descendientes directos de `parent`
        let mut candidates: Vec<Subscript> = Vec::new();
        for (candidate_ns, subs) in self.values.keys() {
            if candidate_ns == ns && is_prefix(parent, subs) && subs.len() > parent.len() {
                candidates.push(subs[parent.len()].clone());
            }
        }
        // F2c: candidatos remotos (ns montada) — mismo nivel, desde el chunk
        if let Some(rns) = remote_mount(self, ns) {
            if let Ok(chunk) = self.remote_chunk(&rns, parent) {
                let plen = parent.len();
                for (c_subs, _, _, _) in chunk.iter() {
                    if c_subs.len() > plen {
                        candidates.push(Subscript::String(c_subs[plen].clone()));
                    }
                }
            }
        }
        // Orden canónico MUMPS (números antes que strings) + únicos
        candidates.sort_by(|a, b| a.canonical_cmp(b));
        candidates.dedup();

        if direction >= 0 {
            for candidate in candidates.iter() {
                if let Some(ref cur) = current {
                    if candidate.canonical_cmp(cur) != std::cmp::Ordering::Greater {
                        continue;
                    }
                }
                return Ok(Some(candidate.clone()));
            }
        } else {
            for candidate in candidates.iter().rev() {
                if let Some(ref cur) = current {
                    if candidate.canonical_cmp(cur) != std::cmp::Ordering::Less {
                        continue;
                    }
                }
                return Ok(Some(candidate.clone()));
            }
        }
        Ok(None)
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
        if !self.input.is_empty() {
            return Ok(self.input.remove(0));
        }
        // READ vivo (14-sep-2026): REPL interactivo en terminal → bloquear y
        // leer una línea real de stdin. El lock de std es reentrante y el
        // bucle del REPL comparte el mismo BufReader: la línea no se pierde.
        if self.live_stdin {
            use std::io::{BufRead, IsTerminal, Write};
            if std::io::stdin().is_terminal() {
                // Marca de espera (14-sep-2026): la consola web detecta este
                // prompt «⟩» para saber que el nodo está bloqueado en un READ
                // (y no simplemente pensando, p.ej. esperando a un LLM).
                eprint!("⟩ ");
                std::io::stderr().flush().ok();
                let mut line = String::new();
                match std::io::stdin().lock().read_line(&mut line) {
                    Ok(0) => return Ok(String::new()),
                    Ok(_) => return Ok(line.trim_end_matches(['\n', '\r']).to_string()),
                    Err(e) => return Err(format!("read stdin: {e}")),
                }
            }
        }
        Ok(String::new())
    }

    fn read_will_block(&self) -> bool {
        use std::io::IsTerminal;
        self.live_stdin && std::io::stdin().is_terminal()
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
        #[cfg(feature = "wasm")]
        { return Ok(wasm_llm_fork(provider, model, prompt, system)); }
        #[cfg(not(feature = "wasm"))]
        {
            // Nodo (14-sep-2026): si el env del proceso no trae key, caer a
            // ^CONFIG("llm_key_<proveedor>") — mismo patrón que la clave DDP:
            // la consola del nodo se autoconfigura desde su propia PDB (sin
            // exports de shell en el NAS). El env SIEMPRE gana si está.
            let env_name = match provider.to_lowercase().as_str() {
                "openrouter" => Some("OPENROUTER_API_KEY"),
                "deepseek" => Some("DEEPSEEK_API_KEY"),
                "lingyi" | "zai" | "yi" => Some("LINGYI_API_KEY"),
                "anthropic" => Some("ANTHROPIC_AUTH_TOKEN"),
                _ => None,
            };
            if let Some(name) = env_name {
                if std::env::var(name).unwrap_or_default().is_empty() {
                    if let Ok(Some(v)) = self.get(
                        "CONFIG",
                        &[Subscript::String(format!("llm_key_{}", provider.to_lowercase()))],
                    ) {
                        let s = v.as_string();
                        if !s.trim().is_empty() {
                            std::env::set_var(name, s.trim().to_string());
                        }
                    }
                }
            }
            Ok(self.pool().fork(provider, model, prompt, system))
        }
    }

        fn llm_poll(&self, future_id: u64) -> Result<Option<String>, String> {
        #[cfg(feature = "wasm")]
        { return Ok(wasm_llm_poll(future_id)); }
        #[cfg(not(feature = "wasm"))]
        {
            // First check LLM futures — None = pending, Some("FUTURE_NOT_FOUND") = unknown
            let r = self.pool().poll(future_id);
            if r != Some("FUTURE_NOT_FOUND".to_string()) {
                return Ok(r);
            }
            // Not an LLM future, check bg fibers
            Ok(global_bg_pool().poll(future_id))
        }
    }

    fn llm_cancel(&self, future_id: u64) -> Result<bool, String> {
        Ok(self.pool().cancel(future_id))
    }

    fn llm_chain(&self, parent_id: u64, provider: &str, model: &str, prompt: &str, system: &str) -> Result<u64, String> {
        Ok(self.pool().chain(parent_id, provider, model, prompt, system))
    }

    // ── User Device implementation ($DEVICE("user:ask")) ─────
    // Async como LLM: fork → pending (JS abre modal) → inject → poll.
    fn user_ask(&self, prompt: &str) -> Result<u64, String> {
        #[cfg(feature = "wasm")]
        { return Ok(wasm_user_fork(prompt)); }
        #[cfg(not(feature = "wasm"))]
        { Err("user device requiere host JS/CLI (solo wasm)".to_string()) }
    }

    fn user_poll(&self, future_id: u64) -> Result<Option<String>, String> {
        #[cfg(feature = "wasm")]
        { return Ok(wasm_user_poll(future_id)); }
        #[cfg(not(feature = "wasm"))]
        { Ok(None) }
    }

    fn user_cancel(&self, future_id: u64) -> Result<bool, String> {
        #[cfg(feature = "wasm")]
        { return Ok(wasm_user_cancel(future_id)); }
        #[cfg(not(feature = "wasm"))]
        { Ok(false) }
    }

    // ── Generic device call (HTTP, future devices) ────────────
    fn entries(&self) -> Result<Vec<GlobalEntry>, String> {
        #[cfg(feature = "sqlite")]
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
                let val = if let Ok(n) = value.trim().parse::<f64>() { Value::Number(n) } else { Value::String(value) };
                entries.push(GlobalEntry { ns, subs, value: val });
            }
            return Ok(entries);
        }
        Ok(MemoryHost::entries(self))
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

    fn is_sandbox(&self) -> bool {
        self.sandbox
    }

    fn device_call(&mut self, device: &str, action: &str, args: &[Value]) -> Result<Value, String> {
        if self.sandbox {
            // Modo sandbox (endpoint público /vm/verify): sin devices.
            // Un script M arbitrario no debe poder hacer HTTP (SSRF/DoS al
            // server ni a la red), llamar al LLM ni tocar DDP.
            return Err(format!(
                "Device '{device}:{action}' disabled in sandbox mode"
            ));
        }
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
            "sys" => {
                // ── F6 (14-sep-2026): $DEVICE("sys:top") — top del nodo (proceso/sistema) ──
                // Devuelve "k=v;k=v;…" con lo disponible: pid, uptime_s, rss_kb, hwm_kb,
                // threads, fds, cpu_ticks, cpu_pct, load1/5/15, mem_total_kb, mem_avail_kb.
                match action {
                    "top" | "stat" => Ok(Value::String(sys_top())),
                    _ => Err(format!("Unknown SYS action: {action}")),
                }
            }
            "rag" => {
                // ── F7 (14-sep-2026): RAG local TF-IDF sobre ^RAG("doc",id,…) ──
                //   $DEVICE("rag:query","pregunta",[ns="RAG"],[k=4]) → líneas "— [id] …"
                //   $DEVICE("rag:stats",[ns])                         → "docs=N;chars=M"
                match action {
                    "query" => Ok(Value::String(rag_query(self, &args))),
                    "stats" => Ok(Value::String(rag_stats(self, &args))),
                    _ => Err(format!("Unknown RAG action: {action}")),
                }
            }
            #[cfg(feature = "ssh")]
            "ssh" => {
                // ── PoC 16-sep-2026: manos SSH del nodo (cliente ssh del sistema) ──
                //   $DEVICE("ssh:exec","user@host","comando",[timeout_s]) → salida combinada
                match action {
                    "exec" => crate::ssh::ssh_exec(self, &args),
                    _ => Err(format!("Unknown SSH action: {action}")),
                }
            }
            #[cfg(feature = "zroutines")]
            "zroutines" => {
                // ── 17-sep-2026: ZS estilo MSM — «grabar rutinas» desde M ──
                //   $DEVICE("zroutines","save",BUF,[DEST]) → routines/DEST.m + recarga
                crate::zroutines::zroutines_device(self, action, &args)
            }
            #[cfg(feature = "minreq")]
            "search" => {
                // $DEVICE("search:web", query, [n], [include_answer]) → búsqueda web
                // (endpoint estilo Tavily configurable por env, ver search_web).
                match action {
                    "web" | "call" => search_web(&args),
                    "text" => search_web_text(&args),
                    _ => Err(format!("Unknown SEARCH action: {action}")),
                }
            }
            "ddp" => {
                match action {
                    // ── F2 (14-sep-2026): DDP HTTP+HMAC contra el hub vm_api (:8081) ──
                    //   $DEVICE("ddp:health")                       → JSON de /ddp/health
                    //   $DEVICE("ddp:pull","NS",[limit],[depth])    → trae y APLICA local, devuelve nº
                    //   $DEVICE("ddp:push","NS")                    → sube el subárbol local
                    // Firma legacy ts+data+key (epoch seg): GET firma path+query; POST firma body.
                    "health" => {
                        let (peer, key) = ddp_cfg(self)?;
                        let (status, body) =
                            crate::ddp_client::get_signed(&peer, "/ddp/health", &key)?;
                        if status != 200 {
                            return Err(format!(
                                "DDP health HTTP {status}: {}",
                                body.chars().take(200).collect::<String>()
                            ));
                        }
                        Ok(Value::String(body))
                    }
                    "pull" => {
                        let ns = args.first().map(|v| v.as_string()).unwrap_or_default();
                        if ns.is_empty() {
                            return Err(
                                "uso: $DEVICE(\"ddp:pull\",\"NS\",[limit],[depth])".to_string()
                            );
                        }
                        let limit = match args.get(1).map(|v| v.as_number() as i64).unwrap_or(500) {
                            n if n > 0 => n,
                            _ => 500,
                        };
                        let depth = args.get(2).map(|v| v.as_number() as i64).unwrap_or(-1);
                        let (peer, key) = ddp_cfg(self)?;
                        let path = format!(
                            "/ddp/pull?ns={}&limit={}&depth={}",
                            crate::ddp_client::urlenc(&ns),
                            limit,
                            depth
                        );
                        let (status, body) =
                            crate::ddp_client::get_signed(&peer, &path, &key)?;
                        if status != 200 {
                            return Err(format!(
                                "DDP pull HTTP {status}: {}",
                                body.chars().take(200).collect::<String>()
                            ));
                        }
                        let parsed: serde_json::Value = serde_json::from_str(&body)
                            .map_err(|e| format!("DDP pull: JSON inválido: {e}"))?;
                        let entries = parsed
                            .get("entries")
                            .and_then(|e| e.as_array())
                            .cloned()
                            .unwrap_or_default();
                        let mut applied = 0usize;
                        let mut skipped = 0usize;
                        for e in entries {
                            let ens = e
                                .get("ns")
                                .and_then(|x| x.as_str())
                                .unwrap_or(ns.as_str())
                                .to_string();
                            let val = e
                                .get("value")
                                .and_then(|x| x.as_str())
                                .unwrap_or("")
                                .to_string();
                            if val.is_empty() {
                                skipped += 1;
                                continue;
                            }
                            let subs: Vec<Subscript> = e
                                .get("subs")
                                .and_then(|x| x.as_array())
                                .map(|arr| {
                                    arr.iter()
                                        .map(|s| {
                                            Subscript::String(
                                                s.as_str().unwrap_or("").to_string(),
                                            )
                                        })
                                        .collect()
                                })
                                .unwrap_or_default();
                            self.set(&ens, &subs, Value::String(val))
                                .map_err(|err| format!("DDP pull set: {err}"))?;
                            applied += 1;
                        }
                        Ok(Value::String(format!("{applied} (skip {skipped})")))
                    }
                    "push" => {
                        let ns = args.first().map(|v| v.as_string()).unwrap_or_default();
                        if ns.is_empty() {
                            return Err("uso: $DEVICE(\"ddp:push\",\"NS\")".to_string());
                        }
                        let (peer, key) = ddp_cfg(self)?;
                        let mut entries: Vec<serde_json::Value> = Vec::new();
                        for ((ens, subs), val) in self.values.iter() {
                            if ens != &ns {
                                continue;
                            }
                            let sv: Vec<String> = subs.iter().map(sub_text).collect();
                            entries.push(serde_json::json!({"subs": sv, "value": val.as_string()}));
                            if entries.len() >= 1000 {
                                break;
                            }
                        }
                        let body = serde_json::json!({"ns": ns.clone(), "entries": entries})
                            .to_string();
                        let (status, resp) =
                            crate::ddp_client::post_signed(&peer, "/ddp/push", &body, &key)?;
                        if status != 200 {
                            return Err(format!(
                                "DDP push HTTP {status}: {}",
                                resp.chars().take(200).collect::<String>()
                            ));
                        }
                        Ok(Value::String(resp))
                    }
                    // F2c: estado/limpieza de la caché de referencias
                    "cache" => {
                        let sub = args.first().map(|v| v.as_string()).unwrap_or_default();
                        match sub.as_str() {
                            "" | "stats" => {
                                let s = match self.remote_cache.lock() {
                                    Ok(c) => c.stats(),
                                    Err(_) => "cache bloqueada".to_string(),
                                };
                                Ok(Value::String(s))
                            }
                            "clear" => {
                                let n = match self.remote_cache.lock() {
                                    Ok(mut c) => c.clear(),
                                    Err(_) => 0,
                                };
                                Ok(Value::String(format!("cache limpiada ({n} chunks)")))
                            }
                            other => Err(format!("Unknown DDP cache action: {other}")),
                        }
                    }
                    // ── F5 (14-sep-2026): "voz prestada" ──
                    // El nodo habla con un agente del ecosistema vía el hub:
                    // POST /ddp/agent/chat (HMAC body) → el hub resuelve el
                    // agente en ^AGENTES("routing") y lo despacha (workers CF
                    // / modos de Poli).
                    //   $DEVICE("ddp:agent","slug","mensaje",[session]) → texto
                    "agent" => {
                        let slug = args.first().map(|v| v.as_string()).unwrap_or_default();
                        let msg = args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        if slug.is_empty() || msg.is_empty() {
                            return Err(
                                "uso: $DEVICE(\"ddp:agent\",\"slug\",\"mensaje\",[session])"
                                    .to_string(),
                            );
                        }
                        let session = match args.get(2).map(|v| v.as_string()) {
                            Some(s) if !s.trim().is_empty() => s,
                            _ => "mvm-nas".to_string(),
                        };
                        let (peer, key) = ddp_cfg(self)?;
                        let body = serde_json::json!({
                            "agente": slug,
                            "mensaje": msg,
                            "session": session,
                        })
                        .to_string();
                        let (status, resp) = crate::ddp_client::post_signed_llm(
                            &peer,
                            "/ddp/agent/chat",
                            &body,
                            &key,
                        )?;
                        if status != 200 {
                            return Err(format!(
                                "DDP agent HTTP {status}: {}",
                                resp.chars().take(220).collect::<String>()
                            ));
                        }
                        let parsed: serde_json::Value = serde_json::from_str(&resp)
                            .map_err(|e| format!("DDP agent: JSON inválido: {e}"))?;
                        let ok = parsed
                            .get("success")
                            .and_then(|v| v.as_bool())
                            .unwrap_or(false);
                        if !ok {
                            let err = parsed
                                .get("error")
                                .and_then(|v| v.as_str())
                                .unwrap_or(resp.as_str());
                            return Err(format!(
                                "DDP agent: {}",
                                err.chars().take(220).collect::<String>()
                            ));
                        }
                        let text = parsed
                            .get("response")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string();
                        Ok(Value::String(text))
                    }
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
            "mcp" => {
                // Device MCP NATIVO — first-class en el MVM (2026-09-09).
                // Las rutinas M hablan con servidores MCP (JSON-RPC 2.0)
                // registrados en la PDB: ^SYS("MCP",<server>,url[|type|headers]).
                //   $DEVICE("mcp:list")                          → servers registrados
                //   $DEVICE("mcp:ping", server)                  → initialize
                //   $DEVICE("mcp:tools", server)                 → tools/list
                //   $DEVICE("mcp:call", server, tool, json_args) → tools/call
                if action == "list" {
                    let mut servers: Vec<String> = Vec::new();
                    let mut cursor: Option<Subscript> = None;
                    loop {
                        match self.order("SYS", &[Subscript::String("MCP".into())], cursor.as_ref(), 1) {
                            Ok(Some(sub)) => {
                                if let Subscript::String(name) = &sub {
                                    let url = match self.get("SYS", &[
                                        Subscript::String("MCP".into()),
                                        Subscript::String(name.clone()),
                                        Subscript::String("url".into()),
                                    ]) {
                                        Ok(Some(Value::String(u))) => u.clone(),
                                        _ => String::new(),
                                    };
                                    let tipo = match self.get("SYS", &[
                                        Subscript::String("MCP".into()),
                                        Subscript::String(name.clone()),
                                        Subscript::String("type".into()),
                                    ]) {
                                        Ok(Some(Value::String(t))) => t.clone(),
                                        _ => "http".to_string(),
                                    };
                                    let has_hmac = match self.get("SYS", &[
                                        Subscript::String("MCP".into()),
                                        Subscript::String(name.clone()),
                                        Subscript::String("hmac_key".into()),
                                    ]) {
                                        Ok(Some(Value::String(k))) => !k.is_empty(),
                                        _ => false,
                                    };
                                    let has_auth = match self.get("SYS", &[
                                        Subscript::String("MCP".into()),
                                        Subscript::String(name.clone()),
                                        Subscript::String("auth".into()),
                                    ]) {
                                        Ok(Some(Value::String(a))) => !a.is_empty(),
                                        _ => false,
                                    };
                                    servers.push(serde_json::json!({
                                        "server": name, "url": url, "type": tipo,
                                        "hmac": has_hmac, "auth": has_auth
                                    }).to_string());
                                }
                                cursor = Some(sub);
                            }
                            Ok(None) => break,
                            Err(_) => break,
                        }
                    }
                    return Ok(Value::String(
                        serde_json::json!({"ok": true, "servers": servers}).to_string()
                    ));
                }
                let server = args.get(0).map(|v| v.as_string()).unwrap_or_default();
                if server.trim().is_empty() {
                    return Err("MCP: server requerido (registro ^SYS(\"MCP\",server,url))".to_string());
                }
                let url = match self.get("SYS", &[
                    Subscript::String("MCP".into()),
                    Subscript::String(server.clone()),
                    Subscript::String("url".into()),
                ]) {
                    Ok(Some(Value::String(u))) if !u.trim().is_empty() => u.clone(),
                    _ => return Err(format!("MCP: server '{server}' no registrado en ^SYS(\"MCP\")")),
                };
                let hmac_key = match self.get("SYS", &[
                    Subscript::String("MCP".into()),
                    Subscript::String(server.clone()),
                    Subscript::String("hmac_key".into()),
                ]) {
                    Ok(Some(Value::String(k))) => k.clone(),
                    _ => String::new(),
                };
                let auth = match self.get("SYS", &[
                    Subscript::String("MCP".into()),
                    Subscript::String(server.clone()),
                    Subscript::String("auth".into()),
                ]) {
                    Ok(Some(Value::String(a))) => a.clone(),
                    _ => String::new(),
                };
                let extra: Vec<(String, String)> = match self.get("SYS", &[
                    Subscript::String("MCP".into()),
                    Subscript::String(server.clone()),
                    Subscript::String("headers".into()),
                ]) {
                    Ok(Some(Value::String(h))) => serde_json::from_str::<serde_json::Value>(&h)
                        .ok()
                        .and_then(|v| v.as_object().cloned())
                        .map(|obj| obj.into_iter().filter_map(|(k, v)| {
                            v.as_str().map(|sv| (k, sv.to_string()))
                        }).collect::<Vec<_>>())
                        .unwrap_or_default(),
                    _ => Vec::new(),
                };
                match action {
                    "call" => {
                        let tool = args.get(1).map(|v| v.as_string()).unwrap_or_default();
                        if tool.trim().is_empty() {
                            return Err("MCP call: tool requerida".to_string());
                        }
                        let args_json = args.get(2).map(|v| v.as_string()).unwrap_or_default();
                        let parsed: serde_json::Value = if args_json.trim().is_empty() {
                            serde_json::Value::Object(Default::default())
                        } else {
                            serde_json::from_str(&args_json)
                                .map_err(|e| format!("MCP call: args_json invalido: {e}"))?
                        };
                        mcp_http_request(
                            &url, "tools/call",
                            &serde_json::json!({"name": tool, "arguments": parsed}),
                            &hmac_key, &auth, &extra,
                        )
                    }
                    "tools" => mcp_http_request(&url, "tools/list", &serde_json::json!({}), &hmac_key, &auth, &extra),
                    "ping" => mcp_http_request(&url, "initialize", &serde_json::json!({
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "clientInfo": {"name": "lumen-m-light", "version": "0.1.0"},
                    }), &hmac_key, &auth, &extra),
                    _ => Err(format!("Unknown MCP action: {action} (list|ping|tools|call)")),
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
        
        let build = || {
            let mut req = minreq::post(url)
                .with_header("Content-Type", "application/json")
                .with_timeout(120)
                .with_body(body_str.clone());
            if is_anthropic {
                req = req.with_header("x-api-key", &api_key)
                         .with_header("anthropic-version", "2023-06-01");
            } else {
                req = req.with_header("Authorization", &format!("Bearer {api_key}"));
            }
            req
        };
        let resp = minreq_send_retry(build)
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

/// Codificar un Subscript al formato MUMPS CANÓNICO del ecosistema
/// (qpdb.py / poli_server): String → \x02 <utf8> \xff ; Number → \x01 <f64 BE 8B> ;
/// terminator final \xff. (Fix 2026-09-04: antes los números se codificaban como
/// \x01 + texto ASCII → incompatible con qpdb/Python en ambas direcciones.)
fn encode_one_sub(sub: &Subscript) -> Vec<u8> {
    let mut out = Vec::new();
    match sub {
        Subscript::Number(v) => {
            out.push(0x01);
            out.extend_from_slice(&v.to_be_bytes());
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
    // Terminador final OBLIGATORIO del formato canónico (qpdb/poli lo escriben
    // con él). Fix 2026-09-05: sin él, las escrituras del MVM creaban subkeys
    // distintas a las de qpdb (misma clave lógica, bytes sin \xff final) →
    // duplicados en _globals por cada SET del preámbulo.
    out.push(0xFF);
    out
}

/// Decodificar subkey binaria canónica a Subscripts TIPADOS.
/// Formato: \x02 <str> \xff (string → Subscript::String, SIEMPRE string) ·
/// \x01 <f64 BE 8B> (número → Subscript::Number) · \xff suelto = terminador.
/// Legacy: \x01 + texto ASCII + \xff → Number si parsea como número, String si no.
/// Bytes desconocidos se leen como string hasta \xff (tolerancia con filas legacy).
/// Fix 2026-09-10 (bug tipos string/número): antes la salida era Vec<String> y
/// TODOS los subscripts string-numéricos se re-normalizaban con parse::<f64> al
/// insertarse → las filas escritas con subscript string "1" quedaban invisibles
/// para ^G("1") tras un reload (y colisionaban con ^G(1)).
fn decode_subkey(subkey: &[u8]) -> Vec<Subscript> {
    let mut result = Vec::new();
    let mut i = 0;
    while i < subkey.len() {
        match subkey[i] {
            0x01 => {
                if i + 9 <= subkey.len() {
                    let eight = &subkey[i + 1..i + 9];
                    if eight.contains(&0xFF) {
                        // Legacy lumen-m-light: \x01 + texto ASCII + \xff (los f64
                        // canonicos de enteros/indices nunca contienen 0xFF).
                        let end = subkey[i + 1..]
                            .iter()
                            .position(|&b| b == 0xFF)
                            .map(|p| i + 1 + p)
                            .unwrap_or(subkey.len());
                        let txt = String::from_utf8_lossy(&subkey[i + 1..end]).to_string();
                        result.push(if let Ok(n) = txt.parse::<f64>() {
                            Subscript::Number(n)
                        } else {
                            Subscript::String(txt)
                        });
                        i = end + 1;
                    } else {
                        let mut bytes = [0u8; 8];
                        bytes.copy_from_slice(eight);
                        result.push(Subscript::Number(f64::from_be_bytes(bytes)));
                        i += 9;
                    }
                } else {
                    i += 1;
                }
            }
            0x02 | 0x00 => {
                i += 1;
                let end = subkey[i..]
                    .iter()
                    .position(|&b| b == 0xFF)
                    .map(|p| i + p)
                    .unwrap_or(subkey.len());
                result.push(Subscript::String(
                    String::from_utf8_lossy(&subkey[i..end]).to_string(),
                ));
                i = end + 1;
            }
            0xFF => i += 1, // terminador
            _ => {
                // legacy/desconocido: chunk como string hasta \xff (comportamiento previo)
                let end = subkey[i..]
                    .iter()
                    .position(|&b| b == 0xFF)
                    .map(|p| i + p)
                    .unwrap_or(subkey.len());
                result.push(Subscript::String(
                    String::from_utf8_lossy(&subkey[i..end]).to_string(),
                ));
                i = end + 1;
            }
        }
    }
    result
}

/// Extraer el primer subscript de una subkey binaria.
fn decode_first_sub(subkey: &[u8]) -> Option<Subscript> {
    decode_subkey(subkey).into_iter().next()
}

/// Extraer el subscript en un nivel especifico de una subkey.
fn extract_sub_at_level(subkey: &[u8], level: usize) -> Option<Subscript> {
    decode_subkey(subkey).get(level).cloned()
}

impl std::fmt::Debug for MemoryHost {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        f.debug_struct("MemoryHost")
            .field("values", &self.values.len())
            .field("has_sqlite", &self.is_sqlite())
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
            live_stdin: self.live_stdin,
            locks: self.locks.clone(),
            llm_api_keys: self.llm_api_keys.clone(),
            sandbox: self.sandbox,
            #[cfg(feature = "sqlite")]
            sqlite_db: None, // SQLite connections can't be cloned
            smith_registry: self.smith_registry.clone(),
            remote_cache: std::sync::Mutex::new(RemoteCache::default()), // caché no se clona
        }
    }
}

#[cfg(test)]
mod subkey_codec_tests {
    use super::*;

    /// Fix 2026-09-10: string "1" y número 1 son subscripts DISTINTOS — el decode
    /// no debe normalizar string→number (bug: filas con subscript string quedaban
    /// invisibles tras un reload del host SQLite).
    #[test]
    fn roundtrip_preserva_tipo_string_vs_number() {
        let subs = vec![
            Subscript::String("a".into()),
            Subscript::String("1".into()),
            Subscript::Number(1.0),
            Subscript::String("x".into()),
        ];
        let blob = encode_subkey(&subs);
        let decoded = decode_subkey(&blob);
        assert_eq!(decoded.len(), 4);
        assert!(matches!(&decoded[0], Subscript::String(s) if s == "a"));
        assert!(
            matches!(&decoded[1], Subscript::String(s) if s == "1"),
            "string 1 debe seguir siendo String, no re-normalizarse a Number"
        );
        assert!(
            matches!(&decoded[2], Subscript::Number(n) if (*n - 1.0).abs() < 1e-9),
            "número 1 debe seguir siendo Number"
        );
        assert!(matches!(&decoded[3], Subscript::String(s) if s == "x"));
    }

    #[test]
    fn string_numerico_y_numero_codifican_distinto() {
        let s_blob = encode_subkey(&[Subscript::String("1".into())]);
        let n_blob = encode_subkey(&[Subscript::Number(1.0)]);
        assert_ne!(s_blob, n_blob, "string y número deben codificar distinto");
        let s_dec = decode_subkey(&s_blob);
        let n_dec = decode_subkey(&n_blob);
        assert!(matches!(s_dec[0], Subscript::String(_)));
        assert!(matches!(n_dec[0], Subscript::Number(_)));
    }

    /// El prefijo de descendientes va SIN el terminador \xff final — base del
    /// fix del KILL de subárbol (substr prefix match sobre BLOB).
    #[test]
    fn prefijo_descendientes_sin_terminador_final() {
        let full = encode_subkey(&[Subscript::String("a".into()), Subscript::String("1".into())]);
        let prefix: Vec<u8> = [Subscript::String("a".into()), Subscript::String("1".into())]
            .iter()
            .flat_map(|s| encode_one_sub(s))
            .collect();
        // El subkey completo = prefijo + terminador
        assert_eq!(full[..full.len() - 1], prefix[..]);
        // Un descendiente empieza por el prefijo
        let child = encode_subkey(&[
            Subscript::String("a".into()),
            Subscript::String("1".into()),
            Subscript::String("x".into()),
        ]);
        assert_eq!(&child[..prefix.len()], &prefix[..]);
    }
}
