mod ffi;
mod host;
mod device8;
mod device9;
mod native_host;
mod llm_engine;
mod prompt_builder;
mod response_parser;

mod tool_dispatch;
mod agent_loop;

use host::{CallbackBridge, LiveHost};
// use native_host::NativeHost; // S1: pending integration in JobActor
use llm_engine::LlmEngine;
use prompt_builder::PromptBuilder;
use response_parser::{ResponseParser, AgentAction};
use tool_dispatch::ToolDispatcher;
use lumen_mlight::{Compiler, Execution, Host, Program, Vm, VmState};
use serde::{Deserialize, Serialize};
use serde_json::{json, Value as JsonValue};
use std::collections::{BTreeMap, VecDeque};
use std::sync::mpsc as std_mpsc;
use std::sync::Arc;
use std::thread;
use std::time::{SystemTime, UNIX_EPOCH};
use tokio::sync::{mpsc, oneshot};
use tokio::task::LocalSet;
use tokio::time::{sleep, Duration};

pub use ffi::*;
pub use host::HostCallback;

const READY: &str = "READY";
const RUNNING: &str = "RUNNING";
const WAITING: &str = "WAITING";
const BLOCKED: &str = "BLOCKED";
const HIBERNATE: &str = "HIBERNATE";
const DEAD: &str = "DEAD";

fn now() -> f64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs_f64()
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct JobSnapshot {
    pub pid: i64,
    pub name: String,
    pub source: String,
    pub owner: String,
    pub status: String,
    pub program: Program,
    pub vm_state: VmState,
    pub created_at: f64,
    pub last_run: f64,
    #[serde(default)]
    pub error: String,
    #[serde(default)]
    pub mailbox: VecDeque<MailboxMessage>,
    #[serde(default)]
    pub wake_at: Option<f64>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MailboxMessage {
    pub id: String,
    pub content: JsonValue,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct CronEntry {
    pub name: String,
    pub interval: f64,
    pub action: String,
    #[serde(default = "default_true")]
    pub enabled: bool,
    #[serde(default)]
    pub last_run: f64,
    #[serde(default = "now")]
    pub created: f64,
    #[serde(default)]
    generation: u64,
}

fn default_true() -> bool {
    true
}

#[derive(Debug, Clone, Serialize)]
pub struct JobInfo {
    pub pid: i64,
    pub name: String,
    pub status: String,
    pub pc: usize,
    pub io_device: i64,
    pub age_secs: f64,
    pub last_run_secs: f64,
    pub vars: usize,
    pub owner: String,
    pub error: String,
    pub gas_limit: u64,
    pub gas_total: u64,
}

impl JobSnapshot {
    fn info(&self) -> JobInfo {
        JobInfo {
            pid: self.pid,
            name: self.name.clone(),
            status: self.status.clone(),
            pc: self.vm_state.ip,
            io_device: self.vm_state.current_io,
            age_secs: (now() - self.created_at).max(0.0),
            last_run_secs: (now() - self.last_run).max(0.0),
            vars: self.vm_state.vars.len(),
            owner: self.owner.clone(),
            error: self.error.clone(),
            gas_limit: self.vm_state.gas_limit,
            gas_total: self.vm_state.gas_used,
        }
    }
}

enum JobCommand {
    Tick {
        gas: u64,
        reply: oneshot::Sender<Result<JobSnapshot, String>>,
    },
    Send {
        message: MailboxMessage,
        reply: oneshot::Sender<Result<JobSnapshot, String>>,
    },
    ReadMailbox {
        reply: oneshot::Sender<Result<(Vec<MailboxMessage>, JobSnapshot), String>>,
    },
    Sleep {
        seconds: f64,
        reply: oneshot::Sender<Result<JobSnapshot, String>>,
    },
    Wake {
        reply: Option<oneshot::Sender<Result<JobSnapshot, String>>>,
    },
    Kill {
        reply: oneshot::Sender<Result<JobSnapshot, String>>,
    },
    Snapshot {
        reply: oneshot::Sender<Result<JobSnapshot, String>>,
    },
}

async fn job_actor(
    mut snapshot: JobSnapshot,
    bridge: CallbackBridge,
    engine: Option<Arc<dyn LlmEngine>>,
    tool_dispatch: Option<Arc<ToolDispatcher>>,
    mut rx: mpsc::Receiver<JobCommand>,
) {
    let mut host = LiveHost::new(bridge, snapshot.pid);
    while let Some(command) = rx.recv().await {
        match command {
            JobCommand::Tick { gas, reply } => {
                if snapshot.status == READY || snapshot.status == BLOCKED {
                    snapshot.status = RUNNING.to_string();
                    snapshot.last_run = now();
                    host.empty_read = false;
                    host.lock_blocked = false;
                    while let Some(message) = snapshot.mailbox.pop_front() {
                        host.push_input(match message.content {
                            JsonValue::String(value) => value,
                            other => other.to_string(),
                        });
                    }
                    let execution = match Vm::resume(
                        snapshot.program.clone(),
                        snapshot.vm_state.clone(),
                        &mut host,
                    ) {
                        Ok(mut vm) => {
                            // S2: THINK_INTERNAL hook — intercept before run_slice
                            let think_hook = snapshot.program.labels.contains_key("THINK_INTERNAL");
                            let execution = if think_hook && engine.is_some() {
                                let engine = engine.as_ref().unwrap();
                                let builder = PromptBuilder::new(snapshot.pid, snapshot.vm_state.gas_used);
                                match builder.build(&host) {
                                    Ok((system, user)) => {
                                        // Dispatch think (non-blocking via oneshot)
                                        let (tx, mut rx) = tokio::sync::oneshot::channel();
                                        let engine_clone = engine.clone();
                                        let sys = system.clone();
                                        let usr = user.clone();
                                        tokio::spawn(async move {
                                            match engine_clone.think(&sys, &usr).await {
                                                Ok(response) => { let _ = tx.send(Ok(response)); }
                                                Err(e) => { let _ = tx.send(Err(e)); }
                                            }
                                        });
                                        // Check if response ready (non-blocking)
                                        match rx.try_recv() {
                                            Ok(Ok(response)) => {
                                                let parsed = ResponseParser::parse(&response);
                                                for action in &parsed.actions {
                                                    match action {
                                                        AgentAction::MCode { code } => {
                                                            // Store for next tick
                                                            let _ = host.set("MEMORY", &[
                                                                lumen_mlight::Subscript::String("self".into()),
                                                                lumen_mlight::Subscript::Number(snapshot.pid as f64),
                                                                lumen_mlight::Subscript::String("pending_mcode".into()),
                                                            ], lumen_mlight::Value::String(code.clone()));
                                                        }
                                                        AgentAction::ToolCall { tool, args } => {
                                                            // Dispatch via SHM (non-blocking)
                                                            if let Some(ref dispatcher) = tool_dispatch {
                                                                let req = tool_dispatch::ToolRequest {
                                                                    tool: tool.clone(),
                                                                    args: args.clone(),
                                                                };
                                                                let dispatcher_clone = dispatcher.clone();
                                                                let tool_clone = tool.clone();
                                                                tokio::spawn(async move {
                                                                    match dispatcher_clone.dispatch(req).await {
                                                                        Ok(resp) => {
                                                                            // resultado se cachea en el dispatcher
                                                                            let _ = resp;
                                                                        }
                                                                        Err(e) => {
                                                                            eprintln!("Tool dispatch error: {}", e);
                                                                        }
                                                                    }
                                                                });
                                                            }
                                                            // Store pending for next tick
                                                            let _ = host.set("RESULT", &[
                                                                lumen_mlight::Subscript::String(tool.clone()),
                                                            ], lumen_mlight::Value::String(args.to_string()));
                                                        }
                                                        AgentAction::SendMessage { target, content } => {
                                                            // Enqueue to mailbox
                                                            let _ = host.set("MAILBOX", &[
                                                                lumen_mlight::Subscript::String(target.clone()),
                                                                lumen_mlight::Subscript::String(format!("msg_{}", snapshot.vm_state.gas_used)),
                                                            ], lumen_mlight::Value::String(content.clone()));
                                                        }
                                                        AgentAction::Output { text } => {
                                                            let _ = host.set("OUTPUT", &[
                                                                lumen_mlight::Subscript::Number(snapshot.pid as f64),
                                                            ], lumen_mlight::Value::String(text.clone()));
                                                        }
                                                    }
                                                }
                                                if parsed.actions.is_empty() {
                                                    Execution::Yielded
                                                } else {
                                                    Execution::Yielded // actions execute next tick
                                                }
                                            }
                                            Ok(Err(_)) => Execution::Yielded, // LLM error, retry next tick
                                            Err(_) => Execution::Yielded, // still waiting for response
                                        }
                                    }
                                    Err(_) => Execution::Yielded,
                                }
                            } else {
                                let execution = vm.run_slice(gas.max(1));
                                snapshot.vm_state = vm.state;
                                execution
                            };
                            // S1: Device 8/9 — dispatch HTTP/webhook on OPEN
                            if snapshot.vm_state.last_open_device == 7 {
                                // K3: Device 7 — LLM nativo
                                let args = snapshot.vm_state.last_open_args.clone();
                                if let Some(colon) = args.find(':') {
                                    host.llm_model = Some(args[colon+1..].trim().to_string());
                                }
                                snapshot.vm_state.last_open_device = 0;
                            }
                            // Original Device 8 dispatch
                            if snapshot.vm_state.last_open_device == 8 {
                                let url = snapshot.vm_state.last_open_args.clone();
                                if let Some(colon) = url.find(':') {
                                    let http_url = url[colon+1..].trim().to_string();
                                    if !http_url.is_empty() {
                                        // Use a oneshot channel to receive the HTTP response
                                        let (tx, mut rx) = tokio::sync::oneshot::channel();
                                        tokio::spawn(async move {
                                            match reqwest::get(&http_url).await {
                                                Ok(resp) => {
                                                    match resp.text().await {
                                                        Ok(body) => { let _ = tx.send(Ok(body)); }
                                                        Err(e) => { let _ = tx.send(Err(e.to_string())); }
                                                    }
                                                }
                                                Err(e) => { let _ = tx.send(Err(e.to_string())); }
                                            }
                                        });
                                        // Check if response is ready (non-blocking)
                                        host.http_rx = Some(rx);
                                    }
                                }
                                snapshot.vm_state.last_open_device = 0;
                                host.empty_read = true; // job waits for HTTP response
                            }
                            // Check pending HTTP response
                            if let Some(ref mut rx) = host.http_rx {
                                if let Ok(Ok(body)) = rx.try_recv() {
                                    let mut buf = VecDeque::new();
                                    for line in body.lines() {
                                        buf.push_back(line.to_string());
                                    }
                                    host.http_buffer = Some(buf);
                                    host.empty_read = false;
                                    host.http_rx = None;
                                }
                            }
                            // K3: Device 7 — flush WRITE output to LLM engine
                            if snapshot.vm_state.current_io == 7 && !snapshot.vm_state.output.is_empty() {
                                let prompt = snapshot.vm_state.output.clone();
                                snapshot.vm_state.output.clear();
                                if let Some(ref engine) = host.llm_engine {
                                    let engine = engine.clone();
                                    let (tx, mut rx) = tokio::sync::oneshot::channel();
                                    let sys = format!("Eres un agente MUMPS ejecutando en LUMEN. Job {}. Modelo: {}",
                                        snapshot.pid, host.llm_model.as_deref().unwrap_or("default"));
                                    tokio::spawn(async move {
                                        match engine.think(&sys, &prompt).await {
                                            Ok(response) => { let _ = tx.send(Ok(response)); }
                                            Err(e) => { let _ = tx.send(Err(e)); }
                                        }
                                    });
                                    // Non-blocking: check response next tick
                                    if let Ok(Ok(response)) = rx.try_recv() {
                                        host.llm_response = Some(response);
                                        host.empty_read = false;
                                    } else {
                                        host.empty_read = true; // wait for LLM
                                    }
                                }
                            }
                            // K5: Device 10 — flush WRITE to ToolDispatcher
                            if snapshot.vm_state.current_io == 10 && !snapshot.vm_state.output.is_empty() {
                                let tool_json = snapshot.vm_state.output.clone();
                                snapshot.vm_state.output.clear();
                                if let Some(ref dispatcher) = host.tool_dispatcher {
                                    if let Ok(req) = serde_json::from_str::<crate::tool_dispatch::ToolRequest>(&tool_json) {
                                        let dispatcher = dispatcher.clone();
                                        let (tx, mut rx) = tokio::sync::oneshot::channel();
                                        tokio::spawn(async move {
                                            match dispatcher.dispatch(req).await {
                                                Ok(resp) => { let _ = tx.send(resp.result); }
                                                Err(e) => { let _ = tx.send(e); }
                                            }
                                        });
                                        if let Ok(result) = rx.try_recv() {
                                            host.tool_result = Some(result);
                                            host.empty_read = false;
                                        } else {
                                            host.empty_read = true;
                                        }
                                    }
                                }
                            }
                            // K5: Device 10 — read tool result
                            if snapshot.vm_state.current_io == 10 {
                                if let Some(ref result) = host.tool_result {
                                    host.push_input(result.clone());
                                    host.tool_result = None;
                                    host.empty_read = false;
                                }
                            }
                            // K3: Device 7 LLM response check
                            if snapshot.vm_state.current_io == 7 {
                                if let Some(ref resp) = host.llm_response {
                                    host.push_input(resp.clone());
                                    host.llm_response = None;
                                    host.empty_read = false;
                                }
                            }
                            // Device 8 read buffers (fallback check)
                            if snapshot.vm_state.current_io == 8 {
                                if let Some(ref buf) = host.http_buffer {
                                    if !buf.is_empty() {
                                        host.empty_read = false;
                                    }
                                }
                            }
                            if snapshot.vm_state.current_io == 9 {
                                if let Some(ref queue) = host.webhook_queue {
                                    if let Ok(mut guard) = queue.try_lock() {
                                        if !guard.is_empty() {
                                            host.empty_read = false;
                                        }
                                    }
                                }
                            }
                            execution
                        }
                        Err(error) => {
                            snapshot.error = error.zerror;
                            Execution::Error
                        }
                    };
                    snapshot.error = snapshot
                        .vm_state
                        .error
                        .as_ref()
                        .map(|error| error.zerror.clone())
                        .unwrap_or_else(|| snapshot.error.clone());
                    snapshot.status = match execution {
                        _ if host.empty_read => {
                            // S3: WAITING with back-off — retry after 100ms
                            snapshot.wake_at = Some(now() + 0.1);
                            WAITING
                        }
                        _ if host.lock_blocked => BLOCKED,
                        Execution::Yielded => READY,
                        Execution::Completed | Execution::Halted | Execution::Error => DEAD,
                    }
                    .to_string();
                    if snapshot.status == DEAD {
                        // Un job muerto nunca libera por sí mismo: soltar sus locks.
                        let _ = host.unlock_all();
                    }
                    let persisted = persist(&host, &snapshot);
                    let _ = reply.send(persisted.map(|_| snapshot.clone()));
                } else {
                    let _ = reply.send(Ok(snapshot.clone()));
                }
            }
            JobCommand::Send { message, reply } => {
                snapshot.mailbox.push_back(message.clone());
                if snapshot.status == WAITING {
                    snapshot.status = READY.to_string();
                }
                let persisted = persist_message(&host, &snapshot, &message);
                let _ = reply.send(persisted.map(|_| snapshot.clone()));
            }
            JobCommand::ReadMailbox { reply } => {
                let messages = snapshot.mailbox.drain(..).collect();
                let persisted = persist(&host, &snapshot);
                let _ = reply.send(persisted.map(|_| (messages, snapshot.clone())));
            }
            JobCommand::Sleep { seconds, reply } => {
                snapshot.status = HIBERNATE.to_string();
                snapshot.wake_at = Some(now() + seconds.max(0.0));
                let persisted = persist(&host, &snapshot);
                let _ = reply.send(persisted.map(|_| snapshot.clone()));
            }
            JobCommand::Wake { reply } => {
                if snapshot.status == HIBERNATE || snapshot.status == WAITING {
                    snapshot.status = READY.to_string();
                }
                snapshot.wake_at = None;
                let persisted = persist(&host, &snapshot);
                if let Some(reply) = reply {
                    let _ = reply.send(persisted.map(|_| snapshot.clone()));
                }
            }
            JobCommand::Kill { reply } => {
                snapshot.status = DEAD.to_string();
                snapshot.wake_at = None;
                let _ = host.unlock_all();
                let persisted = persist(&host, &snapshot);
                let _ = reply.send(persisted.map(|_| snapshot.clone()));
            }
            JobCommand::Snapshot { reply } => {
                let _ = reply.send(Ok(snapshot.clone()));
            }
        }
    }
}

fn persist(host: &LiveHost, snapshot: &JobSnapshot) -> Result<(), String> {
    host.bridge
        .call("persist_job", serde_json::to_value(snapshot).unwrap())?;
    Ok(())
}

fn persist_message(
    host: &LiveHost,
    snapshot: &JobSnapshot,
    message: &MailboxMessage,
) -> Result<(), String> {
    host.bridge.call(
        "persist_message",
        json!({"snapshot": snapshot, "message": message}),
    )?;
    Ok(())
}

struct JobHandle {
    tx: mpsc::Sender<JobCommand>,
    snapshot: JobSnapshot,
}

enum SchedulerCommand {
    Call(JsonValue, std_mpsc::Sender<JsonValue>),
    CronFire(String, u64),
    WakeJob(i64),
    Shutdown(std_mpsc::Sender<()>),
}

pub struct TokioMvm {
    tx: mpsc::UnboundedSender<SchedulerCommand>,
    worker: Option<thread::JoinHandle<()>>,
}

impl TokioMvm {
    pub fn start(bridge: CallbackBridge) -> Result<Self, String> {
        let (tx, rx) = mpsc::unbounded_channel();
        let scheduler_tx = tx.clone();
        let (ready_tx, ready_rx) = std_mpsc::channel();
        let worker = thread::Builder::new()
            .name("lumen-mvm-tokio".to_string())
            .spawn(move || {
                let runtime = tokio::runtime::Builder::new_current_thread()
                    .enable_time()
                    .build()
                    .expect("Tokio runtime");
                let local = LocalSet::new();
                local.block_on(&runtime, async move {
                    let mut scheduler = Scheduler::new(bridge, None, scheduler_tx).await;
                    let _ = ready_tx.send(());
                    scheduler.run(rx).await;
                });
            })
            .map_err(|error| error.to_string())?;
        ready_rx.recv().map_err(|error| error.to_string())?;
        Ok(Self {
            tx,
            worker: Some(worker),
        })
    }

    pub fn call(&self, request: JsonValue) -> Result<JsonValue, String> {
        let (reply_tx, reply_rx) = std_mpsc::channel();
        self.tx
            .send(SchedulerCommand::Call(request, reply_tx))
            .map_err(|_| "MVM scheduler stopped".to_string())?;
        reply_rx.recv().map_err(|error| error.to_string())
    }
}

impl Drop for TokioMvm {
    fn drop(&mut self) {
        let (reply_tx, reply_rx) = std_mpsc::channel();
        let _ = self.tx.send(SchedulerCommand::Shutdown(reply_tx));
        let _ = reply_rx.recv_timeout(std::time::Duration::from_secs(2));
        if let Some(worker) = self.worker.take() {
            let _ = worker.join();
        }
    }
}

struct Scheduler {
    bridge: CallbackBridge,
    engine: Option<Arc<dyn LlmEngine>>,
    tool_dispatch: Option<Arc<ToolDispatcher>>,
    command_tx: mpsc::UnboundedSender<SchedulerCommand>,
    jobs: BTreeMap<i64, JobHandle>,
    cron: BTreeMap<String, CronEntry>,
    message_seq: u64,
}

impl Scheduler {
    async fn new(
        bridge: CallbackBridge,
        engine: Option<Arc<dyn LlmEngine>>,
        command_tx: mpsc::UnboundedSender<SchedulerCommand>,
    ) -> Self {
        let mut scheduler = Self {
            bridge,
            engine,
            tool_dispatch: None, // S3: pending MCP bridge integration
            command_tx,
            jobs: BTreeMap::new(),
            cron: BTreeMap::new(),
            message_seq: 0,
        };
        if let Ok(response) = bridge.call("load_jobs", json!({})) {
            if let Some(jobs) = response.get("jobs").and_then(JsonValue::as_array) {
                for value in jobs {
                    if let Ok(snapshot) = serde_json::from_value::<JobSnapshot>(value.clone()) {
                        scheduler.insert_job(snapshot).await;
                    }
                }
            }
        }
        if let Ok(response) = bridge.call("load_cron", json!({})) {
            if let Some(entries) = response.get("entries").and_then(JsonValue::as_array) {
                for value in entries {
                    if let Ok(mut entry) = serde_json::from_value::<CronEntry>(value.clone()) {
                        entry.generation = entry.generation.max(1);
                        scheduler.schedule_cron(&entry);
                        scheduler.cron.insert(entry.name.clone(), entry);
                    }
                }
            }
        }
        scheduler
    }

    async fn insert_job(&mut self, snapshot: JobSnapshot) {
        let pid = snapshot.pid;
        let (tx, rx) = mpsc::channel(64);
        tokio::task::spawn_local(job_actor(snapshot.clone(), self.bridge, self.engine.clone(), self.tool_dispatch.clone(), rx));
        if let Some(wake_at) = snapshot.wake_at {
            let remaining = (wake_at - now()).max(0.0);
            let command_tx = self.command_tx.clone();
            tokio::task::spawn_local(async move {
                sleep(Duration::from_secs_f64(remaining)).await;
                let _ = command_tx.send(SchedulerCommand::WakeJob(pid));
            });
        }
        self.jobs.insert(pid, JobHandle { tx, snapshot });
    }

    async fn run(&mut self, mut rx: mpsc::UnboundedReceiver<SchedulerCommand>) {
        while let Some(command) = rx.recv().await {
            match command {
                SchedulerCommand::Call(request, reply) => {
                    let response = self
                        .handle(request)
                        .await
                        .unwrap_or_else(|error| json!({"success": false, "error": error}));
                    let _ = reply.send(response);
                }
                SchedulerCommand::CronFire(name, generation) => {
                    let _ = self.fire_cron(&name, generation).await;
                }
                SchedulerCommand::WakeJob(pid) => {
                    let _ = self.wake_pid(pid).await;
                }
                SchedulerCommand::Shutdown(reply) => {
                    let _ = reply.send(());
                    break;
                }
            }
        }
    }

    async fn handle(&mut self, request: JsonValue) -> Result<JsonValue, String> {
        let op = request
            .get("op")
            .and_then(JsonValue::as_str)
            .unwrap_or_default();
        let args = request.get("args").cloned().unwrap_or_else(|| json!({}));
        match op {
            "spawn" => self.spawn(args).await,
            "tick" | "tick_all" => self.tick_all(args).await,
            "list" => {
                Ok(json!({"success": true, "processes": self.infos(), "count": self.jobs.len()}))
            }
            "kill" => self.kill(args).await,
            "mailbox_send" => self.mailbox_send(args).await,
            "mailbox_read" => self.mailbox_read(args).await,
            "sleep" => self.sleep_job(args).await,
            "wake" => self.wake(args).await,
            "export" => self.export(args).await,
            "import" => self.import(args).await,
            "cron_add" => self.cron_add(args),
            "cron_remove" => self.cron_remove(args),
            "cron_list" => {
                Ok(json!({"success": true, "entries": self.cron.values().collect::<Vec<_>>() }))
            }
            _ => Err(format!("unknown MVM operation: {op}")),
        }
    }

    fn infos(&self) -> Vec<JobInfo> {
        self.jobs.values().map(|job| job.snapshot.info()).collect()
    }

    async fn spawn(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let source = args
            .get("code")
            .and_then(JsonValue::as_str)
            .unwrap_or_default()
            .to_string();
        let program = Compiler::compile(&source)?;
        let pid_response = self.bridge.call("allocate_pid", json!({}))?;
        let pid = pid_response
            .get("pid")
            .and_then(JsonValue::as_i64)
            .ok_or("allocate_pid returned no pid")?;
        let mut vm_state = VmState::new(&program);
        vm_state.job_id = pid;
        vm_state.gas_limit = args
            .get("gas_limit")
            .and_then(JsonValue::as_u64)
            .unwrap_or(1000)
            .max(1);
        vm_state.gas_budget = args
            .get("gas_budget")
            .and_then(JsonValue::as_u64)
            .unwrap_or(0);
        let snapshot = JobSnapshot {
            pid,
            name: args
                .get("name")
                .and_then(JsonValue::as_str)
                .filter(|v| !v.is_empty())
                .unwrap_or("job")
                .to_string(),
            source,
            owner: args
                .get("owner")
                .and_then(JsonValue::as_str)
                .unwrap_or_default()
                .to_string(),
            status: READY.to_string(),
            program,
            vm_state,
            created_at: now(),
            last_run: now(),
            error: String::new(),
            mailbox: VecDeque::new(),
            wake_at: None,
        };
        self.bridge
            .call("persist_job", serde_json::to_value(&snapshot).unwrap())?;
        self.insert_job(snapshot).await;
        Ok(json!({"success": true, "pid": pid, "processes": self.infos()}))
    }

    async fn tick_all(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let gas = args
            .get("max_per_process")
            .and_then(JsonValue::as_u64)
            .unwrap_or(100);
        let pids: Vec<i64> = self.jobs.keys().copied().collect();
        let mut alive = 0;
        for pid in pids {
            let Some(job) = self.jobs.get_mut(&pid) else {
                continue;
            };
            // BLOCKED también se tickea: reintenta el LOCK pendiente.
            if job.snapshot.status != READY && job.snapshot.status != BLOCKED {
                continue;
            }
            let (tx, rx) = oneshot::channel();
            job.tx
                .send(JobCommand::Tick { gas, reply: tx })
                .await
                .map_err(|_| "job stopped")?;
            job.snapshot = rx.await.map_err(|_| "job stopped")??;
            if job.snapshot.status != DEAD {
                alive += 1;
            }
        }
        Ok(
            json!({"success": true, "alive": alive, "total": self.jobs.len(), "processes": self.infos()}),
        )
    }

    async fn kill(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let pid = json_pid(&args)?;
        let Some(job) = self.jobs.get_mut(&pid) else {
            return Ok(json!({"success": false, "pid": pid}));
        };
        let (tx, rx) = oneshot::channel();
        job.tx
            .send(JobCommand::Kill { reply: tx })
            .await
            .map_err(|_| "job stopped")?;
        job.snapshot = rx.await.map_err(|_| "job stopped")??;
        Ok(json!({"success": true, "pid": pid}))
    }

    async fn mailbox_send(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let pid = args
            .get("to_pid")
            .or_else(|| args.get("pid"))
            .and_then(json_i64)
            .ok_or("pid required")?;
        let Some(job) = self.jobs.get_mut(&pid) else {
            return Err(format!("process {pid} not found"));
        };
        self.message_seq += 1;
        let id = format!("m{}_{}", (now() * 1_000_000.0) as u64, self.message_seq);
        let message = MailboxMessage {
            id: id.clone(),
            content: args.get("message").cloned().unwrap_or(JsonValue::Null),
        };
        let (tx, rx) = oneshot::channel();
        job.tx
            .send(JobCommand::Send { message, reply: tx })
            .await
            .map_err(|_| "job stopped")?;
        job.snapshot = rx.await.map_err(|_| "job stopped")??;
        Ok(json!({"success": true, "message_id": id, "to_pid": pid}))
    }

    async fn mailbox_read(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let pid = json_pid(&args)?;
        let Some(job) = self.jobs.get_mut(&pid) else {
            return Err(format!("process {pid} not found"));
        };
        let (tx, rx) = oneshot::channel();
        job.tx
            .send(JobCommand::ReadMailbox { reply: tx })
            .await
            .map_err(|_| "job stopped")?;
        let (messages, snapshot) = rx.await.map_err(|_| "job stopped")??;
        job.snapshot = snapshot;
        Ok(json!({"success": true, "count": messages.len(), "messages": messages}))
    }

    async fn sleep_job(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let pid = json_pid(&args)?;
        let seconds = args
            .get("seconds")
            .and_then(JsonValue::as_f64)
            .unwrap_or(60.0);
        let Some(job) = self.jobs.get_mut(&pid) else {
            return Err(format!("process {pid} not found"));
        };
        let (tx, rx) = oneshot::channel();
        job.tx
            .send(JobCommand::Sleep { seconds, reply: tx })
            .await
            .map_err(|_| "job stopped")?;
        job.snapshot = rx.await.map_err(|_| "job stopped")??;
        let command_tx = self.command_tx.clone();
        tokio::task::spawn_local(async move {
            sleep(Duration::from_secs_f64(seconds.max(0.0))).await;
            let _ = command_tx.send(SchedulerCommand::WakeJob(pid));
        });
        Ok(json!({"success": true, "pid": pid, "status": HIBERNATE, "wake_in_seconds": seconds}))
    }

    async fn wake(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let pid = json_pid(&args)?;
        self.wake_pid(pid).await?;
        let status = self
            .jobs
            .get(&pid)
            .map(|job| job.snapshot.status.clone())
            .unwrap_or_else(|| DEAD.to_string());
        Ok(json!({"success": true, "pid": pid, "status": status}))
    }

    async fn wake_pid(&mut self, pid: i64) -> Result<(), String> {
        let Some(job) = self.jobs.get_mut(&pid) else {
            return Err(format!("process {pid} not found"));
        };
        let (tx, rx) = oneshot::channel();
        job.tx
            .send(JobCommand::Wake { reply: Some(tx) })
            .await
            .map_err(|_| "job stopped")?;
        job.snapshot = rx.await.map_err(|_| "job stopped")??;
        Ok(())
    }

    async fn export(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let pid = json_pid(&args)?;
        let Some(job) = self.jobs.get_mut(&pid) else {
            return Err(format!("process {pid} not found"));
        };
        let (tx, rx) = oneshot::channel();
        job.tx
            .send(JobCommand::Snapshot { reply: tx })
            .await
            .map_err(|_| "job stopped")?;
        job.snapshot = rx.await.map_err(|_| "job stopped")??;
        Ok(json!({"success": true, "state": job.snapshot}))
    }

    async fn import(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let mut snapshot: JobSnapshot = serde_json::from_value(
            args.get("state")
                .cloned()
                .ok_or("state required for import")?,
        )
        .map_err(|error| format!("invalid MVM v4 state: {error}"))?;
        let target_pid = args.get("target_pid").and_then(json_i64);
        let pid = match target_pid {
            Some(pid) => pid,
            None => self
                .bridge
                .call("allocate_pid", json!({}))?
                .get("pid")
                .and_then(JsonValue::as_i64)
                .ok_or("allocate_pid returned no pid")?,
        };
        if self.jobs.contains_key(&pid) {
            self.kill(json!({"pid": pid})).await?;
            self.jobs.remove(&pid);
        }
        if target_pid.is_some() {
            self.bridge.call("forget_pid", json!({"pid": pid}))?;
        }
        snapshot.pid = pid;
        snapshot.vm_state.job_id = pid;
        let imported_name = args
            .get("name")
            .and_then(JsonValue::as_str)
            .filter(|name| !name.is_empty())
            .map(str::to_string)
            .unwrap_or_else(|| snapshot.name.clone());
        snapshot.name = imported_name;
        if snapshot.status == RUNNING {
            snapshot.status = READY.to_string();
        }
        snapshot.last_run = now();
        self.bridge
            .call("persist_job", serde_json::to_value(&snapshot).unwrap())?;
        self.insert_job(snapshot).await;
        Ok(json!({"success": true, "pid": pid}))
    }

    fn cron_add(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let name = args
            .get("name")
            .and_then(JsonValue::as_str)
            .filter(|value| !value.is_empty())
            .ok_or("cron name required")?
            .to_string();
        let interval = args
            .get("interval")
            .or_else(|| args.get("interval_secs"))
            .and_then(JsonValue::as_f64)
            .unwrap_or(60.0)
            .max(0.001);
        let generation = self.cron.get(&name).map_or(1, |entry| entry.generation + 1);
        let entry = CronEntry {
            name: name.clone(),
            interval,
            action: args
                .get("action")
                .and_then(JsonValue::as_str)
                .unwrap_or_default()
                .to_string(),
            enabled: args
                .get("enabled")
                .and_then(JsonValue::as_bool)
                .unwrap_or(true),
            last_run: 0.0,
            created: now(),
            generation,
        };
        self.bridge
            .call("persist_cron", serde_json::to_value(&entry).unwrap())?;
        self.schedule_cron(&entry);
        self.cron.insert(name.clone(), entry);
        Ok(json!({"success": true, "name": name}))
    }

    fn cron_remove(&mut self, args: JsonValue) -> Result<JsonValue, String> {
        let name = args
            .get("name")
            .and_then(JsonValue::as_str)
            .ok_or("cron name required")?;
        self.cron.remove(name);
        self.bridge.call("remove_cron", json!({"name": name}))?;
        Ok(json!({"success": true, "name": name}))
    }

    fn schedule_cron(&self, entry: &CronEntry) {
        if !entry.enabled {
            return;
        }
        let tx = self.command_tx.clone();
        let name = entry.name.clone();
        let generation = entry.generation;
        let delay = if entry.last_run > 0.0 {
            (entry.last_run + entry.interval - now()).max(0.0)
        } else {
            entry.interval
        };
        tokio::task::spawn_local(async move {
            sleep(Duration::from_secs_f64(delay)).await;
            let _ = tx.send(SchedulerCommand::CronFire(name, generation));
        });
    }

    async fn fire_cron(&mut self, name: &str, generation: u64) -> Result<(), String> {
        let Some(entry) = self.cron.get(name).cloned() else {
            return Ok(());
        };
        if !entry.enabled || entry.generation != generation {
            return Ok(());
        }
        let mut updated = entry.clone();
        updated.last_run = now();
        self.bridge
            .call("persist_cron", serde_json::to_value(&updated).unwrap())?;
        self.cron.insert(name.to_string(), updated.clone());
        self.spawn(json!({
            "code": updated.action,
            "name": format!("cron:{name}"),
        }))
        .await?;
        self.schedule_cron(&updated);
        Ok(())
    }
}

fn json_i64(value: &JsonValue) -> Option<i64> {
    value.as_i64().or_else(|| value.as_str()?.parse().ok())
}

fn json_pid(args: &JsonValue) -> Result<i64, String> {
    args.get("pid")
        .and_then(json_i64)
        .ok_or_else(|| "pid required".to_string())
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::ffi::CStr;

    unsafe extern "C" fn callback(
        _context: *mut std::ffi::c_void,
        request: *const std::ffi::c_char,
        output: *mut u8,
        capacity: usize,
    ) -> isize {
        let request: JsonValue =
            serde_json::from_str(CStr::from_ptr(request).to_str().unwrap()).unwrap();
        let response = match request["op"].as_str().unwrap() {
            "allocate_pid" => json!({"success": true, "pid": 1}),
            "load_jobs" => json!({"success": true, "jobs": []}),
            "get" => json!({"success": true, "found": false, "value": null}),
            "data" => json!({"success": true, "value": 0}),
            "order" => json!({"success": true, "value": null}),
            _ => json!({"success": true}),
        };
        let bytes = response.to_string().into_bytes();
        if output.is_null() || capacity == 0 {
            return bytes.len() as isize;
        }
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), output, bytes.len());
        bytes.len() as isize
    }

    #[test]
    fn tokio_job_yields_and_completes() {
        let bridge = CallbackBridge::new(callback, std::ptr::null_mut());
        let mvm = TokioMvm::start(bridge).unwrap();
        let spawned = mvm
            .call(
                json!({"op":"spawn","args":{"code":"S x=1\nS y=2","name":"golden","gas_limit":1}}),
            )
            .unwrap();
        assert_eq!(spawned["pid"], 1);
        let first = mvm
            .call(json!({"op":"tick","args":{"max_per_process":1}}))
            .unwrap();
        assert_eq!(first["processes"][0]["status"], READY);
        let second = mvm
            .call(json!({"op":"tick","args":{"max_per_process":1}}))
            .unwrap();
        assert_eq!(second["processes"][0]["status"], DEAD);
        assert_eq!(second["processes"][0]["gas_total"], 2);
    }

    // ── LOCK: tabla de locks compartida para simular pdb_lock ──

    use std::collections::HashMap;
    use std::sync::atomic::{AtomicI64, Ordering};
    use std::sync::Mutex;

    static NEXT_PID: AtomicI64 = AtomicI64::new(1);
    static LOCKS: Mutex<Option<HashMap<String, i64>>> = Mutex::new(None);

    unsafe extern "C" fn lock_callback(
        _context: *mut std::ffi::c_void,
        request: *const std::ffi::c_char,
        output: *mut u8,
        capacity: usize,
    ) -> isize {
        let request: JsonValue =
            serde_json::from_str(CStr::from_ptr(request).to_str().unwrap()).unwrap();
        let args = &request["args"];
        let key = || {
            format!(
                "{}|{}",
                args["ns"].as_str().unwrap_or_default(),
                args["subs"].to_string()
            )
        };
        let response = match request["op"].as_str().unwrap() {
            "allocate_pid" => {
                json!({"success": true, "pid": NEXT_PID.fetch_add(1, Ordering::SeqCst)})
            }
            "load_jobs" => json!({"success": true, "jobs": []}),
            "get" => json!({"success": true, "found": false, "value": null}),
            "data" => json!({"success": true, "value": 0}),
            "order" => json!({"success": true, "value": null}),
            "lock" => {
                let pid = args["pid"].as_i64().unwrap();
                let mut table = LOCKS.lock().unwrap();
                let table = table.get_or_insert_with(HashMap::new);
                let owner = *table.entry(key()).or_insert(pid);
                json!({"success": true, "locked": owner == pid})
            }
            "unlock" => {
                let pid = args["pid"].as_i64().unwrap();
                let mut table = LOCKS.lock().unwrap();
                let table = table.get_or_insert_with(HashMap::new);
                if args["all"].as_bool() == Some(true) {
                    table.retain(|_, owner| *owner != pid);
                } else {
                    let key = key();
                    if table.get(&key) == Some(&pid) {
                        table.remove(&key);
                    }
                }
                json!({"success": true})
            }
            _ => json!({"success": true}),
        };
        let bytes = response.to_string().into_bytes();
        if output.is_null() || capacity == 0 {
            return bytes.len() as isize;
        }
        std::ptr::copy_nonoverlapping(bytes.as_ptr(), output, bytes.len());
        bytes.len() as isize
    }

    #[test]
    fn lock_contention_blocks_and_releases_when_the_holder_dies() {
        let bridge = CallbackBridge::new(lock_callback, std::ptr::null_mut());
        let mvm = TokioMvm::start(bridge).unwrap();
        let code = "L ^MUTEX(1)\nS x=1\nS x=2\nS x=3";
        let first = mvm
            .call(json!({"op":"spawn","args":{"code":code,"name":"holder","gas_limit":2}}))
            .unwrap()["pid"]
            .as_i64()
            .unwrap();
        let second = mvm
            .call(json!({"op":"spawn","args":{"code":code,"name":"waiter","gas_limit":2}}))
            .unwrap()["pid"]
            .as_i64()
            .unwrap();

        let status = |response: &JsonValue, pid: i64| {
            response["processes"]
                .as_array()
                .unwrap()
                .iter()
                .find(|process| process["pid"] == pid)
                .unwrap()["status"]
                .clone()
        };

        // Tick 1: holder adquiere y cede por gas; waiter no adquiere → BLOCKED.
        let tick1 = mvm
            .call(json!({"op":"tick","args":{"max_per_process":2}}))
            .unwrap();
        assert_eq!(status(&tick1, first), READY);
        assert_eq!(status(&tick1, second), BLOCKED);

        // Tick 2: holder termina (DEAD → unlock_all); waiter reintenta el
        // mismo LOCK, lo adquiere y sigue ejecutando.
        let tick2 = mvm
            .call(json!({"op":"tick","args":{"max_per_process":2}}))
            .unwrap();
        assert_eq!(status(&tick2, first), DEAD);
        assert_eq!(status(&tick2, second), READY);

        // El waiter acaba y suelta también su lock: tabla vacía.
        let tick3 = mvm
            .call(json!({"op":"tick","args":{"max_per_process":10}}))
            .unwrap();
        assert_eq!(status(&tick3, second), DEAD);
        assert!(LOCKS.lock().unwrap().as_ref().unwrap().is_empty());
    }
}
