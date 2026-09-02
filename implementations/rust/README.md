# 🦀 LUMEN Protocol — Rust Implementation

> **Status:** S1-S4 complete (July 2026). OS cognitivo funcional en Rust puro.

## Quick Start

```bash
cd implementations/rust/lumen-mvm
cargo build --release    # compile
cargo test               # 15 tests
cargo check              # fast lint
```

## Crates

| Crate | Path | Purpose |
|-------|------|---------|
| `lumen-m-light` | `lumen-m-light/` | M Language VM: compiler, opcodes, types, $ORDER, $GET, FOR, IF, DO |
| `lumen-pdb` | `lumen-pdb/` | Native storage (redb): ^GLOBALS, transactions (TSTART/TCOMMIT), locks |
| `lumen-mvm` | `lumen-mvm/` | Tokio scheduler + Cognitive OS: JobActor, LlmEngine, PromptBuilder, Tools, Agent Loop |

## Architecture

See [ARCHITECTURE.md](../../ARCHITECTURE.md) for the full layer diagram, data flow, and test matrix.

## Modules in `lumen-mvm` (the cognitive OS)

| Module | Lines | What it does |
|--------|------:|--------------|
| `lib.rs` | 1,330 | TokioMvm: scheduler, JobActor, spawn/kill/tick, WAITING/BLOCKED states |
| `host.rs` | 277 | LiveHost: Python bridge + HTTP/webhook device buffers |
| `llm_engine.rs` | 103 | LlmEngine trait + HttpLlmEngine (OpenAI API) |
| `prompt_builder.rs` | 240 | Builds LLM prompt from ^GLOBALS ($ORDER limits) |
| `response_parser.rs` | 205 | Parses LLM output → M code / tool calls / messages |
| `tool_dispatch.rs` | 133 | Non-blocking tool calls via mpsc channels |
| `agent_loop.rs` | 66 | Canonical M agent code |
| `device8.rs` | 60 | HTTP client device (reqwest) |
| `device9.rs` | 99 | Webhook server device (axum) |
| `native_host.rs` | 166 | NativeHost: RedbHost + Device 8 + Device 9 |

## Tests

```bash
# All tests (15 pass)
cargo test -- --nocapture

# Specific test
cargo test test_device8_http_dispatch -- --nocapture
cargo test --test s4_agent_e2e -- --nocapture
```

All tests are pure Rust. No Python mock required. No network needed (except device8 test which calls httpbin.org).

## Dependencies

- **redb** — pure Rust embedded database (^GLOBALS)
- **tokio** — async runtime (scheduler, HTTP, webhooks)
- **reqwest** — HTTP client (Device 8, LlmEngine)
- **axum** — HTTP server (Device 9 webhook)
- **serde / serde_json** — serialization (job state, tool calls)
- **async-trait** — async trait support (LlmEngine)

Zero Python dependencies in the Rust path.

## Building Agents

See [AGENT_GUIDE.md](../../AGENT_GUIDE.md) for a step-by-step guide.
