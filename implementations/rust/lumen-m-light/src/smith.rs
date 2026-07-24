//! Smith Streaming State Machine
//!
//! ForkState machine para el orquestador multi-personalidad Smith.
//! Basado en los estados del MVM (Completed, Yielded, Halted, Error)
//! y extendido para streaming progresivo con eventos NDJSON.
//!
//! Arquitectura:
//!   SmithCoordinator gestiona N forks en threads separados.
//!   Cada fork emite eventos via mpsc a una cola compartida.
//!   Python pollea smith:poll() para obtener eventos en tiempo real.
//!
//! Estados MVM origen → ForkState:
//!   Completed  → PartialReady / Complete
//!   Yielded    → Thinking (esperando LLM)
//!   Halted     → Timeout / Degraded
//!   Error      → Error

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// ── Fork states ─────────────────────────────────────────────────────

/// Estado de un fork individual de Smith.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
pub enum ForkState {
    /// Fork creado pero no iniciado
    Idle,
    /// Fork registrado, esperando asignación a thread worker
    Pending,
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
            ForkState::Pending => "pending",
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
    /// Síntesis completada (todos los forks listos)
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
                    domain, elapsed_ms)
            }
            SmithEvent::Degraded { domain, fallback, retries } => {
                format!(r#"{{"type":"degraded","domain":"{}","fallback":"{}","retries":{}}}"#,
                    domain, escape_json(fallback), retries)
            }
            SmithEvent::Error { domain, reason } => {
                format!(r#"{{"type":"error","domain":"{}","reason":"{}"}}"#,
                    domain, escape_json(reason))
            }
            SmithEvent::Synthesis { response, domains_used, domains_total } => {
                format!(r#"{{"type":"synthesis","response":"{}","domains_used":{},"domains_total":{}}}"#,
                    escape_json(response), domains_used, domains_total)
            }
            SmithEvent::Heartbeat => {
                r#"{"type":"heartbeat"}"#.to_string()
            }
            SmithEvent::Done { total_domains, total_duration_ms } => {
                format!(r#"{{"type":"done","total_domains":{},"total_duration_ms":{}}}"#,
                    total_domains, total_duration_ms)
            }
        }
    }
}

fn escape_json(s: &str) -> String {
    s.replace('\\', "\\\\")
        .replace('"', "\\\"")
        .replace('\n', "\\n")
        .replace('\r', "\\r")
        .replace('\t', "\\t")
}

// ── ForkHandle — resultado de un fork ──────────────────────────────

/// Resultado de un fork individual.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ForkResult {
    pub domain: String,
    pub state: ForkState,
    pub response: Option<String>,
    pub duration_ms: u64,
    pub pulse_count: u64,
}

// ── SmithCoordinator ───────────────────────────────────────────────

/// Coordinador global de sesiones Smith.
/// Cada sesión (stream) tiene su propio coordinator.
#[derive(Clone)]
pub struct SmithCoordinator {
    /// Dominios registrados para esta sesión
    domains: Vec<String>,
    /// Estado actual de cada fork
    forks: HashMap<String, ForkState>,
    /// Cola de eventos (consumida por smith:poll)
    events: Arc<Mutex<Vec<SmithEvent>>>,
    /// Último timestamp de poll
    last_poll: Arc<Mutex<Instant>>,
    /// Timestamp de inicio
    start_time: Instant,
    /// Timeout por fork (default 30s)
    fork_timeout: Duration,
    /// Máximo de pulsos de thinking por fork
    max_pulses: u64,
    /// Último heartbeat enviado
    last_heartbeat: Arc<Mutex<Instant>>,
    /// Intervalo de heartbeat (default 5s)
    heartbeat_interval: Duration,
    /// Si la síntesis ya se ejecutó
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

    /// Iniciar un fork: transiciona Idle → Pending
    pub fn start_fork(&mut self, domain: &str) {
        if let Some(state) = self.forks.get_mut(domain) {
            if *state == ForkState::Idle {
                *state = ForkState::Pending;
            }
        }
    }

    /// Marcar un fork como en progreso: Pending → Thinking
    pub fn fork_thinking(&mut self, domain: &str, thought: &str) {
        if let Some(state) = self.forks.get_mut(domain) {
            match state {
                ForkState::Pending | ForkState::Thinking { .. } => {
                    let pulse_count = match state {
                        ForkState::Thinking { pulse_count, .. } => *pulse_count + 1,
                        _ => 1,
                    };
                    *state = ForkState::Thinking {
                        pulse_count,
                        last_thought: thought.to_string(),
                    };
                    self.push_event(SmithEvent::Pulse {
                        domain: domain.to_string(),
                        thought: thought.to_string(),
                        pulse: pulse_count,
                    });
                }
                _ => {}
            }
        }
    }

    /// Buffer un chunk de respuesta: Thinking → Buffering
    pub fn fork_buffering(&mut self, domain: &str, chunk: &str) {
        if let Some(state) = self.forks.get_mut(domain) {
            match state {
                ForkState::Thinking { .. } | ForkState::Buffering { .. } => {
                    let mut chunks = match state {
                        ForkState::Buffering { chunks } => chunks.clone(),
                        _ => Vec::new(),
                    };
                    chunks.push(chunk.to_string());
                    *state = ForkState::Buffering { chunks };
                }
                _ => {}
            }
        }
    }

    /// Completar un fork: Buffering/Thinking → PartialReady
    pub fn fork_complete(&mut self, domain: &str, response: &str) {
        if let Some(state) = self.forks.get_mut(domain) {
            *state = ForkState::PartialReady {
                response: response.to_string(),
            };
            self.push_event(SmithEvent::Partial {
                domain: domain.to_string(),
                response: response.to_string(),
            });
        }
    }

    /// Timeout en un fork
    pub fn fork_timeout(&mut self, domain: &str) {
        let elapsed = self.start_time.elapsed().as_millis() as u64;
        if let Some(state) = self.forks.get_mut(domain) {
            *state = ForkState::Timeout { elapsed_ms: elapsed };
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

    /// Marcar síntesis como completada
    pub fn set_synthesis(&mut self, response: &str) {
        self.synthesis_done = true;
        let used = self.forks.values()
            .filter(|s| matches!(s, ForkState::PartialReady { .. } | ForkState::Complete))
            .count();
        let total = self.forks.len();
        self.push_event(SmithEvent::Synthesis {
            response: response.to_string(),
            domains_used: used,
            domains_total: total,
        });
        // Marcar todos como Complete
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
    }

    /// Poll: obtener eventos nuevos desde el último poll
    pub fn poll_events(&mut self) -> Vec<SmithEvent> {
        *self.last_poll.lock().unwrap() = Instant::now();
        self.check_heartbeat();
        self.events.lock().unwrap().drain(..).collect()
    }

    /// Verificar si algún fork ha excedido el timeout
    pub fn check_timeouts(&mut self) {
        let elapsed = self.start_time.elapsed();
        if elapsed < self.fork_timeout {
            return;
        }
        let domains: Vec<String> = self.forks.iter()
            .filter(|(_, s)| matches!(s, ForkState::Thinking { .. } | ForkState::Buffering { .. } | ForkState::Pending))
            .map(|(d, _)| d.clone())
            .collect();
        for domain in domains {
            self.fork_timeout(&domain);
        }
    }

    /// Verificar si todos los forks están en estado terminal
    pub fn all_terminated(&self) -> bool {
        self.synthesis_done || self.forks.values().all(|s| s.is_terminal())
    }

    /// Obtener resultados de forks completados
    pub fn completed_results(&self) -> Vec<ForkResult> {
        let mut results = Vec::new();
        for (domain, state) in &self.forks {
            let (response, pulse_count) = match state {
                ForkState::PartialReady { response } => {
                    (Some(response.clone()), 0u64)
                }
                ForkState::Complete => {
                    (None, 0u64)
                }
                _ => continue,
            };
            results.push(ForkResult {
                domain: domain.clone(),
                state: state.clone(),
                response,
                duration_ms: self.start_time.elapsed().as_millis() as u64,
                pulse_count: 0,
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

    // ── Helpers ──

    fn push_event(&mut self, event: SmithEvent) {
        self.events.lock().unwrap().push(event);
    }

    fn check_heartbeat(&mut self) {
        let hb_elapsed = self.last_heartbeat.lock().unwrap().elapsed();
        if hb_elapsed >= self.heartbeat_interval {
            self.push_event(SmithEvent::Heartbeat);
            *self.last_heartbeat.lock().unwrap() = Instant::now();
        }
    }
}

// ── SmithRegistry — sesiones multi-agente ──────────────────────────

/// Registry global de sesiones Smith, accesible desde host.rs.
/// Sobrevive a yields del VM (como SmithRegistry en el diseño).
pub struct SmithRegistry {
    sessions: Mutex<HashMap<u64, SmithCoordinator>>,
    next_id: AtomicU64,
}

impl SmithRegistry {
    pub fn new() -> Self {
        Self {
            sessions: Mutex::new(HashMap::new()),
            next_id: AtomicU64::new(1),
        }
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
            sessions: Mutex::new(self.sessions.lock().unwrap().clone()),
            next_id: AtomicU64::new(self.next_id.load(Ordering::SeqCst)),
        }
    }
}

impl SmithRegistry {
    /// Crear una nueva sesión Smith. Retorna session_id.
    pub fn create_session(&self, domains: &[String]) -> u64 {
        let id = self.next_id.fetch_add(1, Ordering::SeqCst);
        let coordinator = SmithCoordinator::new(domains);
        self.sessions.lock().unwrap().insert(id, coordinator);
        id
    }

    /// Obtener referencia a un coordinator (para poll/collect)
    pub fn get_session(&self, session_id: u64) -> Option<std::sync::MutexGuard<'_, SmithCoordinator>> {
        // No podemos devolver una ref al coordinator dentro del Mutex fácilmente.
        // En su lugar, exponemos métodos específicos.
        None
    }

    /// Poll eventos de una sesión
    pub fn poll_session(&self, session_id: u64) -> Option<Vec<SmithEvent>> {
        self.sessions.lock().unwrap().get_mut(&session_id)
            .map(|c| c.poll_events())
    }

    /// Check timeouts de una sesión
    pub fn check_session_timeouts(&self, session_id: u64) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.check_timeouts();
        }
    }

    /// Obtener resultados completados
    pub fn session_results(&self, session_id: u64) -> Option<Vec<ForkResult>> {
        self.sessions.lock().unwrap().get(&session_id)
            .map(|c| c.completed_results())
    }

    /// Verificar si todos terminaron
    pub fn session_done(&self, session_id: u64) -> Option<bool> {
        self.sessions.lock().unwrap().get(&session_id)
            .map(|c| c.all_terminated())
    }

    /// Status resumido de sesión
    pub fn session_status(&self, session_id: u64) -> Option<Vec<(String, String, bool)>> {
        self.sessions.lock().unwrap().get(&session_id)
            .map(|c| c.status_summary())
    }

    /// Eliminar una sesión
    pub fn remove_session(&self, session_id: u64) {
        self.sessions.lock().unwrap().remove(&session_id);
    }

    /// Iniciar un fork en una sesión
    pub fn start_fork(&self, session_id: u64, domain: &str) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.start_fork(domain);
        }
    }

    /// Thinking pulse en un fork
    pub fn fork_thinking(&self, session_id: u64, domain: &str, thought: &str) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.fork_thinking(domain, thought);
        }
    }

    /// Fork completado
    pub fn fork_complete(&self, session_id: u64, domain: &str, response: &str) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.fork_complete(domain, response);
        }
    }

    /// Fork timeout
    pub fn fork_timeout(&self, session_id: u64, domain: &str) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.fork_timeout(domain);
        }
    }

    /// Fork error
    pub fn fork_error(&self, session_id: u64, domain: &str, reason: &str) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.fork_error(domain, reason);
        }
    }

    /// Marcar síntesis completada
    pub fn set_synthesis(&self, session_id: u64, response: &str) {
        if let Some(c) = self.sessions.lock().unwrap().get_mut(&session_id) {
            c.set_synthesis(response);
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
        assert_eq!(smith.forks.get("legal").unwrap(), &ForkState::Pending);

        smith.fork_thinking("legal", "Analizando...");
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

    #[test]
    fn test_degraded_fallback() {
        let mut smith = SmithCoordinator::new(&["legal".to_string()]);
        smith.start_fork("legal");
        smith.fork_thinking("legal", "Intentando análisis profundo...");
        smith.fork_degraded("legal", "modelo rápido", 1);
        assert!(matches!(smith.forks.get("legal").unwrap(), ForkState::Degraded { .. }));
    }

    #[test]
    fn test_synthesis_flow() {
        let mut smith = SmithCoordinator::new(&["a".to_string(), "b".to_string()]);
        smith.start_fork("a");
        smith.fork_complete("a", "R1");
        smith.start_fork("b");
        smith.fork_complete("b", "R2");
        // PartialReady es terminal, forks completados
        assert!(smith.all_terminated());
        assert_eq!(smith.completed_results().len(), 2);

        smith.set_synthesis("Síntesis final");
        assert!(smith.all_terminated());

        let events = smith.poll_events();
        let has_synthesis = events.iter().any(|e| matches!(e, SmithEvent::Synthesis { .. }));
        let has_done = events.iter().any(|e| matches!(e, SmithEvent::Done { .. }));
        assert!(has_synthesis);
        assert!(has_done);
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
}
