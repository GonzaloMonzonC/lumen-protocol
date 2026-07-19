# 🏗️ LUMEN Protocol — Architecture

> **Last updated:** 2026-07-19
> **Status:** S1-S4 complete. OS cognitivo funcional en Rust puro.

---

## Layer stack

```
┌─────────────────────────────────────────────────┐
│              Agent Loop (M code)                 │  ← CHECK_MAILBOX → THINK → YIELD
├─────────────────────────────────────────────────┤
│  Cognitive Layer                                │
│  ┌──────────┬─────────────┬──────────────────┐  │
│  │ LlmEngine│PromptBuilder│ResponseParser    │  │
│  │ (HTTP)   │(^GLOBALS)   │(```m/```tool/msg)│  │
│  └──────────┴─────────────┴──────────────────┘  │
├─────────────────────────────────────────────────┤
│  Tool Layer                                     │
│  ┌──────────────────────────────────────────┐   │
│  │         ToolDispatch (mpsc channel)       │   │  ← non-blocking SHM substitute
│  └──────────────────────────────────────────┘   │
├─────────────────────────────────────────────────┤
│  I/O Layer                                      │
│  ┌──────────────┬──────────────────────────┐    │
│  │ Device 8     │ Device 9                 │    │
│  │ HTTP client  │ Webhook server (axum)    │    │
│  │ (reqwest)    │                          │    │
│  └──────────────┴──────────────────────────┘    │
├─────────────────────────────────────────────────┤
│  Scheduling Layer                               │
│  ┌──────────────────────────────────────────┐   │
│  │         TokioMvm (JobActor × N)          │   │
│  │  States: READY → RUNNING → WAITING/BLOCKED   │
│  │  WAITING: back-off 100ms, mailbox wake-up    │
│  └──────────────────────────────────────────┘   │
├─────────────────────────────────────────────────┤
│  VM Layer                                       │
│  ┌──────────────────────────────────────────┐   │
│  │       M-Light VM (Rust)                  │   │
│  │  Opcodes: SET, GET, KILL, ORDER, DATA,   │   │
│  │  FOR, IF, DO, OPEN, USE, READ, WRITE     │   │
│  └──────────────────────────────────────────┘   │
├─────────────────────────────────────────────────┤
│  Storage Layer                                  │
│  ┌──────────────────────────────────────────┐   │
│  │       PDB (redb, pure Rust)              │   │
│  │  ^GLOBALS: hierarchical KV, $ORDER,      │   │
│  │  transactions (TSTART/TCOMMIT), locks    │   │
│  └──────────────────────────────────────────┘   │
└─────────────────────────────────────────────────┘
```

---

## Crates

### `lumen-m-light` — M-Light VM
**Path:** `implementations/rust/lumen-m-light/`

| Module | Lines | Purpose |
|--------|------:|---------|
| `vm.rs` | 1,535 | Virtual machine: opcode dispatch, execution context, state management |
| `compiler.rs` | 258 | M code → bytecode compiler (labels, instructions) |
| `value.rs` | 145 | M value types: Null, Bool, Number, String, Array, Object |
| `host.rs` | 237 | Host trait: GET, SET, KILL, DATA, ORDER, READ, WRITE, LOCK, transactions |
| `ffi.rs` | 219 | C FFI bindings (Python bridge) |
| `ddp.rs` | 62 | DDP protocol: pull/push, journal |
| `wasm.rs` | 115 | WASM compilation target |

**Tests:** `golden.rs` (247), `lock_funcs.rs` (223)

### `lumen-pdb` — Native Storage (redb)
**Path:** `implementations/rust/lumen-pdb/`

| Module | Lines | Purpose |
|--------|------:|---------|
| `host.rs` | 334 | `RedbHost`: implements Host trait on redb (pure Rust, no Python) |
| `globals.rs` | 373 | Global storage: SET, GET, KILL, ORDER, DATA on redb tables |
| `subkey.rs` | 162 | M subscript encoding/decoding |
| `ffi.rs` | 345 | C FFI for Python bridge |

**Dependency:** redb (pure Rust embedded database, 0 bytes FFI)

### `lumen-mvm` — Tokio Scheduler + Cognitive OS
**Path:** `implementations/rust/lumen-mvm/`

| Module | Lines | Purpose |
|--------|------:|---------|
| `lib.rs` | 1,102 | `TokioMvm`: scheduler, JobActor, spawn/kill/tick, persist, WAITING, BLOCKED |
| `host.rs` | 255 | `LiveHost`: Python bridge + Device 8/9 buffers + HTTP receiver |
| `llm_engine.rs` | 103 | `LlmEngine` trait + `HttpLlmEngine` (reqwest → OpenAI API) |
| `prompt_builder.rs` | 240 | `PromptBuilder v0.2`: ^GLOBALS → LLM prompt (10 mailbox, 20 memory, 1 model level) |
| `response_parser.rs` | 205 | `ResponseParser`: LLM output → ```m / ```tool / ```msg / text |
| `tool_dispatch.rs` | 133 | `ToolDispatcher`: non-blocking tool calls via mpsc channel (SHM substitute) |
| `agent_loop.rs` | 66 | Canonical M agent code: CHECK_MAILBOX → THINK → YIELD |
| `device8.rs` | 60 | Device 8: HTTP client buffer (reqwest dispatch) |
| `device9.rs` | 99 | Device 9: Webhook server (axum + shared queue) |
| `native_host.rs` | 166 | `NativeHost`: RedbHost + Device 8 + Device 9 (no Python FFI) |
| `ffi.rs` | 81 | C FFI entry points |

**Tests:** `device8_integration.rs` (73), `device9_integration.rs` (72), `s4_agent_e2e.rs` (127)

### `lumen-shm` — LUMEN Binary Protocol
**Path:** `implementations/rust/src/`

| Module | Lines | Purpose |
|--------|------:|---------|
| `frame.rs` | 836 | LUMEN wire format: framing, types, serialization |
| `shm.rs` | 655 | Shared memory transport (zero-copy, mmap ring buffers) |
| `stream.rs` | 911 | Stream transport |
| `mux.rs` | 657 | Multiplexer: channels, flow control |
| `handshake.rs` | 577 | Protocol handshake: version negotiation, capabilities |
| `quic.rs` | 655 | QUIC transport (multi-node) |
| `compress.rs` | 627 | Wire compression (55-80%) |
| `datagram.rs` | 390 | Datagram transport |
| `crypto.rs` | 683 | Encryption: Hyb128, key exchange |
| `macaroon.rs` | 675 | Macaroon-based auth tokens |
| `dict.rs` | 812 | Dictionary encoding |
| `hyb128.rs` | 297 | Hyb128 AEAD cipher |
| `transport.rs` | 149 | Transport abstraction |
| `wasm.rs` | 96 | WASM bindings |

---

## Data flow: Agent think cycle

```
┌──────────┐    ┌──────────────┐    ┌──────────────┐
│ ^GLOBALS │───→│PromptBuilder │───→│  LlmEngine   │
│ MEMORY   │    │  (system+user)│    │  (HTTP POST) │
│ MAILBOX  │    └──────────────┘    └──────┬───────┘
│ MODELS   │                              │
└──────────┘                              ▼
                                    ┌──────────────┐
                                    │ LLM Response │
                                    └──────┬───────┘
                                           │
                                    ┌──────▼───────┐
                                    │ResponseParser│
                                    │ ```m/```tool │
                                    │ /```msg/text │
                                    └──────┬───────┘
                                           │
                          ┌────────────────┼────────────────┐
                    ┌─────▼─────┐  ┌──────▼──────┐  ┌──────▼──────┐
                    │ ^MEMORY   │  │ ToolDispatch│  │  ^MAILBOX   │
                    │ (next tick│  │  (SHM → MCP)│  │  (other job)│
                    │  execute) │  └─────────────┘  └─────────────┘
                    └───────────┘
```

---

## Agent lifecycle

```
  SPAWN ──→ READY ──→ RUNNING ──┬──→ READY (yield)
                                 ├──→ WAITING (empty_read, back-off 100ms)
                                 │    └──→ mailbox msg → READY (wake-up)
                                 ├──→ BLOCKED (lock contention)
                                 └──→ DEAD (halt/error/completed)
```

Jobs persist in `^PROCESSES` via RedbHost. On restart, `Scheduler::new()` loads all jobs from PDB.

---

## Test matrix (15 tests, all passing)

| Test | What it verifies |
|------|-----------------|
| `s1_persistence` (2) | S ^X → kill → restart → $G = original |
| `device8_integration` (2) | HTTP dispatch + buffer R |
| `device9_integration` (2) | Webhook server + POST receive |
| `prompt_builder` (2) | Empty prompt + format instructions |
| `response_parser` (5) | MCode, ToolCall, Msg, Output, Mixed |
| `tool_dispatch` (2) | Non-blocking dispatch + cached results |
| `agent_loop` (2) | Agent code compiles + THINK_INTERNAL |
| `s4_agent_e2e` (3) | Webhook flow + persistence across restart |

---

## What this enables (that Python-only couldn't)

1. **Zero-copy storage**: RedbHost reads/writes ^GLOBALS directly from Rust, no FFI roundtrip
2. **Non-blocking I/O**: Device 8 HTTP calls dispatch via tokio::spawn, scheduler keeps ticking
3. **Native webhooks**: Device 9 axum server on any port, POSTs arrive in job mailbox
4. **LLM-native**: HttpLlmEngine talks to any OpenAI-compatible API from Rust
5. **Prompt from state**: PromptBuilder reads ^MEMORY, ^MAILBOX, ^MODELS with $ORDER limits
6. **Structured parsing**: ResponseParser extracts M code, tool calls, messages, and output
7. **Tool dispatch**: Non-blocking tool execution via mpsc → MCP bridge
8. **Agent persistence**: Jobs survive crashes, reanimate from ^PROCESSES on restart
9. **Single binary**: `cargo build --release` produces one .dll/.so with everything
10. **Testable**: 15 unit/integration tests, all Rust, no Python mock needed
