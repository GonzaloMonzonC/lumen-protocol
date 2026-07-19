//! Wrapper: NativeHost — combina RedbHost + Device 8 (HTTP) + Device 9 (Webhook).
//!
//! S1 deliverable: job M puede O 8 y O 9 sin Python FFI.

use crate::device8::HttpDevice;
use crate::device9::{WebhookDevice, WebhookMessage};
use lumen_mlight::{Host, Subscript, Value};
use lumen_pdb::host::RedbHost;
use std::collections::VecDeque;
use std::sync::Arc;
use tokio::sync::Mutex;

/// Host que combina almacenamiento nativo (redb) + I/O devices.
pub struct NativeHost {
    pub storage: RedbHost,
    pub pid: i64,
    pub input: VecDeque<String>,
    pub empty_read: bool,
    pub lock_blocked: bool,
    /// Device 8 — HTTP client.
    pub http: HttpDevice,
    /// Device 9 — Webhook server. Shared queue para todos los jobs.
    pub webhook_queue: Arc<Mutex<VecDeque<WebhookMessage>>>,
    /// Dispositivo activo (copia de vm_state.current_io).
    pub current_io: i64,
    transaction_level: usize,
}

impl NativeHost {
    pub fn new(storage: RedbHost, pid: i64, webhook_queue: Arc<Mutex<VecDeque<WebhookMessage>>>) -> Self {
        Self {
            storage,
            pid,
            input: VecDeque::new(),
            empty_read: false,
            lock_blocked: false,
            http: HttpDevice::new(),
            webhook_queue,
            current_io: 0,
            transaction_level: 0,
        }
    }

    pub fn push_input(&mut self, value: String) {
        self.input.push_back(value);
    }

    /// Intenta resolver una operación de device (HTTP o webhook) si current_io lo indica.
    /// Devuelve true si se hizo algo (el job debe volver a WAITING/READY).
    pub fn try_device_read(&mut self) -> bool {
        match self.current_io {
            8 => {
                // Device 8: HTTP client — leer respuesta bufferizada
                if let Some(line) = self.http.read_line() {
                    self.input.push_back(line);
                    self.empty_read = false;
                    true
                } else {
                    false
                }
            }
            9 => {
                // Device 9: Webhook server — leer mensaje entrante
                // No podemos bloquear en async aquí, usamos try_lock
                if let Ok(mut queue) = self.webhook_queue.try_lock() {
                    if let Some(msg) = queue.pop_front() {
                        self.input.push_back(msg.body);
                        self.empty_read = false;
                        return true;
                    }
                }
                false
            }
            _ => false,
        }
    }
}

impl Host for NativeHost {
    fn get(&self, ns: &str, subs: &[Subscript]) -> Result<Option<Value>, String> {
        self.storage.get(ns, subs)
    }

    fn set(&mut self, ns: &str, subs: &[Subscript], value: Value) -> Result<(), String> {
        self.storage.set(ns, subs, value)
    }

    fn kill(&mut self, ns: &str, subs: &[Subscript]) -> Result<u64, String> {
        self.storage.kill(ns, subs)
    }

    fn data(&self, ns: &str, subs: &[Subscript]) -> Result<u8, String> {
        self.storage.data(ns, subs)
    }

    fn order(
        &self,
        ns: &str,
        parent: &[Subscript],
        current: Option<&Subscript>,
        direction: i32,
    ) -> Result<Option<Subscript>, String> {
        self.storage.order(ns, parent, current, direction)
    }

    fn transaction_start(&mut self) -> Result<(), String> {
        self.storage.transaction_start()?;
        self.transaction_level += 1;
        Ok(())
    }

    fn transaction_commit(&mut self) -> Result<(), String> {
        if self.transaction_level == 0 {
            return Err("TCOMMIT without TSTART".to_string());
        }
        self.storage.transaction_commit()?;
        self.transaction_level -= 1;
        Ok(())
    }

    fn transaction_rollback(&mut self) -> Result<(), String> {
        if self.transaction_level == 0 {
            return Err("TROLLBACK without TSTART".to_string());
        }
        self.storage.transaction_rollback()?;
        self.transaction_level -= 1;
        Ok(())
    }

    fn transaction_level(&self) -> usize {
        self.transaction_level
    }

    fn routine(&self, name: &str) -> Result<Option<String>, String> {
        self.storage.routine(name)
    }

    fn read(&mut self) -> Result<String, String> {
        if let Some(value) = self.input.pop_front() {
            return Ok(value);
        }
        self.empty_read = true;
        Ok(String::new())
    }

    fn read_would_block(&self) -> bool {
        self.empty_read
    }

    fn lock(
        &mut self,
        ns: &str,
        subs: &[Subscript],
        timeout: Option<f64>,
    ) -> Result<bool, String> {
        self.storage.lock(ns, subs, timeout)
    }

    fn unlock(&mut self, ns: &str, subs: &[Subscript]) -> Result<(), String> {
        self.storage.unlock(ns, subs)
    }

    fn unlock_all(&mut self) -> Result<(), String> {
        self.storage.unlock_all()
    }
}
