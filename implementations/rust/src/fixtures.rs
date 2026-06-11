//! Realistic fixtures for LUMEN benchmarks.
//!
//! Uses real-world patterns (tool definitions, source code, LLM responses)
//! rather than random bytes to ensure compression ratios reflect actual usage.

use serde_json::{json, Value};

// ── Scenario 1: tools/list ──────────────────────────────────────────────────

/// Generates N realistic MCP tool definitions.
/// Each tool has a name, description, and inputSchema with properties.
pub fn generate_tools(n: usize) -> Vec<Value> {
    let tool_templates = [
        ("search_code", "Search for code patterns in the workspace using regex or semantic queries", &[
            ("query", "string", "The search query or pattern"),
            ("path", "string", "Optional path to scope the search"),
            ("max_results", "integer", "Maximum number of results to return"),
        ][..]),
        ("read_file", "Read the contents of a file from the filesystem", &[
            ("uri", "string", "URI of the file to read"),
            ("start_line", "integer", "Starting line number (1-based)"),
            ("end_line", "integer", "Ending line number (inclusive)"),
        ][..]),
        ("write_file", "Write content to a file, creating directories if needed", &[
            ("path", "string", "Absolute path to the target file"),
            ("content", "string", "Content to write to the file"),
            ("overwrite", "boolean", "Whether to overwrite existing files"),
        ][..]),
        ("execute_command", "Execute a shell command in the terminal", &[
            ("command", "string", "The command to execute"),
            ("working_dir", "string", "Working directory for execution"),
            ("timeout_ms", "integer", "Timeout in milliseconds"),
        ][..]),
        ("list_directory", "List contents of a directory with optional filtering", &[
            ("path", "string", "Absolute path to the directory"),
            ("pattern", "string", "Glob pattern for filtering"),
            ("recursive", "boolean", "Whether to list recursively"),
        ][..]),
        ("get_diagnostics", "Retrieve compiler and linter errors from the workspace", &[
            ("file_path", "string", "Optional file path to scope diagnostics"),
            ("severity", "string", "Filter by severity: error, warning, info"),
        ][..]),
        ("semantic_search", "Search the codebase using natural language understanding", &[
            ("query", "string", "Natural language description of what to find"),
            ("top_k", "integer", "Number of results to return"),
            ("include_comments", "boolean", "Whether to include comments in search"),
        ][..]),
        ("create_rule", "Create or update a project rule or coding standard", &[
            ("name", "string", "Name of the rule"),
            ("description", "string", "What the rule enforces"),
            ("severity", "string", "Rule severity: error, warning, info, hint"),
            ("pattern", "string", "Regex pattern for the rule"),
        ][..]),
        ("manage_memory", "Store, retrieve, and update persistent memory across sessions", &[
            ("operation", "string", "Memory operation: view, create, update, delete"),
            ("path", "string", "Path within the memory namespace"),
            ("content", "string", "Content for create/update operations"),
        ][..]),
        ("fetch_webpage", "Fetch and extract content from web pages", &[
            ("urls", "array", "Array of URLs to fetch"),
            ("query", "string", "Information to extract from the pages"),
        ][..]),
    ];

    let mut tools = Vec::with_capacity(n);
    for i in 0..n {
        let (name, desc, props) = &tool_templates[i % tool_templates.len()];
        let variant = i / tool_templates.len();
        let tool_name = if variant > 0 {
            format!("{}_{}", name, variant)
        } else {
            name.to_string()
        };

        let properties: Value = props
            .iter()
            .map(|(pname, ptype, pdesc)| {
                (
                    pname.to_string(),
                    json!({
                        "type": ptype,
                        "description": pdesc
                    }),
                )
            })
            .collect();

        tools.push(json!({
            "name": tool_name,
            "description": format!("{} (variant {})", desc, variant + 1),
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": [props[0].0]
            }
        }));
    }
    tools
}

/// Builds the full MCP tools/list response.
pub fn build_tools_list_response(tools: &[Value]) -> Value {
    json!({
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "tools": tools
        }
    })
}

// ── Scenario 2: file_context ────────────────────────────────────────────────

/// Generates realistic source code content for a file.
/// Uses patterns found in real Rust/TypeScript projects.
pub fn generate_source_code(language: &str, size_kb: usize) -> String {
    let mut code = String::with_capacity(size_kb * 1024);

    // Header
    code.push_str(&format!(
        "// {} file: generated for benchmark\n",
        match language {
            "rust" => "Rust",
            "typescript" => "TypeScript",
            "python" => "Python",
            _ => language,
        }
    ));

    let snippets = match language {
        "rust" => RUST_SNIPPETS,
        "typescript" => TS_SNIPPETS,
        _ => GENERIC_SNIPPETS,
    };

    let mut i = 0;
    while code.len() < size_kb * 1024 {
        code.push_str(snippets[i % snippets.len()]);
        code.push('\n');
        i += 1;
    }
    code.truncate(size_kb * 1024);
    code
}

const RUST_SNIPPETS: &[&str] = &[
    "pub async fn handle_request(&self, req: LumenRequest) -> Result<LumenResponse, LumenError> {",
    "    let start = std::time::Instant::now();",
    "    let payload = self.decode_frame(&req.payload)?;",
    "    match req.frame_type {",
    "        TYPE_REQUEST => self.dispatch_tool_call(payload).await,",
    "        TYPE_DISCOVER => Ok(self.build_schema_response()),",
    "        _ => Err(LumenError::UnknownFrameType(req.frame_type)),",
    "    }",
    "}",
    "struct ToolRegistry {",
    "    tools: HashMap<u8, Box<dyn ToolHandler>>,",
    "    dict_version: u16,",
    "    capabilities: Vec<Capability>,",
    "}",
    "impl FrameParser {",
    "    fn parse_header(bytes: &[u8]) -> Result<(u64, u8, u8), ParseError> {",
    "        let decoded = hyb128::decode(bytes).ok_or(ParseError::Truncated)?;",
    "        let ty = bytes[decoded.header_len];",
    "        let flags = bytes[decoded.header_len + 1];",
    "        Ok((decoded.value, ty, flags))",
    "    }",
    "}",
];

const TS_SNIPPETS: &[&str] = &[
    "export class LumenClient implements Transport {",
    "  private buffer: Uint8Array;",
    "  private offset: number = 0;",
    "  ",
    "  async connect(path: string): Promise<void> {",
    "    this.socket = await Deno.connect({ path, transport: 'unix' });",
    "    await this.handshake();",
    "  }",
    "  ",
    "  feed(data: Uint8Array): Frame[] {",
    "    const frames: Frame[] = [];",
    "    this.buffer = concat(this.buffer, data);",
    "    while (this.offset < this.buffer.length) {",
    "      const result = parseFrame(this.buffer.subarray(this.offset));",
    "      if (result === 'incomplete') break;",
    "      frames.push(result);",
    "      this.offset += result.consumed;",
    "    }",
    "    return frames;",
    "  }",
    "}",
];

const GENERIC_SNIPPETS: &[&str] = &[
    "def process_batch(items: list[dict]) -> dict:",
    "    results = {}",
    "    for item in items:",
    "        results[item['id']] = transform(item)",
    "    return results",
    "class BaseAgent:",
    "    def __init__(self, name: str, capabilities: list[str]):",
    "        self.name = name",
    "        self.capabilities = capabilities",
    "        self.tools: dict[str, Callable] = {}",
    "",
];

/// Builds a file context payload (simulating sending files to an LLM).
pub fn build_file_context_payload(files: &[(String, String)]) -> Value {
    let resources: Vec<Value> = files
        .iter()
        .map(|(path, content)| {
            json!({
                "uri": format!("file://{}", path),
                "mimeType": "text/plain",
                "text": content
            })
        })
        .collect();

    json!({
        "jsonrpc": "2.0",
        "id": 42,
        "result": {
            "resources": resources
        }
    })
}

// ── Scenario 3: token_stream ────────────────────────────────────────────────

/// Generates realistic LLM token text (like what a model would emit).
pub fn generate_llm_tokens(count: usize) -> Vec<String> {
    let tokens = [
        "The", " function", " takes", " a", " parameter", " and", " returns",
        " the", " result", " of", " processing", " the", " input", " data",
        " through", " a", " series", " of", " transformations", ".",
        " Each", " step", " validates", " the", " intermediate", " state",
        " before", " proceeding", " to", " ensure", " correctness", ".",
        "\n", "```", "rust", "fn", " main", "()", " {", "}", "```",
        "let", "mut", "vec", "=", "Vec", "::", "new", "();",
        "use", "std", "::", "collections", "::", "HashMap", ";",
        "impl", "Iterator", "for", "struct", "enum", "trait", "where",
        "async", "await", "match", "if", "else", "loop", "return",
        "error", "ok", "some", "none", "true", "false", "null",
        "import", "export", "default", "const", "type", "interface",
        "class", "extends", "implements", "private", "public", "static",
    ];

    let mut result = Vec::with_capacity(count);
    for i in 0..count {
        result.push(tokens[i % tokens.len()].to_string());
    }
    result
}

// ── Scenario 4: multi_agent ─────────────────────────────────────────────────

/// Generates a batch of tool call requests (simulating multi-agent orchestration).
pub fn generate_agent_requests(agent_count: usize, requests_per_agent: usize) -> Vec<Value> {
    let methods = [
        ("tools/call", "search_code"),
        ("tools/call", "read_file"),
        ("tools/call", "list_directory"),
        ("tools/call", "semantic_search"),
        ("resources/read", ""),
        ("prompts/get", ""),
        ("tools/list", ""),
        ("resources/list", ""),
        ("logging/setLevel", ""),
        ("sampling/createMessage", ""),
    ];

    let mut requests = Vec::with_capacity(agent_count * requests_per_agent);

    for agent in 0..agent_count {
        for req in 0..requests_per_agent {
            let method_idx = (agent * requests_per_agent + req) % methods.len();
            let (method, tool) = &methods[method_idx];

            let mut req_json = json!({
                "jsonrpc": "2.0",
                "id": agent * 10000 + req,
                "method": method,
                "params": {}
            });

            if !tool.is_empty() {
                req_json["params"] = json!({
                    "name": tool,
                    "arguments": {
                        "query": format!("agent_{}_req_{}", agent, req),
                        "path": format!("/home/user/project/src/module_{}", agent),
                        "max_results": 10
                    }
                });
            }

            requests.push(req_json);
        }
    }
    requests
}

// ── Scenario 5: heartbeat ───────────────────────────────────────────────────

/// Heartbeat payload (minimal overhead test).
pub fn build_heartbeat() -> Value {
    json!({
        "jsonrpc": "2.0",
        "method": "notifications/heartbeat",
        "params": { "timestamp": 1700000000000u64 }
    })
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn tools_generation_is_deterministic() {
        let tools1 = generate_tools(100);
        let tools2 = generate_tools(100);
        assert_eq!(tools1.len(), tools2.len());
        assert_eq!(tools1[0]["name"], tools2[0]["name"]);
    }

    #[test]
    fn tools_have_required_fields() {
        let tools = generate_tools(50);
        for tool in &tools {
            assert!(tool["name"].is_string());
            assert!(tool["description"].is_string());
            assert!(tool["inputSchema"]["properties"].is_object());
        }
    }

    #[test]
    fn source_code_generates_correct_size() {
        for size in &[1, 10, 100] {
            let code = generate_source_code("rust", *size);
            assert!(
                code.len() >= (size * 1024) - 50,
                "size={}, len={}",
                size,
                code.len()
            );
            assert!(
                code.len() <= size * 1024,
                "size={}, len={}",
                size,
                code.len()
            );
        }
    }

    #[test]
    fn llm_tokens_generation() {
        let tokens = generate_llm_tokens(1000);
        assert_eq!(tokens.len(), 1000);
        // Verify realistic: first few tokens are English words
        assert_eq!(tokens[0], "The");
        assert_eq!(tokens[1], " function");
    }
}
