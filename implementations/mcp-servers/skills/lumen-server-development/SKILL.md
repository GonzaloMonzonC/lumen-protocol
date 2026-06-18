---
name: lumen-server-development
description: How to build, test, and deploy LUMEN MCP servers. Covers JSON-RPC wrapper pattern, LUMEN native pattern, pitfall checklist, benchmarking, and Hermes integration.
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, mcp, server, development]
---

# LUMEN MCP Server Development

Canonical guide for building MCP servers that speak LUMEN binary protocol.
Reference implementations live at `lumen-protocol/implementations/mcp-servers/`.

---

## Two Server Patterns

### Pattern A: JSON-RPC + LUMEN Wrapper (`server.py`)

The server speaks standard JSON-RPC over stdio. Hermes wraps it in LUMEN frames
via `transport: lumen` + `lumen_force_json_rpc: true`. The server doesn't know
about LUMEN at all.

**When to use**: quick development, debugging, compatibility with non-LUMEN clients.

```python
# Minimal skeleton
import sys, json

def main():
    while True:
        line = sys.stdin.readline()
        if not line: break
        msg = json.loads(line.strip())
        method = msg.get("method")
        req_id = msg.get("id")
        
        if method == "initialize":
            response = {"jsonrpc":"2.0","id":req_id,"result":{
                "protocolVersion":"2025-03-26",
                "capabilities":{"tools":{}},
                "serverInfo":{"name":"my-server","version":"1.0"}
            }}
        elif method == "tools/list":
            response = {"jsonrpc":"2.0","id":req_id,"result":{"tools":TOOLS}}
        elif method == "tools/call":
            params = msg.get("params",{})
            # ... dispatch to handler
            response = {"jsonrpc":"2.0","id":req_id,"result":result}
        
        sys.stdout.write(json.dumps(response)+"\n")
        sys.stdout.flush()
```

Hermes config:
```yaml
mcp_servers:
  my_server:
    command: "python"
    args: ["server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

**Wire savings**: 32-60% (LUMEN compresses the JSON-RPC wrapper).

### Pattern B: LUMEN Native (`server_native.py`)

The server reads/writes LUMEN binary frames directly. No JSON-RPC text wrapping.
Uses `build_frame()` / `parse_frame()` / `compress_value()` / `decompress_value()`.

**When to use**: maximum performance, MUX channels, STREAM_DATA, pure binary protocol.

```python
from lumen import (
    build_frame, parse_frame, compress_value, decompress_value,
    TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED, ParseComplete, build_size
)

# Sending a response:
payload = compress_value(response_dict)
buf = bytearray(build_size(len(payload)))  # build_size() returns total wire size (fixed June 2026)
build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
sys.stdout.buffer.write(buf)
sys.stdout.buffer.flush()

# Reading a frame (Windows-safe):
buf = bytearray()
while True:
    b = sys.stdin.buffer.read(1)   # ⚠️ read 1 byte: fix for Windows pipe deadlock
    if not b: break
    buf.extend(b)
    result = parse_frame(buf, 0)
    if isinstance(result, ParseComplete):
        frame = result.frame
        payload = frame.payload
        if frame.flags & FLAG_COMPRESSED:
            payload = decompress_value(payload)
        return payload  # ⚠️ already a dict, NOT bytes
```

Hermes config (no `lumen_force_json_rpc`):
```yaml
mcp_servers:
  my_server:
    command: "python"
    args: ["server_native.py"]
    transport: lumen
```

**Wire savings**: 50-80% (no JSON-RPC overhead at all).

### Native Server PROBE Handshake

Native LUMEN servers MUST handle the PROBE/ACK handshake to work with Hermes.
Hermes sends a LUMEN PROBE frame first. The server must detect it and respond
with PROBE_ACK BEFORE processing any JSON-RPC messages.

```python
def process_message(msg: dict) -> dict:
    # PROBE frames have "protocol": "LUMEN" key (not "method" like JSON-RPC)
    if "protocol" in msg and msg.get("protocol") == "LUMEN":
        client_versions = msg.get("supported_versions", ["1.0"])
        accepted = "1.0" if "1.0" in client_versions else client_versions[0]
        return {
            "__lumen_ack__": True,
            "ack": {
                "protocol": "LUMEN",
                "server_name": "my-server-name",
                "accepted_version": accepted,
            }
        }
    # Normal JSON-RPC handling...
    method = msg.get("method", "")
```

```python
def send_lumen_frame(response: dict) -> None:
    if response is None: return
    if response.get("__lumen_ack__"):
        # Send as TYPE_PROBE_ACK frame, not TYPE_RESPONSE
        payload = compress_value(response["ack"])
        buf = bytearray(build_size(len(payload)))
        build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()
        return
    # Normal TYPE_RESPONSE handling...
```

Without this, Hermes will timeout on the LUMEN probe and the server won't connect.

---

## MCP Server Structure

Every server must handle these JSON-RPC methods:

| Method | Purpose |
|--------|---------|
| `initialize` | Protocol handshake, version, capabilities |
| `tools/list` | Return tool schemas |
| `tools/call` | Dispatch to tool handler |
| `notifications/initialized` | No response needed |

Tool schema format follows Hermes conventions exactly:
```python
{
    "name": "my_tool",
    "description": "What it does",
    "inputSchema": {
        "type": "object",
        "properties": {
            "param1": {"type": "string", "description": "First param"},
            "param2": {"type": "integer", "default": 42}
        },
        "required": ["param1"]
    }
}
```

Tool results MUST follow MCP content format:
```python
{"content": [{"type": "text", "text": "result string"}]}
```

---

## Pitfall Checklist

### ✅ Frame building
- `build_size(payload_len)` returns **total wire size** (header + type + flags + payload).
  Call it as `build_size(len(payload))` — the first positional arg is `payload_len`,
  NOT `frame_type`. `frame_type` is keyword-only.
- `buf = bytearray(build_size(len(payload)))` — one call, no manual addition needed.
- `TYPE_REQUEST` for client→server, `TYPE_RESPONSE` for server→client
- ⚠️ **Historical bug (fixed June 2026)**: `build_size()` had `frame_type` as first
  positional parameter, so `build_size(len(payload))` called `build_size(frame_type=86, payload_len=0)`
  and always returned 3 bytes. Fixed by making `frame_type` keyword-only.
  See `references/build_size-bug.md` for full details.

### ✅ Decompression
- `decompress_value()` returns a **dict**, not bytes. Don't call `json.loads()` on it
- Check `frame.flags & FLAG_COMPRESSED` before decompressing

### ✅ FrameAssembler buffer cap (DoS prevention)
- Always initialize `FrameAssembler(max_frame=4*1024*1024)` — default 4 MiB
- Without a cap, a malicious peer can send `LEN=4GB` and exhaust memory
- `BufferError` is raised when the buffer exceeds `max_frame`

### ✅ Hyb128 strict mode
- `decode_hyb128(data, strict=True)` rejects non-minimal encodings
- `strict=False` (default) is lenient for backward compat
- Use `strict=True` in security-sensitive contexts to prevent canonicalization bypass

### ✅ Windows pipe I/O (June 2026 — revised)

**DO NOT use `read(1)`** — it dispatches to the threadpool per byte (terrible performance).
Use a **dedicated reader thread** with the `asyncio.Queue` pattern:

```python
import threading, asyncio

class NativeServer:
    def __init__(self):
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=256)

    def _start_reader_thread(self):
        loop = asyncio.get_running_loop()
        stdin = sys.stdin.buffer
        def _run():
            while True:
                chunk = stdin.read(65536)
                loop.call_soon_threadsafe(self._queue.put_nowait, chunk)
                if not chunk: break
        threading.Thread(target=_run, daemon=True).start()

    async def read_frame(self):
        buf = bytearray()
        while True:
            chunk = await self._queue.get()
            if not chunk: return None  # EOF
            buf.extend(chunk)
            result = parse_frame(buf, 0)
            if isinstance(result, ParseComplete):
                return result.frame
```

For **servers** (not transports), the simpler `read(1)` loop is acceptable since servers
process one request at a time. The thread pattern is essential for transports that
must sustain high-throughput agent loops.

### ✅ Tool schemas
- Match Hermes built-in schemas exactly for tool names the LLM knows
- Include `default`, `minimum`, `maximum` in integer params
- Use `enum` for string params with fixed options
- `required` array must list non-optional params

### ✅ Error handling
- Return errors as content text, not JSON-RPC error codes
- Gracefully handle missing files, permission errors, invalid input
- Never crash on malformed input from the LLM

### ✅ Multi-agent
- Use in-memory cache with TTL (e.g., 300s for web search)
- Hard cap output sizes (100K chars for files, 80K for search)
- Prune old chains to avoid memory bloat (keep last 10)

---

## Multi-agent Session Isolation

For servers that maintain state (chains, assumptions, models, work logs),
multi-agent isolation prevents state collisions when multiple agents share
a transport connection.

**Pattern: Session class + per-session state**

```python
class Session:
    def __init__(self, label=""):
        self.label = label
        self.chains: dict = {}
        self.assumptions: list = []
        self.model: dict = {}
        self.works: list = []
        self.tool_calls = 0
        self.created_at = time.time()
        self.updated_at = time.time()

_sessions: dict[str, Session] = {}
_DEFAULT_SESSION = "default"

def _get_session(session_id: str | None = None) -> Session:
    sid = session_id or _DEFAULT_SESSION
    if sid not in _sessions:
        _sessions[sid] = Session(label=sid)
    _sessions[sid].updated_at = time.time()
    _sessions[sid].tool_calls += 1
    return _sessions[sid]
```

**Key rules:**
1. Each tool function extracts session at the top: `session = _get_session(args.get("session_id"))`
2. All state accesses go through `session.chains`, `session.assumptions`, etc.
3. `session_init` tool creates/resumes sessions, returns `session_id`
4. `session_list` tool shows all active sessions with stats
5. Backward compatible: default session for existing code without `session_id` param
6. Use `_chains()` / `_assumptions()` / `_model()` shim functions for legacy compat during migration

**Refactoring checklist** (when converting from global to per-session):
- Replace all `_chains[cid]` → `session.chains[cid]`
- Replace all `_assumptions.append(...)` → `session.assumptions.append(...)`
- Replace all `_model[path]` → `session.model[path]`
- Replace all `_works.append(...)` → `session.works.append(...)`
- Update `_update_dependents()` to accept `session` parameter
- Add `session_id` to each tool's inputSchema (`required: false`)
- Verify with eval suite before committing

---

## Testing & Evaluation

The project includes an objective evaluation framework at
`implementations/mcp-servers/eval_framework.py`.

**Running evaluations:**
```bash
cd implementations/mcp-servers/filesystem && python eval.py
cd implementations/mcp-servers/web && python eval.py
cd implementations/mcp-servers/thinking && python eval.py
```

**Framework API:**
```python
from eval_framework import MCPTestRunner

runner = MCPTestRunner("SERVER NAME")

# Per-tool tests with categories
runner.test("tool_name", "correctness", lambda: check_result())
runner.test("tool_name", "error-handling", lambda: check_error())
runner.test("tool_name", "edge-cases", lambda: check_boundary())
runner.test("security", "security", lambda: check_blocked())

# Scored report with per-tool breakdown
print(runner.report())
```

**Test categories:**
- `correctness` — normal inputs, expected outputs
- `error-handling` — invalid/missing params, graceful errors
- `edge-cases` — empty, boundary, large inputs
- `security` — path traversal (filesystem), SSRF (web), injection

**Design rules for eval tests:**
1. Test EVERY tool in the server
2. Test both success and failure paths
3. Include performance timing (framework auto-records latency)
4. Security tests MUST verify blocks, not just existence
5. Use inline roundtrip (LUMEN frames) for fast execution
6. Use subprocess (JSON-RPC) for realistic network tests

---

## Benchmarking

Always compare LUMEN vs Hermes built-in on the same data:

```python
# Latency: both tools on same file
t0 = time.perf_counter()
# ... built-in operation ...
t_builtin = time.perf_counter() - t0

t0 = time.perf_counter()
# ... LUMEN operation ...
t_lumen = time.perf_counter() - t0

# Wire: compress the JSON-RPC response
json_bytes = len(json.dumps(response).encode())
lumen_bytes = len(compress_value(response))
savings = (1 - lumen_bytes / json_bytes) * 100
```

**Honest assessment rule**: if LUMEN isn't clearly superior, say so. Don't push weak claims.

---

## Cognitive Safety Principle

**Tools must EXPAND perception, not REPLACE judgment.** Gate for all new tools:

- ✅ SAFE: Assumption Tracker (shows blind spots), Mental Model Builder (factual graph), Context Decay Detector (preserves info)
- ❌ UNSAFE: Decision Journal (over-generalization, bias), Confidence Tracker (overfitting, dogmatism)

---

## Hermes Integration

After building the server, add to Hermes config:

```yaml
mcp_servers:
  my_lumen_server:
    command: "C:/Users/.../python.exe"
    args: ["C:/Users/.../server.py"]
    transport: lumen
    lumen_force_json_rpc: true  # only for Pattern A servers
    enabled: true
```

Tools appear as `mcp_my_lumen_server_tool_name` in Hermes.

To force the LLM to use only LUMEN tools (disable built-in equivalents):
```yaml
tools:
  disabled_toolsets: ["file"]  # disable Hermes built-in file tools
```

---

## Reference Implementations

All in `lumen-protocol/implementations/mcp-servers/`:

| Server | Pattern | Tools | Key Learnings |
|--------|---------|-------|---------------|
| `filesystem/` | A + B | 9 | Schema parity, output_mode, bulk ops, streaming |
| `web/` | A | 2 | DuckDuckGo API + HTML fallback, multi-agent cache |
| `thinking/` | A | 22 | TF-IDF in stdlib, cognitive safety, work tracker |

## Protocol Development Workflow

For protocol-level changes (new frame types, RFC updates, cross-language interop),
see `references/protocol-development.md`. Covers the audit→fix→implement→RFC cycle,
publishing workarounds, and project conventions.

## Related Skills

- **[lumen-thinking-server-dev](lumen-thinking-server-dev)** — STREAM_DATA token streaming, MUX channel multiplexing, Windows-safe frame parsing for thinking servers
- **[lumen-mcp-server-pattern](lumen-mcp-server-pattern)** — Proven patterns: shared_tools (anti-duplication), session isolation, eval framework, security hardening
