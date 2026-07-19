# 🤖 Building Your First Agent — LUMEN Rust Stack

> Step-by-step: compile, spawn, think, survive.

## 1. Compile

```bash
cd implementations/rust/lumen-mvm
cargo build --release
# Binary: target/release/lumen_mvm.dll (or .so)
```

## 2. Write Agent M Code

Create `my_agent.m`:

```m
AGENT
  ; ── My first agent ──
  D CHECK_MAILBOX
  F {
    D THINK
    I $TEST Q
  }
  Q

CHECK_MAILBOX
  S N=""
  F  S N=$O(^MAILBOX($J,N)) Q:N=""  D
  . S MSG=$G(^MAILBOX($J,N))
  . S ^MEMORY("self",$J,"last_msg")=MSG
  . KILL ^MAILBOX($J,N)
  Q

THINK
  S RESULT=$$THINK_INTERNAL()
  I RESULT="YIELD" Q
  I RESULT="HALT"  S $TEST=1 Q
  Q
```

The key line: `S RESULT=$$THINK_INTERNAL()` — this is the hook that the LlmHost intercepts.

## 3. Spawn via Rust API

```rust
use lumen_mvm::TokioMvm;
use lumen_mvm::host::CallbackBridge;

let mvm = TokioMvm::start(bridge)?;
let code = include_str!("my_agent.m");
let job_id = mvm.spawn("my-agent", code, 5000)?;

// Tick the agent
mvm.tick(job_id, 100)?; // gas=100
```

## 4. Connect to an LLM

```rust
use lumen_mvm::llm_engine::{HttpLlmEngine, LlmEngine};
use std::sync::Arc;

let engine = Arc::new(HttpLlmEngine::new(
    "https://api.openai.com/v1/chat/completions",
    "sk-your-key-here",
    "gpt-4o",
));

// Pass engine to scheduler
let mut scheduler = Scheduler::new(bridge, Some(engine), tx).await;
```

## 5. Expose a Webhook

```m
O 9:":8767"    ; start webhook server on port 8767
U 0 R           ; wait for POST
```

From another terminal:
```bash
curl -X POST http://localhost:8767/ -d '{"alert":"cpu"}'
```

The POST body arrives in the agent's mailbox.

## 6. Make an HTTP Call

```m
O 8:"GET https://api.github.com/repos/GonzaloMonzonC/lumen-protocol"
U 0 R           ; read response line by line
```

## 7. Survive Restart

```rust
// Agent state is in ^PROCESSES (RedbHost)
// On restart:
let mvm = TokioMvm::start(bridge)?;
// load_jobs() recovers all agents from disk
// They continue where they left off
```

## 8. The Full Stack

```
Agent M code
    │
    ▼
THINK_INTERNAL hook
    │
    ├── PromptBuilder: reads ^MEMORY + ^MAILBOX + ^MODELS
    │       │
    │       ▼
    ├── LlmEngine: HTTP POST to LLM API
    │       │
    │       ▼
    └── ResponseParser: ```m / ```tool / ```msg / text
            │
            ├── M code → ^MEMORY → execute next tick
            ├── Tool call → ToolDispatch → MCP → ^RESULT
            ├── Message → ^MAILBOX(target_job)
            └── Output → ^OUTPUT(pid)
```

## 9. Verify

```bash
# Run all tests
cargo test -- --nocapture

# Build release
cargo build --release

# Check: no Python in the binary
ldd target/release/lumen_mvm.dll | grep -i python  # should be empty
```

Done. You have a cognitive agent in pure Rust.
