//! Device 8 — HTTP client nativo en Rust.
//! 
//! Uso M: O 8:"GET https://api.example.com"
//!         U 0 R
//! 
//! El HTTP se ejecuta async (tokio::spawn), el scheduler no se bloquea.
//! La respuesta se bufferiza y se entrega via R (READ).

use std::collections::VecDeque;

/// Estado del Device 8 para un job.
pub struct HttpDevice {
    /// Respuesta bufferizada, línea por línea (como M espera).
    pub buffer: VecDeque<String>,
    /// URL activa (si hay una request en vuelo).
    pub pending_url: Option<String>,
    /// Puerto del servidor webhook (Device 9) si está activo.
    pub webhook_port: Option<u16>,
}

impl HttpDevice {
    pub fn new() -> Self {
        Self {
            buffer: VecDeque::new(),
            pending_url: None,
            webhook_port: None,
        }
    }

    /// Procesa O 8:"<method> <url>"
    pub fn open(&mut self, args: &str) {
        let parts: Vec<&str> = args.splitn(2, ' ').collect();
        let _method = if parts.len() == 2 { parts[0].to_uppercase() } else { "GET".to_string() };
        let url = if parts.len() == 2 { parts[1].to_string() } else { args.to_string() };

        self.pending_url = Some(url.clone());

        // La llamada HTTP real se hace desde tokio::spawn en el tick del scheduler.
        // Aquí solo registramos la intención.
        // El resultado se inyecta via self.buffer cuando llega.
    }

    /// Devuelve la siguiente línea del buffer (para R).
    pub fn read_line(&mut self) -> Option<String> {
        self.buffer.pop_front()
    }

    /// Inyecta una respuesta HTTP en el buffer.
    pub fn inject_response(&mut self, body: &str) {
        for line in body.lines() {
            self.buffer.push_back(line.to_string());
        }
    }
}

impl Default for HttpDevice {
    fn default() -> Self {
        Self::new()
    }
}
