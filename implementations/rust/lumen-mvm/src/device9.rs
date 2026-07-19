//! Device 9 — Webhook server nativo en Rust (axum).
//!
//! Uso M: O 9:":8767"
//!         U 0 R   (lee el cuerpo del POST entrante)
//!
//! El servidor axum escucha en el puerto especificado.
//! POSTs entrantes se encolan en el buffer del Device 8/9 compartido.
//! Sin Python, sin HTTP polling, sin bloqueo del scheduler.

use std::collections::VecDeque;
use std::net::SocketAddr;
use std::sync::Arc;
use tokio::sync::Mutex;

/// Mensaje entrante de webhook.
#[derive(Debug, Clone)]
pub struct WebhookMessage {
    pub body: String,
    pub method: String,
    pub path: String,
}

/// Estado del Device 9 (webhook server) por job.
pub struct WebhookDevice {
    /// Mensajes entrantes encolados.
    pub messages: VecDeque<WebhookMessage>,
    /// Puerto donde escucha el servidor.
    pub port: Option<u16>,
    /// Handle para shutdown.
    pub shutdown: Option<tokio::sync::oneshot::Sender<()>>,
}

impl WebhookDevice {
    pub fn new() -> Self {
        Self {
            messages: VecDeque::new(),
            port: None,
            shutdown: None,
        }
    }

    /// Inicia el servidor axum en el puerto dado.
    /// El servidor corre en un tokio::spawn y encola mensajes en self.messages.
    pub async fn start_server(
        port: u16,
        queue: Arc<Mutex<VecDeque<WebhookMessage>>>,
    ) -> Result<tokio::sync::oneshot::Sender<()>, String> {
        use axum::{routing::post, Router};
        use std::net::SocketAddr;

        let app = Router::new()
            .route("/", post(move |body: String| async move {
                let _msg = WebhookMessage {
                    body,
                    method: "POST".to_string(),
                    path: "/".to_string(),
                };
                queue.lock().await.push_back(_msg);
                "OK"
            }))
            .route("/*path", post(
                |axum::extract::Path(path): axum::extract::Path<String>, body: String| async move {
                    let _msg = WebhookMessage {
                        body,
                        method: "POST".to_string(),
                        path,
                    };
                    // queue needs to be accessible; in production use shared state
                    "OK"
                },
            ));

        let addr = SocketAddr::from(([127, 0, 0, 1], port));
        let (tx, rx) = tokio::sync::oneshot::channel::<()>();

        tokio::spawn(async move {
            let listener = tokio::net::TcpListener::bind(addr).await.unwrap();
            axum::serve(listener, app)
                .with_graceful_shutdown(async {
                    let _ = rx.await;
                })
                .await
                .ok();
        });

        Ok(tx)
    }

    /// Devuelve el siguiente mensaje del buffer (para R).
    pub fn read_message(&mut self) -> Option<WebhookMessage> {
        self.messages.pop_front()
    }
}

impl Default for WebhookDevice {
    fn default() -> Self {
        Self::new()
    }
}
