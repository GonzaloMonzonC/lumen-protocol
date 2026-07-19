//! S2: ResponseParser — parsea la salida del LLM en acciones.
//!
//! Detecta 4 tipos de bloque en la respuesta:
//! - ```m\\n<código>\\n``` → MCode (ejecutar en próximo tick)
//! - ```tool\\n<JSON>\\n``` → ToolCall (dispatch SHM → MCP)
//! - ```msg <dest>\\n<mensaje>\\n``` → SendMessage (^MAILBOX)
//! - Texto plano → Output (^OUTPUT)
//!
//! Regla crítica (spec v0.2): el MCode no se ejecuta en el mismo tick.
//! Se guarda en ^MEMORY y se ejecuta en el próximo tick.

use serde::{Deserialize, Serialize};

/// Acción resultante del parseo de la respuesta del LLM.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub enum AgentAction {
    /// Código M a ejecutar en el próximo tick.
    MCode { code: String },
    /// Tool call a dispatchear vía SHM al MCP server.
    ToolCall { tool: String, args: serde_json::Value },
    /// Mensaje a enviar a otro job (^MAILBOX).
    SendMessage { target: String, content: String },
    /// Texto plano para ^OUTPUT.
    Output { text: String },
}

/// Resultado del parseo.
#[derive(Debug)]
pub struct ParsedResponse {
    pub actions: Vec<AgentAction>,
    pub reasoning: String, // texto fuera de los bloques
}

pub struct ResponseParser;

impl ResponseParser {
    /// Parsea la respuesta completa del LLM.
    pub fn parse(response: &str) -> ParsedResponse {
        let mut actions = Vec::new();
        let mut reasoning = String::new();
        let mut in_block = false;
        let mut block_type = "";
        let mut block_content = String::new();
        let mut block_lines: Vec<&str> = Vec::new();

        for line in response.lines() {
            let trimmed = line.trim();

            if !in_block {
                if trimmed.starts_with("```msg") {
                    in_block = true;
                    block_type = "msg";
                    let rest = trimmed.replacen("```msg", "", 1).trim().to_string();
                    if !rest.is_empty() {
                        block_content = rest;
                    }
                    block_lines.clear();
                } else if trimmed.starts_with("```tool") {
                    in_block = true;
                    block_type = "tool";
                    block_content.clear();
                    block_lines.clear();
                } else if trimmed.starts_with("```m") || trimmed.starts_with("```M") {
                    in_block = true;
                    block_type = "m";
                    block_content = trimmed.replacen("```m", "", 1).replacen("```M", "", 1).trim().to_string();
                    if !block_content.is_empty() {
                        block_lines.push(&line[line.find('m').unwrap_or(3)+1..]);
                    }
                } else if trimmed.starts_with("```") {
                    // Cierre de bloque o bloque desconocido — tratar como texto
                    reasoning.push_str(line);
                    reasoning.push('\n');
                } else {
                    reasoning.push_str(line);
                    reasoning.push('\n');
                }
            } else {
                // Dentro de un bloque
                if trimmed == "```" {
                    // Fin del bloque
                    // Fin del bloque
                    in_block = false;
                    match block_type {
                        "m" => {
                            let cleaned = block_content.trim().to_string();
                            if !cleaned.is_empty() {
                                actions.push(AgentAction::MCode { code: cleaned });
                            }
                        }
                        "tool" => {
                            if let Ok(args) = serde_json::from_str::<serde_json::Value>(&block_content) {
                                let tool = args.get("tool").and_then(|t| t.as_str()).unwrap_or("unknown").to_string();
                                let tool_args = args.get("args").cloned().unwrap_or(serde_json::Value::Null);
                                actions.push(AgentAction::ToolCall { tool, args: tool_args });
                            }
                        }
                        "msg" => {
                            let parts: Vec<&str> = block_content.splitn(2, '\n').collect();
                            let target = parts[0].trim().to_string();
                            let content = if parts.len() > 1 { parts[1].trim().to_string() } else { String::new() };
                            if !target.is_empty() {
                                actions.push(AgentAction::SendMessage { target, content });
                            }
                        }
                        _ => {}
                    }
                    block_content.clear();
                    block_lines.clear();
                    block_type = "";
                } else {
                    if !block_content.is_empty() {
                        block_content.push('\n');
                    }
                    block_content.push_str(line);
                }
            }
        }

        // Bloque sin cerrar al final
        if in_block {
            match block_type {
                "m" => {
                    let cleaned = block_content.trim().to_string();
                    if !cleaned.is_empty() {
                        actions.push(AgentAction::MCode { code: cleaned });
                    }
                }
                _ => {
                    // Bloque sin cerrar — tratarlo como output
                    actions.push(AgentAction::Output { text: block_content });
                }
            }
        }

        // Si no hay acciones y hay reasoning, es output
        if actions.is_empty() && !reasoning.trim().is_empty() {
            actions.push(AgentAction::Output { text: reasoning.trim().to_string() });
            reasoning.clear();
        }

        ParsedResponse { actions, reasoning }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_parse_mcode_block() {
        let resp = "```m\nS ^X(\"test\")=42\nW \"done\"\n```";
        let parsed = ResponseParser::parse(resp);
        assert_eq!(parsed.actions.len(), 1);
        assert_eq!(parsed.actions[0], AgentAction::MCode { code: "S ^X(\"test\")=42\nW \"done\"".into() });
    }

    #[test]
    fn test_parse_tool_call() {
        let resp = "```tool\n{\"tool\":\"web_search\",\"args\":{\"query\":\"LUMEN protocol\"}}\n```";
        let parsed = ResponseParser::parse(resp);
        assert_eq!(parsed.actions.len(), 1);
        match &parsed.actions[0] {
            AgentAction::ToolCall { tool, args } => {
                assert_eq!(tool, "web_search");
                assert_eq!(args["query"], "LUMEN protocol");
            }
            _ => panic!("Expected ToolCall"),
        }
    }

    #[test]
    fn test_parse_msg() {
        let resp = "```msg job_8\nHola desde job 7\n```";
        let parsed = ResponseParser::parse(resp);
        println!("Actions: {:?}", parsed.actions);
        assert_eq!(parsed.actions.len(), 1);
        match &parsed.actions[0] {
            AgentAction::SendMessage { target, content } => {
                println!("target='{}', content='{}'", target, content);
                assert_eq!(target, "job_8");
                assert!(!content.is_empty());
            }
            other => panic!("Expected SendMessage, got {:?}", other),
        }
    }

    #[test]
    fn test_parse_output_fallback() {
        let resp = "No necesito hacer nada ahora.";
        let parsed = ResponseParser::parse(resp);
        assert_eq!(parsed.actions.len(), 1);
        match &parsed.actions[0] {
            AgentAction::Output { text } => assert!(text.contains("No necesito")),
            _ => panic!("Expected Output"),
        }
    }

    #[test]
    fn test_parse_mixed_response() {
        let resp = "Analizando...\n\n```tool\n{\"tool\":\"web_search\",\"args\":{\"query\":\"test\"}}\n```\n\nConclusión final.";
        let parsed = ResponseParser::parse(resp);
        assert_eq!(parsed.actions.len(), 1);
    }
}
