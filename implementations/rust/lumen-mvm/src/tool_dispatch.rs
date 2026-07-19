//! S3: Tool Dispatch via message passing (SHM substitute).
//!
//! Cuando el LLM genera ```tool, el dispatcher envía la tool call
//! de forma no bloqueante (mpsc channel → MCP handler → resultado).
//!
//! En producción, esto usaría LUMEN SHM (shared memory). Para el MVP,
//! usamos un channel tokio mpsc que simula SHM.

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::{mpsc, oneshot, Mutex};

/// Solicitud de tool call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolRequest {
    pub tool: String,
    pub args: serde_json::Value,
}

/// Resultado de una tool call.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolResponse {
    pub tool: String,
    pub result: String,
    pub success: bool,
}

/// Handler de tool calls (trait para mock/testing).
#[async_trait::async_trait]
pub trait ToolHandler: Send + Sync {
    async fn handle(&self, request: ToolRequest) -> ToolResponse;
}

/// Dispatcher: envía tool calls y recibe respuestas.
pub struct ToolDispatcher {
    tx: mpsc::Sender<(ToolRequest, oneshot::Sender<ToolResponse>)>,
    /// Resultados pendientes: tool_name → response
    pending: Arc<Mutex<HashMap<String, ToolResponse>>>,
}

impl ToolDispatcher {
    /// Crea un dispatcher con un handler en background.
    pub fn new(handler: Arc<dyn ToolHandler>) -> Self {
        let (tx, mut rx) = mpsc::channel::<(ToolRequest, oneshot::Sender<ToolResponse>)>(64);
        let pending = Arc::new(Mutex::new(HashMap::new()));
        let pending_clone = pending.clone();

        // Worker: procesa tool calls en background (sin bloquear el scheduler)
        tokio::spawn(async move {
            while let Some((req, reply)) = rx.recv().await {
                let resp = handler.handle(req.clone()).await;
                let tool_name = req.tool.clone();
                let _ = reply.send(resp.clone());
                // También guardar en resultados pendientes
                pending_clone.lock().await.insert(tool_name, resp);
            }
        });

        Self { tx, pending }
    }

    /// Envía una tool call (no bloqueante).
    pub async fn dispatch(&self, request: ToolRequest) -> Result<ToolResponse, String> {
        let (reply_tx, reply_rx) = oneshot::channel();
        self.tx
            .send((request, reply_tx))
            .await
            .map_err(|_| "Tool dispatcher stopped".to_string())?;
        reply_rx
            .await
            .map_err(|_| "Tool handler dropped".to_string())
    }

    /// Intenta obtener un resultado pendiente (no bloqueante).
    pub fn try_get_result(&self, tool_name: &str) -> Option<ToolResponse> {
        // try_lock para no bloquear el scheduler
        self.pending.try_lock().ok()?.get(tool_name).cloned()
    }
}

/// Mock tool handler para tests.
pub struct MockToolHandler;

#[async_trait::async_trait]
impl ToolHandler for MockToolHandler {
    async fn handle(&self, request: ToolRequest) -> ToolResponse {
        ToolResponse {
            tool: request.tool.clone(),
            result: format!("mocked response for {}", request.tool),
            success: true,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::sync::Arc;

    #[tokio::test]
    async fn test_tool_dispatch_non_blocking() {
        let handler = Arc::new(MockToolHandler);
        let dispatcher = ToolDispatcher::new(handler);

        let req = ToolRequest {
            tool: "web_search".into(),
            args: serde_json::json!({"query": "LUMEN protocol"}),
        };

        let resp = dispatcher.dispatch(req).await.unwrap();
        assert!(resp.success);
        assert_eq!(resp.tool, "web_search");
    }

    #[tokio::test]
    async fn test_tool_dispatch_pending_results() {
        let handler = Arc::new(MockToolHandler);
        let dispatcher = ToolDispatcher::new(handler);

        let req = ToolRequest {
            tool: "get_file".into(),
            args: serde_json::json!({"path": "/tmp/test"}),
        };

        let _resp = dispatcher.dispatch(req).await.unwrap();

        // try_get_result should have the cached response
        let cached = dispatcher.try_get_result("get_file");
        assert!(cached.is_some());
        assert_eq!(cached.unwrap().tool, "get_file");
    }
}
