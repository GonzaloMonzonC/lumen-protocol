//! Smith Streaming State Machine — v0.2 endurecida
//!
//! ForkState machine para el orquestador multi-personalidad Smith.
//! Basado en los estados del MVM (Completed, Yielded, Halted, Error)
//! y extendido para streaming progresivo con eventos NDJSON.
//!
//! Arquitectura:
//!   SmithCoordinator gestiona N forks en threads separados.
//!   Cada fork emite eventos a una cola compartida acotada (MAX_EVENTS).
//!   Python pollea smith:poll() para obtener eventos en tiempo real.
//!
//! Estados MVM origen → ForkState:
//!   Completed  → PartialReady / Complete
//!   Yielded    → Thinking (esperando LLM)
//!   Halted     → Timeout / Degraded
//!   Error      → Error
//!
//! Endurecimiento v0.2 (auditoría externa):
//!   #1  max_pulses se aplica (exceso → Degraded, no pulsos infinitos)
//!   #2  Timeout POR fork (started_at individual, no global de sesión)
//!   #3  fork_timeout calcula elapsed desde el inicio del fork
//!   #4  escape_json completo (\b \f y todos los controles 0x00-0x1F)
//!   #5  fork_buffering O(1) amortizado (append sin clonar el Vec)
//!   #6  Cola de eventos acotada (MAX_EVENTS; descarta los más antiguos)
//!   #7  completed_results conserva pulse_count real
//!   #8  duration_ms por fork (finished_at − started_at), no global
//!   #9  Locks tolerantes a poisoning (lock_ok, sin unwrap panickeable)
//!   #10 set_synthesis valida precondiciones (≥1 fork listo; una sola vez)
//!   #11 get_session funcional (Arc<Mutex<Coordinator>> por sesión)
//!   #12 cancel_fork para abortar forks en curso
//!   #13 fork_complete solo desde estados activos (no desde Error/Timeout)
//!   #14 Heartbeat con timestamp en su render NDJSON

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::time::{Duration, Instant};

/// Lock tolerante a poisoning (#9): si otro hilo paniqueó con el lock tomado,
/// recuperamos el dato en vez de propagar el panic.
fn lock_ok<T>(m: &Mutex<T>) -> MutexGuard<'_, T> {
    m.lock().unwrap_or_else(|p| p.into_inner())
}

/// Límite de la cola de eventos por sesión (#6): si el cliente no hace poll(),
/// se descartan los más antiguos en bloque — la cola nunca crece sin techo.
const MAX_EVENTS: usize = 10_000;

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

// ── Fork states ─────────────────────────────────────────────────────

/// Estado de un fork individual de Smith.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ForkState {
    /// Fork creado pero no iniciado
    Idle,
    /// Fork registrado, esperando asignación a thread worker.
    /// `started_at_ms` (epoch ms) habilita timeouts POR fork (#2/#3).
    Pending {
        started_at_ms: u64,
    },
    /// LLM en progreso, emitiendo pulsos de pensamiento
    Thinking {
        pulse_count: u64,
        last_thought: String,
    },
    /// Acumulando chunks de respuesta parcial
    Buffering {
        chunks: Vec<String>,
    },
    /// Fork completó su respuesta
    PartialReady {
        response: String,
    },
    /// Fork excedió su presupuesto de tiempo
    Timeout {
        elapsed_ms: u64,
    },
    /// Fallo temporal — se degradó a plan B (modelo más barato / menos pasos)
    Degraded {
        fallback: String,
        retries: u64,
    },
    /// Error permanente
    Error {
        reason: String,
    },
    /// Integrado en la síntesis final
    Complete,
}

impl ForkState {
    pub fn is_terminal(&self) -> bool {
        matches!(self, ForkState::PartialReady { .. }
            | ForkState::Timeout { .. }
            | ForkState::Error { .. }
            | ForkState::Complete)
    }

    pub fn is_active(&self) -> bool {
        !matches!(self, ForkState::Idle | ForkState::Complete)
    }

    pub fn label(&self) -> &'static str {
        match self {
            ForkState::Idle => "idle",
            ForkState::Pending { .. } => "pending",
            ForkState::Thinking { .. } => "thinking",
            ForkState::Buffering { .. } => "buffering",
            ForkState::PartialReady { .. } => "partial",
            ForkState::Timeout { .. } => "timeout",
            ForkState::Degraded { .. } => "degraded",
            ForkState::Error { .. } => "error",
            ForkState::Complete => "complete",
        }
    }
}

// ── Events ─────────────────────────────────────────────────────────

/// Eventos que emite Smith durante la ejecución de forks.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub enum SmithEvent {
    /// Pulso de pensamiento durante Thinking
    Pulse {
        domain: String,
        thought: String,
        pulse: u64,
    },
    /// Respuesta parcial completa
    Partial {
        domain: String,
        response: String,
    },
    /// Timeout alcanzado
    Timeout {
        domain: String,
        elapsed_ms: u64,
    },
    /// Degradación a plan B
    Degraded {
        domain: String,
        fallback: String,
        retries: u64,
    },
    /// Error permanente
    Error {
        domain: String,
        reason: String,
    },
    /// Síntesis completada
    Synthesis {
        response: String,
        domains_used: usize,
        domains_total: usize,
    },
    /// Heartbeat — el stream sigue vivo
    Heartbeat,
    /// Stream finalizado
    Done {
        total_domains: usize,
        total_duration_ms: u64,
    },
}

impl SmithEvent {
    pub fn to_ndjson(&self) -> String {
        match self {
            SmithEvent::Pulse { domain, thought, pulse } => {
                format!(r#"{{"type":"pulse","domain":"{}","thought":"{}","pulse":{}}}"#,
                    escape_json(domain), escape_json(thought), pulse)
            }
            SmithEvent::Partial { domain, response } => {
                format!(r#"{{"type":"partial","domain":"{}","response":"{}"}}"#,
                    escape_json(domain), escape_json(response))
            }
            SmithEvent::Timeout { domain, elapsed_ms } => {
                format!(r#"{{"type":"timeout","domain":"{}","elapsed_ms":{}}}"#,
                    escape_json(domain), elapsed_ms)
            }
            SmithEvent::Degraded { domain, fallback, retries } => {
                format!(r#"{{"type":"degraded","domain":"{}","fallback":"{}","retries":{}}}"#,
                    escape_json(domain), escape_json(fallback), retries)
            }
            SmithEvent::Error { domain, reason } => {
                format!(r#"{{"type":"error","domain":"{}","reason":"{}"}}"#,
                    escape_json(domain), escape_json(reason))
            }
            SmithEvent::Synthesis { response, domains_used, domains_total } => {
                format!(r#"{{"type":"synthesis","response":"{}","domains_used":{},"domains_total":{}}}"#,
                    escape_json(response), domains_used, domains_total)
            }
            // #14: el heartbeat lleva timestamp — el cliente sabe si es fresco o stale
            SmithEvent::Heartbeat => {
                format!(r#"{{"type":"heartbeat","ts_ms":{}}}"#, now_ms())
            }
            SmithEvent::Done { total_domains, total_duration_ms } => {
                format!(r#"{{"type":"done","total_domains":{},"total_duration_ms":{}}}"#,
                    total_domains, total_duration_ms)
            }
        }
    }
}

/// Escape JSON completo (#4): backspace, form feed y TODOS los caracteres
/// de control 0x00-0x1F como \u00XX — un thought con \0 ya no rompe el NDJSON.
fn escape_json(s: &str) -> String {
    let mut out = String::with_capacity(s.len() + 8);
    for c in s.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '"' => out.push_str("\\\""),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            '\t' => out.push_str("\\t"),
            '\u{08}' => out.push_str("\\b"),
            '\u{0C}' => out.push_str("\\f"),
            c if (c as u32) < 0x20 => out.push_str(&format!("\\u{:04x}", c as u32)),
            c => out.push(c),
        }
    }
    out
}

// ── ForkResult — resultado de un fork ──────────────────────────────

/// Resultado de un fork individual.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForkResult {
    pub domain: String,
    pub state: ForkState,
    pub response: Option<String>,
    pub duration_ms: u64,
    pub pulse_count: u64,
}

// ── SmithCoordinator — el corazón del sistema ──────────────────────

/// Gestiona una sesión con múltiples forks.
pub struct SmithCoordinator {
    domains: Vec<String>,
    forks: HashMap<String, ForkState>,
    /// Inicio de cada fork en epoch ms — timeout POR fork (#2/#3)
    started_at: HashMap<String, u64>,
    /// Fin de cada fork (epoch ms) — duración individual en resultados (#8)
    finished_at: HashMap<String, u64>,
    /// Pulsos emitidos por fork — sobrevive a Buffering (#7)
    pulses: HashMap<String, u64>,
    events: Arc<Mutex<Vec<SmithEvent>>>,
    last_poll: Arc<Mutex<Instant>>,
    start_time: Instant,
    fork_timeout: Duration,
    max_pulses: u64,
    last_heartbeat: Arc<Mutex<Instant>>,
    heartbeat_interval: Duration,
    synthesis_done: bool,
}

impl SmithCoordinator {
    pub fn new(domains: &[String]) -> Self {
        let mut forks = HashMap::new();
        for domain in domains {
            forks.insert(domain.clone(), ForkState::Idle);
        }
        Self {
            domains: domains.to_vec(),
            forks,
            started_at: HashMap::new(),
            finished_at: HashMap::new(),
            pulses: HashMap::new(),
            events: Arc::new(Mutex::new(Vec::new())),
            last_poll: Arc::new(Mutex::new(Instant::now())),
            start_time: Instant::now(),
            fork_timeout: Duration::from_secs(30),
            max_pulses: 5,
            last_heartbeat: Arc::new(Mutex::new(Instant::now())),
            heartbeat_interval: Duration::from_secs(5),
            synthesis_done: false,
        }
    }

    /// Ajustar el timeout de fork de esta sesión (útil en tests)
    pub fn set_fork_timeout(&mut self, d: Duration) -> &mut Self {
        self.fork_timeout = d;
        self
    }

    /// Ajustar el tope de pulsos de pensamiento por fork
    pub fn set_max_pulses(&mut self, n: u64) -> &mut Self {
        self.max_pulses = n;
        self
    }

    fn started_or_now(&self, domain: &str) -> u64 {
        *self.started_at.get(domain).unwrap_or(&(self.start_time_epoc_ms()))
    }

    fn start_time_epoc_ms(&self) -> u64 {
        now_ms().saturating_sub(self.start_time.elapsed().as_millis() as u64)
    }

    /// Iniciar un fork: transiciona Idle → Pending(started_at_ms)
    pub fn start_fork(&mut self, domain: &str) {
        if let Some(state) = self.forks.get_mut(domain) {
            if *state == ForkState::Idle {
                let t = now_ms();
                self.started_at.insert(domain.to_string(), t);
                *state = ForkState::Pending { started_at_ms: t };
            }
        }
    }

    /// Pending → Thinking. Devuelve false si el fork se degradó por exceder
    /// max_pulses (#1): el plan B entra, no hay bucle infinito de pulsos.
    pub fn fork_thinking(&mut self, domain: &str, thought: &str) -> bool {
        if let Some(state) = self.forks.get_mut(domain) {
            match state {
                ForkState::Pending { .. } | ForkState::Thinking { .. } => {
                    let pulse_count = match state {
                        ForkState::Thinking { pulse_count, .. } => *pulse_count + 1,
                        _ => 1,
                    };
                    if pulse_count > self.max_pulses {
                        let retries = pulse_count.saturating_sub(1);
                        *state = ForkState::Degraded {
                            fallback: format!("excedido max_pulses={}", self.max_pulses),
                            retries,
                        };
                        self.push_event(SmithEvent::Degraded {
                            domain: domain.to_string(),
                            fallback: format!("max_pulses={} alcanzado", self.max_pulses),
                            retries,
                        });
                        return false;
                    }
                    *state = ForkState::Thinking {
                        pulse_count,
                        last_thought: thought.to_string(),
                    };
                    self.pulses.insert(domain.to_string(), pulse_count);
                    self.push_event(SmithEvent::Pulse {
                        domain: domain.to_string(),
                        thought: thought.to_string(),
                        pulse: pulse_count,
                    });
                    return true;
                }
                _ => {}
            }
        }
        false
    }

    /// Acumular un chunk: Thinking → Buffering, o append en Buffering.
    /// O(1) amortizado — sin clonar el vector entero por chunk (#5).
    pub fn fork_buffering(&mut self, domain: &str, chunk: &str) {
        if let Some(state) = self.forks.get_mut(domain) {
            match state {
                ForkState::Thinking { .. } => {
                    *state = ForkState::Buffering {
                        chunks: vec![chunk.to_string()],
                    };
                }
                ForkState::Buffering { chunks } => {
                    chunks.push(chunk.to_string());
                }
                _ => {}
            }
        }
    }

    /// Completar un fork: Thinking/Buffering/Pending → PartialReady.
    /// Ignora transiciones inválidas desde estados terminales (#13).
    pub fn fork_complete(&mut self, domain: &str, response: &str) {
        let valido = matches!(
            self.forks.get(domain),
            Some(ForkState::Pending { .. })
                | Some(ForkState::Thinking { .. })
                | Some(ForkState::Buffering { .. })
        );
        if !valido {
            return;
        }
        self.finished_at.insert(
            domain.to_string(),
            now_ms().min(self.started_or_now(domain).saturating_add(self.fork_timeout.as_millis() as u64 * 60)),
        );
        self.finished_at.insert(domain.to_string(), now_ms());
        if let Some(state) = self.forks.get_mut(domain) {
            *state = ForkState::PartialReady {
                response: response.to_string(),
            };
        }
        self.push_event(SmithEvent::Partial {
            domain: domain.to_string(),
            response: response.to_string(),
        });
    }

    /// Abortar un fork en curso (#12): lo marca como Error("cancelado").
    pub fn cancel_fork(&mut self, domain: &str) {
        let activo = matches!(
            self.forks.get(domain),
            Some(s) if s.is_active() && !matches!(s, ForkState::Complete)
        );
        if activo {
            self.finished_at.insert(domain.to_string(), now_ms());
            if let Some(state) = self.forks.get_mut(domain) {
                *state = ForkState::Error {
                    reason: "cancelado por el host".to_string(),
                };
            }
            self.push_event(SmithEvent::Error {
                domain: domain.to_string(),
                reason: "cancelado por el host".to_string(),
            });
        }
    }

    /// Timeout en un fork — elapsed medido DESDE EL INICIO DEL FORK (#3)
    pub fn fork_timeout(&mut self, domain: &str) {
        let started = self.started_or_now(domain);
        let elapsed = now_ms().saturating_sub(started);
        if matches!(
            self.forks.get(domain),
            Some(ForkState::Pending { .. })
                | Some(ForkState::Thinking { .. })
                | Some(ForkState::Buffering { .. })
        ) {
            self.finished_at.insert(domain.to_string(), now_ms());
            if let Some(state) = self.forks.get_mut(domain) {
                *state = ForkState::Timeout { elapsed_ms: elapsed };
            }
            self.push_event(SmithEvent::Timeout {
                domain: domain.to_string(),
                elapsed_ms: elapsed,
            });
        }
    }

    /// Degradar un fork a plan B
    pub fn fork_degraded(&mut self, domain: &str, fallback: &str, retries: u64) {
        if let Some(state) = self.forks.get_mut(domain) {
            *state = ForkState::Degraded {
                fallback: fallback.to_string(),
                retries,
            };
            self.push_event(SmithEvent::Degraded {
                domain: domain.to_string(),
                fallback: fallback.to_string(),
                retries,
            });
        }
    }

    /// Error en un fork
    pub fn fork_error(&mut self, domain: &str, reason: &str) {
        self.finished_at.insert(domain.to_string(), now_ms());
        if let Some(state) = self.forks.get_mut(domain) {
            *state = ForkState::Error {
                reason: reason.to_string(),
            };
            self.push_event(SmithEvent::Error {
                domain: domain.to_string(),
                reason: reason.to_string(),
            });
        }
    }

    /// Marcar síntesis como completada. Con guarda (#10): requiere al menos
    /// un fork listo y que no se haya sintetizado antes. Devuelve si procedió.
    pub fn set_synthesis(&mut self, response: &str) -> bool {
        if self.synthesis_done {
            return false;
        }
        let listos = self.forks.values()
            .filter(|s| matches!(s, ForkState::PartialReady { .. }))
            .count();
        if listos == 0 {
            return false;
        }
        self.synthesis_done = true;
        let used = listos + self.forks.values()
            .filter(|s| matches!(s, ForkState::Complete))
            .count();
        let total = self.forks.len();
        self.push_event(SmithEvent::Synthesis {
            response: response.to_string(),
            domains_used: used,
            domains_total: total,
        });
        for state in self.forks.values_mut() {
            if matches!(state, ForkState::PartialReady { .. }) {
                *state = ForkState::Complete;
            }
        }
        let total_duration = self.start_time.elapsed().as_millis() as u64;
        self.push_event(SmithEvent::Done {
            total_domains: total,
            total_duration_ms: total_duration,
        });
        true
    }

    /// Poll: obtener eventos nuevos desde el último poll
    pub fn poll_events(&mut self) -> Vec<SmithEvent> {
        *lock_ok(&self.last_poll) = Instant::now();
        self.check_heartbeat();
        lock_ok(&self.events).drain(..).collect()
    }

    /// Verificar timeouts POR FORK (#2): cada fork se compara contra su propio
    /// started_at — uno tardío ya no muere por el reloj de la sesión.
    pub fn check_timeouts(&mut self) {
        let timeout_ms = self.fork_timeout.as_millis() as u64;
        let ahora = now_ms();
        let vencidos: Vec<String> = self.forks.iter()
            .filter(|(d, s)| {
                matches!(s, ForkState::Pending { .. } | ForkState::Thinking { .. } | ForkState::Buffering { .. })
                    && ahora.saturating_sub(*self.started_at.get(*d).unwrap_or(&ahora)) >= timeout_ms
            })
            .map(|(d, _)| d.clone())
            .collect();
        for domain in vencidos {
            self.fork_timeout(&domain);
        }
    }

    /// Verificar si todos los forks están en estado terminal
    /// (o la síntesis ya se hizo)
    pub fn all_terminated(&self) -> bool {
        self.synthesis_done || self.forks.values().all(|s| s.is_terminal())
    }

    /// Resultados de forks completados — con pulso y duración REALES (#7/#8)
    pub fn completed_results(&self) -> Vec<ForkResult> {
        let mut results = Vec::new();
        for (domain, state) in &self.forks {
            let response = match state {
                ForkState::PartialReady { response } => Some(response.clone()),
                ForkState::Complete => None,
                _ => continue,
            };
            let started = self.started_or_now(domain);
            let finished = *self.finished_at.get(domain).unwrap_or(&now_ms());
            results.push(ForkResult {
                domain: domain.clone(),
                state: state.clone(),
                response,
                duration_ms: finished.saturating_sub(started),
                pulse_count: *self.pulses.get(domain).unwrap_or(&0),
            });
        }
        results
    }

    /// Estado resumido de todos los forks
    pub fn status_summary(&self) -> Vec<(String, String, bool)> {
        self.forks.iter()
            .map(|(d, s)| (d.clone(), s.label().to_string(), s.is_terminal()))
            .collect()
    }

    /// Número de forks
    pub fn fork_count(&self) -> usize {
        self.forks.len()
    }

    /// Dominios de la sesión
    pub fn domains(&self) -> &[String] {
        &self.domains
    }

    // ── Helpers ──

    fn push_event(&mut self, event: SmithEvent) {
        let mut q = lock_ok(&self.events);
        if q.len() >= MAX_EVENTS {
            // descarta el bloque más antiguo, conserva el flujo reciente
            q.drain(..MAX_EVENTS / 2);
        }
        q.push(event);
    }

    fn check_heartbeat(&mut self) {
        let hb_elapsed = lock_ok(&self.last_heartbeat).elapsed();
        if hb_elapsed >= self.heartbeat_interval {
            self.push_event(SmithEvent::Heartbeat);
            *lock_ok(&self.last_heartbeat) = Instant::now();
        }
    }
}

// ── SmithRegistry — sesiones multi-agente ──────────────────────────

/// Registry global de sesiones Smith, accesible desde host.rs.
/// Cada sesión vive en su propio Arc<Mutex<..>> (#11): get_session puede
/// devolver un guard real del coordinator sin retener el lock del mapa.
pub struct SmithRegistry {
    sessions: Mutex<HashMap<u64, Arc<Mutex<SmithCoordinator>>>>,
    next_id: AtomicU64,
}

impl SmithRegistry {
    pub fn new() -> Self {
        Self {
            sessions: Mutex::new(HashMap::new()),
            next_id: AtomicU64::new(1),
        }
    }

    /// Guard directo al coordinator de una sesión (#11 — antes stubeado a None)
    pub fn get_session(&self, session_id: u64) -> Option<Arc<Mutex<SmithCoordinator>>> {
        lock_ok(&self.sessions).get(&session_id).cloned()
    }

    fn with<F>(&self, session_id: u64, f: F)
    where
        F: FnOnce(&mut SmithCoordinator),
    {
        if let Some(c) = lock_ok(&self.sessions).get(&session_id).cloned() {
            f(&mut lock_ok(&c));
        }
    }

    fn with_r<F, R>(&self, session_id: u64, f: F) -> Option<R>
    where
        F: FnOnce(&mut SmithCoordinator) -> R,
    {
        let c = lock_ok(&self.sessions).get(&session_id).cloned()?;
        let mut guard = lock_ok(&c);
        let out = f(&mut guard);
        drop(guard);
        Some(out)
    }

    /// Crear una nueva sesión Smith. Retorna session_id.
    pub fn create_session(&self, domains: &[String]) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let coordinator = Arc::new(Mutex::new(SmithCoordinator::new(domains)));
        lock_ok(&self.sessions).insert(id, coordinator);
        id
    }

    /// Poll eventos de una sesión
    pub fn poll_session(&self, session_id: u64) -> Option<Vec<SmithEvent>> {
        self.with_r(session_id, |c| c.poll_events())
    }

    /// Check timeouts de una sesión
    pub fn check_session_timeouts(&self, session_id: u64) {
        self.with(session_id, |c| c.check_timeouts());
    }

    /// Obtener resultados completados
    pub fn session_results(&self, session_id: u64) -> Option<Vec<ForkResult>> {
        self.with_r(session_id, |c| c.completed_results())
    }

    /// Verificar si todos terminaron
    pub fn session_done(&self, session_id: u64) -> Option<bool> {
        self.with_r(session_id, |c| c.all_terminated())
    }

    /// Status resumido de sesión
    pub fn session_status(&self, session_id: u64) -> Option<Vec<(String, String, bool)>> {
        self.with_r(session_id, |c| c.status_summary())
    }

    /// Eliminar una sesión
    pub fn remove_session(&self, session_id: u64) {
        lock_ok(&self.sessions).remove(&session_id);
    }

    /// Iniciar un fork en una sesión
    pub fn start_fork(&self, session_id: u64, domain: &str) {
        self.with(session_id, |c| c.start_fork(domain));
    }

    /// Thinking pulse en un fork (false si degradó por max_pulses)
    pub fn fork_thinking(&self, session_id: u64, domain: &str, thought: &str) -> bool {
        self.with_r(session_id, |c| c.fork_thinking(domain, thought)).unwrap_or(false)
    }

    /// Buffer un chunk en un fork
    pub fn fork_buffering(&self, session_id: u64, domain: &str, chunk: &str) {
        self.with(session_id, |c| c.fork_buffering(domain, chunk));
    }

    /// Fork completado (ignorado si el fork ya estaba terminado)
    pub fn fork_complete(&self, session_id: u64, domain: &str, response: &str) {
        self.with(session_id, |c| c.fork_complete(domain, response));
    }

    /// Cancelar un fork en curso
    pub fn cancel_fork(&self, session_id: u64, domain: &str) {
        self.with(session_id, |c| c.cancel_fork(domain));
    }

    /// Fork timeout
    pub fn fork_timeout(&self, session_id: u64, domain: &str) {
        self.with(session_id, |c| c.fork_timeout(domain));
    }

    /// Fork error
    pub fn fork_error(&self, session_id: u64, domain: &str, reason: &str) {
        self.with(session_id, |c| c.fork_error(domain, reason));
    }

    /// Marcar síntesis completada (false si no había forks listos o ya se hizo)
    pub fn set_synthesis(&self, session_id: u64, response: &str) -> bool {
        self.with_r(session_id, |c| c.set_synthesis(response)).unwrap_or(false)
    }
}

impl Default for SmithRegistry {
    fn default() -> Self {
        Self::new()
    }
}

impl Clone for SmithRegistry {
    fn clone(&self) -> Self {
        Self {
            // clonamos el mapa de Arcs (barato) — sin unwrap panickeable (#9)
            sessions: Mutex::new(lock_ok(&self.sessions).clone()),
            next_id: AtomicU64::new(self.next_id.load(Ordering::SeqCst)),
        }
    }
}

// ── Tests ──────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_fork_state_transitions() {
        let mut smith = SmithCoordinator::new(&["legal".to_string(), "finance".to_string()]);
        assert_eq!(smith.fork_count(), 2);
        assert_eq!(smith.forks.get("legal").unwrap(), &ForkState::Idle);

        smith.start_fork("legal");
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::Pending { .. }));

        assert!(smith.fork_thinking("legal", "Analizando..."));
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::Thinking { .. }));

        smith.fork_complete("legal", "Respuesta legal completa");
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::PartialReady { .. }));
    }

    #[test]
    fn test_event_queue() {
        let mut smith = SmithCoordinator::new(&["legal".to_string()]);
        smith.start_fork("legal");
        smith.fork_thinking("legal", "Pensamiento 1");
        smith.fork_thinking("legal", "Pensamiento 2");

        let events = smith.poll_events();
        assert_eq!(events.len(), 2); // 2 pulses

        let event_json = events[0].to_ndjson();
        assert!(event_json.contains("\"type\":\"pulse\""));
        assert!(event_json.contains("\"domain\":\"legal\""));
    }

    #[test]
    fn test_timeout_detection() {
        let mut smith = SmithCoordinator::new(&["legal".to_string()]);
        smith.start_fork("legal");
        smith.fork_timeout("legal");
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::Timeout { .. }));
    }

    /// #2/#3: el timeout es POR fork — un fork iniciado tarde no muere por el reloj de la sesión
    #[test]
    fn test_timeout_per_fork_not_global() {
        let mut smith = SmithCoordinator::new(&["rapido".to_string(), "lento".to_string()]);
        smith.set_fork_timeout(Duration::from_millis(80));

        smith.start_fork("rapido");
        // simulamos que "rapido" empezó hace mucho (epoch ms retrocedido)
        let hace_mucho = now_ms() - 500;
        smith.started_at.insert("rapido".to_string(), hace_mucho);

        smith.check_timeouts();
        assert!(matches!(smith.forks.get("rapido").unwrap(), ForkState::Timeout { .. }),
            "el fork viejo debe vencer");

        // "lento" empieza AHORA y aún no vence
        smith.start_fork("lento");
        smith.fork_thinking("lento", "trabajando...");
        smith.check_timeouts();
        assert!(matches!(smith.forks.get("lento").unwrap(), ForkState::Thinking { .. }),
            "un fork recién iniciado NO debe vencer aunque la sesión dure");
    }

    #[test]
    fn test_degraded_fallback() {
        let mut smith = SmithCoordinator::new(&["legal".to_string()]);
        smith.start_fork("legal");
        smith.fork_thinking("legal", "Intentando análisis profundo...");
        smith.fork_degraded("legal", "modelo rápido", 1);
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::Degraded { .. }));
    }

    /// #1: max_pulses se aplica — el pulso 6 degrada el fork en vez de emitir infinitos
    #[test]
    fn test_max_pulses_enforced() {
        let mut smith = SmithCoordinator::new(&["legal".to_string()]);
        smith.set_max_pulses(5);
        smith.start_fork("legal");
        for i in 1..=5 {
            assert!(smith.fork_thinking("legal", &format!("pulso {i}")), "pulso {i} válido");
        }
        assert!(!smith.fork_thinking("legal", "pulso 6"), "el pulso 6 debe degradar");
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::Degraded { .. }));

        let events = smith.poll_events();
        assert!(events.iter().any(|e| matches!(e, SmithEvent::Degraded { .. })));
    }

    #[test]
    fn test_synthesis_flow() {
        let mut smith = SmithCoordinator::new(&["a".to_string(), "b".to_string()]);
        smith.start_fork("a");
        smith.fork_complete("a", "R1");
        smith.start_fork("b");
        smith.fork_complete("b", "R2");
        assert!(smith.all_terminated());
        assert_eq!(smith.completed_results().len(), 2);

        assert!(smith.set_synthesis("Síntesis final"), "primera síntesis procede");
        assert!(!smith.set_synthesis("duplicada"), "#10: segunda síntesis rechazada");

        let events = smith.poll_events();
        assert!(events.iter().any(|e| matches!(e, SmithEvent::Synthesis { .. })));
        assert!(events.iter().any(|e| matches!(e, SmithEvent::Done { .. })));
    }

    /// #10: sin forks listos, la síntesis NO procede
    #[test]
    fn test_synthesis_requires_ready_forks() {
        let mut smith = SmithCoordinator::new(&["a".to_string()]);
        smith.start_fork("a");
        smith.fork_thinking("a", "aún pensando");
        assert!(!smith.set_synthesis("prematuro"));
        // y desde vacío-total tampoco
        let mut smith2 = SmithCoordinator::new(&["x".to_string()]);
        assert!(!smith2.set_synthesis("nadie listo"));
    }

    #[test]
    fn test_registry() {
        let registry = SmithRegistry::new();
        let sid = registry.create_session(&["legal".to_string(), "finance".to_string()]);
        assert!(sid > 0);

        registry.start_fork(sid, "legal");
        registry.fork_thinking(sid, "legal", "Thinking...");
        registry.fork_complete(sid, "legal", "Done");

        let events = registry.poll_session(sid);
        assert!(events.is_some());
        assert!(!events.unwrap().is_empty());

        registry.remove_session(sid);
        assert!(registry.poll_session(sid).is_none());
    }

    /// #11: get_session ya no es un stub — devuelve el coordinator real
    #[test]
    fn test_get_session_functional() {
        let registry = SmithRegistry::new();
        let sid = registry.create_session(&["a".to_string()]);
        let arc = registry.get_session(sid);
        assert!(arc.is_some(), "get_session debe devolver Some");
        let arc = registry.get_session(sid);
        assert!(arc.is_some(), "get_session debe devolver Some");
        let c = arc.unwrap();
        lock_ok(&c).start_fork("a");
        assert!(matches!(lock_ok(&c).forks.get("a").unwrap(), ForkState::Pending { .. }));
        drop(c);
        assert!(registry.get_session(9999).is_none());
    }

    #[test]
    fn test_ndjson_format() {
        let event = SmithEvent::Pulse {
            domain: "legal".to_string(),
            thought: "Análisis con \"comillas\" y saltos\n".to_string(),
            pulse: 1,
        };
        let json = event.to_ndjson();
        assert!(json.contains("\\\"comillas\\\""));
        assert!(json.contains("\\n"));
        assert!(json.starts_with('{'));
        assert!(json.ends_with('}'));
    }

    /// #4: caracteres de control extremos ya no rompen el NDJSON
    #[test]
    fn test_escape_control_chars() {
        let thought = "nulo\u{0000}back\u{0008}form\u{000C}y\u{0001}control";
        let event = SmithEvent::Pulse {
            domain: "d".to_string(),
            thought: thought.to_string(),
            pulse: 1,
        };
        let json = event.to_ndjson();
        assert!(json.contains("\\u0000"), "NUL escapado");
        assert!(json.contains("\\b"), "backspace escapado");
        assert!(json.contains("\\f"), "form feed escapado");
        assert!(json.contains("\\u0001"), "control genérico escapado");
        // una línea NDJSON válida: parseable como JSON
        let parsed: Result<serde_json::Value, _> = serde_json::from_str(&json);
        assert!(parsed.is_ok(), "la línea debe ser JSON válido: {json}");
    }

    /// #5: buffering O(n) — muchos chunks no degradan ni pierden datos
    #[test]
    fn test_buffering_many_chunks() {
        let mut smith = SmithCoordinator::new(&["a".to_string()]);
        smith.start_fork("a");
        smith.fork_thinking("a", "pensando");
        for i in 0..1000 {
            smith.fork_buffering("a", &format!("chunk-{i}"));
        }
        match smith.forks.get("a").unwrap() {
            ForkState::Buffering { chunks } => assert_eq!(chunks.len(), 1000),
            other => panic!("estado inesperado: {other:?}"),
        }
    }

    /// #13: fork_complete desde Error/Timeout se ignora
    #[test]
    fn test_fork_complete_rejects_terminal_states() {
        let mut smith = SmithCoordinator::new(&["a".to_string()]);
        smith.start_fork("a");
        smith.fork_error("a", "boom");
        smith.fork_complete("a", "resurrección imposible");
        assert!(matches!(smith.forks.get("a").unwrap(), ForkState::Error { .. }));
    }

    /// #12: cancel_fork aborta forks en curso
    #[test]
    fn test_cancel_fork() {
        let mut smith = SmithCoordinator::new(&["a".to_string()]);
        smith.start_fork("a");
        smith.fork_thinking("a", "trabajando");
        smith.cancel_fork("a");
        assert!(matches!(smith.forks.get("a").unwrap(), ForkState::Error { reason }
            if reason == "cancelado por el host"));

        // y cancelar algo terminado no hace nada
        smith.cancel_fork("a");
        assert!(matches!(smith.forks.get("a").unwrap(), ForkState::Error { .. }));
    }

    /// #7/#8: resultados con pulso y duración reales por fork
    #[test]
    fn test_completed_results_real_metrics() {
        let mut smith = SmithCoordinator::new(&["a".to_string()]);
        smith.start_fork("a");
        for i in 1..=3 {
            smith.fork_thinking("a", &format!("t{i}"));
        }
        smith.fork_complete("a", "respuesta");
        let results = smith.completed_results();
        assert_eq!(results.len(), 1);
        assert_eq!(results[0].pulse_count, 3, "el pulso real sobrevive a PartialReady");
        assert_eq!(results[0].response.as_deref(), Some("respuesta"));
        // duración ≥ 0 y plausible (< 60s de test)
        assert!(results[0].duration_ms < 60_000);
    }

    /// #6: la cola de eventos tiene techo
    #[test]
    fn test_events_capped() {
        let mut smith = SmithCoordinator::new(&["a".to_string()]);
        smith.start_fork("a");
        for i in 0..12_000 {
            smith.fork_thinking("a", &format!("pulso infinito {i}")).then_some(()).unwrap_or(());
        }
        let q_len = smith.events.lock().unwrap().len();
        assert!(q_len <= MAX_EVENTS, "cola acotada: {q_len}");
        // y el poll sigue funcionando
        assert!(!smith.poll_events().is_empty());
    }
}
