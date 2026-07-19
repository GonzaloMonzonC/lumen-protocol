//! S2: LlmEngine trait + HttpLlmEngine (reqwest).
//!
//! El engine es el backend de inferencia. Recibe un prompt (string)
//! y devuelve la respuesta completa del LLM (string).
//! HttpLlmEngine hace POST a una API compatible con OpenAI.
//!
//! Uso:
//! ```ignore
//! let engine = HttpLlmEngine::new("https://api.openai.com/v1/chat/completions", "sk-...", "gpt-4o");
//! let response = engine.think("Eres un agente MUMPS. Responde:", "¿Qué es $ORDER?").await?;
//! ```

use async_trait::async_trait;
use serde::{Deserialize, Serialize};

/// Trait del engine de inferencia LLM.
/// Recibe un system prompt y un user prompt, devuelve la respuesta completa.
#[async_trait]
pub trait LlmEngine: Send + Sync {
    async fn think(&self, system: &str, user: &str) -> Result<String, String>;
}

/// Engine HTTP compatible con APIs OpenAI-like.
pub struct HttpLlmEngine {
    pub endpoint: String,
    pub api_key: String,
    pub model: String,
}

impl HttpLlmEngine {
    pub fn new(endpoint: &str, api_key: &str, model: &str) -> Self {
        Self {
            endpoint: endpoint.to_string(),
            api_key: api_key.to_string(),
            model: model.to_string(),
        }
    }
}

#[derive(Serialize)]
struct ChatRequest {
    model: String,
    messages: Vec<ChatMessage>,
    temperature: f64,
    max_tokens: u32,
}

#[derive(Serialize)]
struct ChatMessage {
    role: String,
    content: String,
}

#[derive(Deserialize)]
struct ChatResponse {
    choices: Vec<ChatChoice>,
}

#[derive(Deserialize)]
struct ChatChoice {
    message: ChatMessageContent,
}

#[derive(Deserialize)]
struct ChatMessageContent {
    content: String,
}

#[async_trait]
impl LlmEngine for HttpLlmEngine {
    async fn think(&self, system: &str, user: &str) -> Result<String, String> {
        let client = reqwest::Client::new();
        let req = ChatRequest {
            model: self.model.clone(),
            messages: vec![
                ChatMessage { role: "system".into(), content: system.to_string() },
                ChatMessage { role: "user".into(), content: user.to_string() },
            ],
            temperature: 0.2,
            max_tokens: 4096,
        };

        let resp = client
            .post(&self.endpoint)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(&req)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {}", e))?;

        let body: ChatResponse = resp
            .json()
            .await
            .map_err(|e| format!("JSON parse error: {}", e))?;

        body.choices
            .into_iter()
            .next()
            .map(|c| c.message.content)
            .ok_or_else(|| "No choices in response".to_string())
    }
}
