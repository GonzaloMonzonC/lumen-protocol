---
name: lumen-server-development
description: '👽 How to build, test, and deploy LUMEN MCP servers. Covers JSON-RPC wrapper pattern, LUMEN native pattern, pitfall checklist, benchmarking, and Hermes integration. LUMEN tools marked 👽.'
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

### Pattern C: Shared Memory Zero-Copy (`server_shm.py`)

Level 2 transport using mmap'd ring buffers for zero-copy inter-process communication.
The server creates a named `ShmRegion` during PROBE handshake and advertises it
in the PROBE_ACK. All subsequent frames flow through lock-free SPSC ring buffers.

**When to use**: large payloads (>4KB), high-throughput agent loops, local IPC.

**Architecture**:
```
PROBE (stdio) → ACK with shm_region name → switch to mmap ring buffers
  Ring A: Client → Server (SPSC, length-prefixed LUMEN frames)
  Ring B: Server → Client (SPSC, length-prefixed LUMEN frames)
```

```python
from shm_native_server import ShmNativeServer

server = ShmNativeServer(
    "my-server-shm",
    TOOLS,
    HANDLERS,
    shm_size=1024 * 1024,  # 1 MiB
)
server.run()
```

The `ShmNativeServer` base class handles: PROBE→SHM negotiation, ring buffer
setup, frame I/O (both stdio and shm), and cleanup. Subclasses only provide
`TOOLS` and `HANDLERS`.

**Hermes integration (pending)**: `LumenStdioTransport` must detect `shm_region`
in the PROBE_ACK, open the region via `ShmRegion.open()`, and switch to
`ShmTransport`. Current workaround: use `server.py` + `lumen_force_json_rpc: true`
or `server_native.py` via binary pipes for Hermes; SHM servers work in direct
cross-process tests.

**Wire savings**: 55-80% (same as native binary) + zero-copy for payloads.

**SHM Tuning (CRITICAL — June 2026)**:

| Parameter | Default | Recommended | Why |
|-----------|---------|-------------|-----|
| `MAX_SPIN` | 1,000,000 | **50,000,000** | Timeout on files >30KB. 50M handles >1MB payloads |
| `YIELD_INTERVAL` | 1000 | **100** | Yield more often during spin-wait to avoid CPU starvation |
| Filesystem buffer | 2 MiB | **8 MiB** | Large file reads + search results on big repos (ProjectOS: 500K files) |
| Thinking buffer | 1 MiB | **2 MiB** | Long chains + large model entities |
| Web buffer | 512 KiB | 512 KiB | Web responses are network-bound, little local data |

**SHM Tuning (CRITICAL — June 2026)**: The default SHM parameters cause timeouts and flaky behavior. These values are production-tested:

| Parameter | Default | Production | Why |
|-----------|---------|-----------|-----|
| `MAX_SPIN` | 1,000,000 | **50,000,000** | Files >30KB timeout. 50M handles >1MB payloads |
| `YIELD_INTERVAL` | 1000 | **100** | Yield frequently during spin-wait for smoother performance |
| Filesystem buffer | 2 MiB | **8 MiB** | Large repos (ProjectOS: 500K files) need headroom |
| Thinking buffer | 1 MiB | **2 MiB** | Long chains + large model entities |
| Web buffer | 512 KiB | 512 KiB | Network-bound, little local data |

**Limits**: Files >2MB still timeout at 50M MAX_SPIN + 8 MiB. Use `stream_read` for these.

### Pattern D: Dashboard HTTP Metrics API (`--dashboard`)

Expose cognitive state via HTTP for monitoring dashboards. Runs on daemon thread — zero interference with MCP.

**Integration**: `python server.py --dashboard 9876`
- `/` → dashboard HTML (vanilla JS, no deps)
- `/metrics` → JSON API with all cognitive data
- `/health` → plain text OK
- POST `/touch` → register file access for collision detection
- GET `/collisions` → detect multi-session file conflicts

**Shared state pattern**: Dashboard server and SHM server are separate processes. They communicate via `.thinking_state.json`. Dashboard re-reads on each `/metrics` request.

**Dashboard lifecycle**: The plugin now spawns the thinking server with `--dashboard 9876` automatically. No manual `sleep 999 | python server.py --dashboard 9876` needed. The plugin also cleans stale processes on port 9876 before starting. See `references/dashboard-lifecycle.md`.

**Standalone mode for Hermes background (June 2026)**: When started via `terminal(background=true)` without stdin, the server's main loop (`sys.stdin.readline()` at line 2710) immediately receives EOF (`None`) and exits. Because the dashboard's HTTP server runs on a daemon thread, the process dies. **Two fixes:**

  1. **Pass `--standalone` flag** — bypasses stdin loop with a `time.sleep(1)` loop:
     ```bash
     python server.py --dashboard 9876 --standalone
     ```
  2. **Auto-detect non-tty stdin** (already patched June 2026) — the main loop now checks `sys.stdin.isatty()`. When not a TTY (pipeless mode), it enters standalone mode automatically. `--standalone` forces it explicitly.

  **Verification** after starting:
  ```bash
  curl -s http://127.0.0.1:9876/metrics | jq .totals
  ```

**Pitfall — work tools need the thinking server running**: `work_done`, `work_block`, `work_start` send tool calls to the thinking server via the SHM bridge. If the thinking server is down (commonly from stdin-exit), calls appear to succeed (no error) but the work log is never updated. Check `state_snapshot` or `process(action='poll')` to verify the server is alive before debugging stale work items.

**Pitfall**: NEVER inline dashboard HTML as Python `r"""..."""`. Load from file.

**Platform support**: Windows (`CreateFileMappingW`/`MapViewOfFile`) and
Unix (`shm_open`/`mmap`). Python `mmap` module abstracts platform differences.

**Key modules**:
- `lumen/shm.py` — `ShmRegion`, `ShmRingBuffer`, `ShmTransport`
- `mcp-servers/shm_native_server.py` — `ShmNativeServer` base class
- `mcp-servers/thinking/server_shm.py` — 29 cognitive tools over SHM
- `mcp-servers/filesystem/server_shm.py` — 9 file tools over SHM
- `mcp-servers/web/server_shm.py` — 2 web tools over SHM

### Pattern D: Dashboard HTTP API (`--dashboard` flag) 🆕

Expose cognitive state via lightweight HTTP for monitoring dashboards.
Runs on daemon thread — zero interference with MCP transport.

```python
def _start_dashboard(port: int = 9876):
    import threading, http.server
    dashboard_html = open(Path(__file__).parent / "dashboard.html").read()
    
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":          # HTML dashboard
                self.wfile.write(dashboard_html.encode())
            elif self.path == "/metrics": # JSON API
                self.wfile.write(json.dumps(_build_metrics()).encode())
            elif self.path == "/health":  # Plain text
                self.wfile.write(b"OK")
    
    threading.Thread(target=http.server.HTTPServer(("127.0.0.1", port), Handler).serve_forever, daemon=True).start()
```

**Dashboard HTML**: Vanilla JS only — no Alpine.js, no CDN deps, no build step.
`fetch('/metrics')` every 10s (was 3s — 10s + change detection prevents CPU saturation), render with `innerHTML`, Canvas for charts.

**Shared state**: Dashboard server and MCP server are separate processes.
They share state via `.thinking_state.json`. Dashboard re-reads on each `/metrics` request.

**Pitfall**: NEVER inline dashboard HTML as Python `r"""..."""` raw string.
Em dashes, `</script>` tags, and CSS backslash sequences break Python raw strings.

**Reference**: `implementations/mcp-servers/thinking/dashboard.html` — production dashboard with 18 panels.  
**LUMEN WebSocket transport**: `lumen_transport.py` (198 lines) pushes LUMEN-framed metrics (80% compression) to dashboard clients on port+1. See `references/lumen-universal-protocol-strategy.md`.  
**Token-efficient tools**: Register <50-char output tools in 3 places (server.py HANDLERS, server.py TOOLS, plugin __init__.py register_tool). See `references/token-efficient-tools-pattern.md`.

See `references/dashboard-metrics-api.md` for full API spec.

See `references/shm-transport.md` for full integration details, test results,
and the cross-process test harness.

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

### ✅ Windows Unicode / charmap encoding

On Windows, Python's default stdout codec is `charmap` (Windows-1252), which
**cannot encode** emoji, box-drawing characters (`═`, `─`, `█`), or any character
above U+00FF. Any MCP server that outputs these will fail with:
`'charmap' codec can't encode character '\U0001f4ca' in position 78`.

**Fix (applied to filesystem server June 2026):**

```python
# At the top of server.py, BEFORE any output:
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
```

**Additional safety**: Replace Unicode box-drawing and emoji characters in tool
output with ASCII equivalents. Even with UTF-8 configured, some terminals and
pipe readers don't handle them:

| Unicode | Replacement |
|---------|-------------|
| `═` `─` | `=` `-` |
| `█` | `#` |
| `📁` `📄` | `[DIR]` `[FILE]` |
| `📖` `📊` | `FILE:` (or remove) |
| `🏁` `✅` `❌` | `[DONE]` `OK` `FAIL` |

**Note**: The thinking server already has `reconfigure(encoding="utf-8")` since
its initial version and uses emoji safely because of it. New servers must include
this from day one.

### ✅ Windows UTF-8 stdout (MANDATORY — June 2026)

**Every MCP server MUST force UTF-8 on stdout** as the first executable line after imports. Without this, any Unicode character (emoji, accented text, box-drawing chars like `█`/`═`/`─`) in tool output will crash the server with `charmap codec can't encode character` on Windows.

```python
# server.py — MUST be the first lines after imports, before any logic
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
```

**Affected servers fixed June 2026**: filesystem (emojis + box-drawing), web (HTML content with Unicode), thinking (already had the fix). Without this, servers crash on first Unicode output and Hermes marks them unreachable after 3 retries.

**Also replace non-ASCII output with safe alternatives** when possible:
- `📁`/`📄` → `[DIR]`/`[FILE]`
- `📖` → `FILE:`
- `🏁` → `[FINAL CHUNK]`
- `═══` → `===`
- `───` → `---`
- `█` → `#`

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

### ✅ Hermes binary pipe limitation for native servers (June 2026)

Native LUMEN servers (`server_native.py`) write binary frames to `sys.stdout.buffer`.
However, Hermes' `LumenStdioTransport` spawns the MCP subprocess with **text pipes**
(UTF-8 encoding). When the native server writes binary PROBE_ACK or response frames,
Hermes fails with:
```
'utf-8' codec can't decode byte 0x80 in position 0: invalid start byte
```

**Current state**: Native servers pass all tests when accessed directly with binary
pipes (PROBE→ACK→tools/call). They are blocked from Hermes use until
`LumenStdioTransport` adds binary pipe support. In the meantime, use the JSON-RPC
wrapper pattern (`server.py` + `lumen_force_json_rpc: true`) for Hermes integration.

**Testing native servers directly**:
```python
# Binary pipe test — works
from lumen import build_frame, build_size, compress_value, parse_frame, ...
proc = subprocess.Popen([PYTHON, "server_native.py"], stdin=PIPE, stdout=PIPE)
# Send PROBE frame → read ACK → send JSON-RPC in LUMEN frames → read response
```

### ✅ `lumen_force_json_rpc` deadlock (CRITICAL — June 2026)

**🐛 Symptom**: Hermes logs show `MCP server 'X' failed initial connection after 3 attempts` with empty error messages. Server process starts but never completes handshake.

**Root cause**: When `lumen_force_json_rpc: false` (the default), Hermes sends a LUMEN binary PROBE frame. JSON-RPC-only `server.py` files use `sys.stdin.readline()` which blocks until a newline byte (`\n`). LUMEN binary frames don't contain newlines → `readline()` blocks forever → Hermes times out. Deadlock.

**Fix**: Set `lumen_force_json_rpc: true` for ALL `server.py` variants that use `readline()`-based input:

```yaml
mcp_servers:
  lumen_thinking:
    transport: lumen
    lumen_force_json_rpc: true  # ← REQUIRED for readline()-based servers
```

Apply via CLI: `hermes config set mcp_servers.<name>.lumen_force_json_rpc true`

**Affected servers**: All `server.py` files that use `sys.stdin.readline()` in their main loop (filesystem, thinking, web). The `server_native.py` variants use `sys.stdin.buffer.read(1)` and are NOT affected.

### ✅ Hermes plugin handler signature (CRITICAL — June 2026)

**🐛 Symptom**: Plugin registers tools, overrides built-ins (REJECTED messages confirm), but tool calls return 0 chars with no error logged. Latency is very fast (0.35s) — too fast for actual server work.

**Root cause**: Hermes passes tool parameters as a **single dict in the first positional argument**, NOT as individual kwargs. A handler `def fn(path: str, ...)` receives the params dict as `path`.

**Fix**: ALL plugin handlers MUST use `*args`:
```python
# ❌ WRONG — receives dict as 'path', returns empty silently
def handle_read_file(path: str, offset: int = 1, limit: int = 500, **kwargs) -> str:
    # path = {"path": "C:\\...", "offset": 1, "limit": 500}  ← DICT, not string!
    ...

# ✅ CORRECT — extracts params from dict
def handle_read_file(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    path = params.get("path", "")
    offset = params.get("offset", 1)
    limit = params.get("limit", 500)
    ...
```

**Debugging silent failures**: When a handler returns empty (0 chars, no error logged), it's almost always a signature mismatch. Evidence: `tool read_file completed (0.35s, 0 chars)` with 0.35s latency — too fast for actual I/O. Hermes silently swallows the TypeError.

**Validated**: All 40 LUMEN SHM tools use this pattern and pass with zero errors in full benchmark (2026-06-19).

### ✅ Hermes plugin config format (CRITICAL — June 2026)

Two antipatterns that silently prevent plugin loading:

**1. `plugins.enabled` is a YAML LIST, not a dict:**
```yaml
# ✅ CORRECT
plugins:
  enabled:
    - lumen-shm-bridge

# ❌ WRONG — silently ignored
plugins:
  lumen-shm-bridge:
    enabled: true
```

**2. `hermes config set` stores values as strings:**
```bash
# ❌ Sets plugins.enabled = "['lumen-shm-bridge']" (STRING, not list!)
hermes config set plugins.enabled "['lumen-shm-bridge']"

# ✅ Use Python to write proper YAML
python -c "import yaml; cfg=yaml.safe_load(open('config.yaml')); cfg['plugins']={'enabled':['name']}; yaml.dump(cfg, open('config.yaml','w'))"
```

**3. `plugin.yaml` manifest REQUIRED:**
```yaml
# ~/.hermes/plugins/<name>/plugin.yaml
name: my-plugin
version: 1.0.0
description: "..."
author: "..."
kind: standalone  # for tool-registering plugins
```
Without `plugin.yaml`, `hermes plugins list` won't show it and it won't load.

- **Auto-trigger variable mismatch (2026-06-20, CRITICAL)**: `sequential_thinking`'s auto-evaluate block referenced `new_thought` but the actual variable is `thought_obj` (line 864). The outer `try/except` silently caught the `NameError`, so NOT A SINGLE thought was ever auto-scored since the feature was deployed. **Fix**: patch all three references (`thought_obj.get("score")`, `thought_obj["thought"]`, `thought_obj["score"] = score`). Verify by checking output for `🤖 Auto-scored: X/10` after creating a thought with action words + numbers.

- **Dashboard JS brace imbalance from duplicate functions (2026-06-20)**: Three common sources of JS syntax errors in `dashboard.html`: (1) `async function refresh(){async function refresh(){` — function name duplicated on same line, (2) Two `showCluster` functions (old `/chain` API + new `_lastClusters` in-memory version) — remove the old one, (3) Duplicate `toggleSection` definitions — remove one. **Symptom**: `Uncaught SyntaxError: Unexpected end of input` in browser console, all dashboard numbers show 0. **Fix**: verify with `python implementations/mcp-servers/thinking/post-patch-validator.py` after any dashboard edit. Brace balance must be 0 diff.

- **Plugin auto-dashboard not starting (2026-06-20)**: The `lumen-shm-bridge` plugin spawns `server_shm.py` WITHOUT `--dashboard 9876` by default. Add the flag to the spawn args: `[_HERMES_VENV_PYTHON, "-u", self.server_path, "--dashboard", "9876"] if "thinking" in self.server_path else`. Three stale processes can accumulate on 9876 — kill ALL before testing: `netstat -ano | grep ":9876 " | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid 2>/dev/null; done`.

- **Uncaught ReferenceError: _lumenWs is not defined (2026-06-20)**: The dashboard's `refresh()` function checks `if(_lumenWs&&_lumenWs.readyState===WebSocket.OPEN)return;` but `_lumenWs` is only defined if the LUMEN WebSocket client script loads successfully. **Fix**: add `var _lumenWs=null;` before the `refresh()` function declaration. The dashboard falls back to HTTP polling when WebSocket is unavailable.

### ✅ Dashboard HTTP API (June 2026)

Thinking servers can expose a lightweight HTTP metrics endpoint for dashboards.
Runs on a daemon thread — zero interference with MCP operations.

**Integration:**
```python
# server.py
def _start_dashboard(port: int = 9876):
    import threading, http.server as _http
    _dashboard_html = open(Path(__file__).parent / "dashboard.html").read()
    
    class Handler(_http.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":
                body = _dashboard_html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/metrics":
                data = {"totals": {"chains": 3, "patterns": 1, ...}, "top_chains": [...], ...}
                body = json.dumps(data).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/health":
                self.send_response(200); self.end_headers(); self.wfile.write(b"OK")
    
    threading.Thread(target=_http.HTTPServer(("127.0.0.1", port), Handler).serve_forever, daemon=True).start()

# In main():
if "--dashboard" in sys.argv:
    port = int(sys.argv[sys.argv.index("--dashboard") + 1]) if ... else 9876
    _start_dashboard(port)
```

**For SHM server (`server_shm.py`):**
```python
import server as _server
if "--dashboard" in sys.argv:
    _server._start_dashboard(port)
```

**Serve dashboard HTML from file**, never inline as Python string. Raw strings (`r"""..."""`) break on em dashes, `</script>` tags, and backslash sequences in CSS.

**CORS is REQUIRED** for cross-origin dashboards (Vercel → localhost). The `/metrics` endpoint must set `Access-Control-Allow-Origin: *`.

**🐛 Symptom**: `RuntimeError: SHM read timeout` on files >30KB or `search_files count` on large directories. Client spins waiting for complete frame in ring buffer but server hasn't finished writing yet.

**Root cause**: `MAX_SPIN=1_000_000` in `lumen/shm.py` is too low for large payloads. The server process needs time to read a large file from disk, format the response, and write it to the ring buffer. The client's `recv_frame()` spins out before the write completes.

**Fix**: Increase `MAX_SPIN` to 50M and decrease `YIELD_INTERVAL` to 100:
```python
# lumen/shm.py
MAX_SPIN: int = 50_000_000      # was 1_000_000 — handles >1MB payloads
YIELD_INTERVAL: int = 100       # was 1000 — yield more frequently
```

**Also increase filesystem ring buffer** for large repo exploration:
```python
# Plugin SERVER_CONFIGS or server_shm.py
shm_size = 8 * 1024 * 1024  # 8 MiB (was 2 MiB)
```

**Validated**: 44KB file reads in 11.5ms (was timeout). 500K-file repo exploration with zero timeouts.

**Files >2MB** still timeout. Use `stream_read` for these.

### Pattern D: Dashboard HTTP Metrics API (`--dashboard` flag)
- Use `enum` for string params with fixed options
- `required` array must list non-optional params

### ✅ Error handling
- Return errors as content text, not JSON-RPC error codes
- Gracefully handle missing files, permission errors, invalid input
- Never crash on malformed input from the LLM
- **Critical: broad exception handling in main loop** (fixed 2026-06-19):
  The `main()` loop's try/except must catch ALL exceptions, not just
  `JSONDecodeError`. If a tool handler raises `KeyError` (missing param),
  or `send()` hits `OSError` (broken pipe), the server dies and Hermes
  gets `ClosedResourceError`. Pattern:
  ```python
  except json.JSONDecodeError:
      pass  # malformed JSON, skip
  except Exception as e:
      try:
          send({"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32603, "message": f"Internal error: {e}"}})
      except Exception:
          pass  # send() itself failed, but server stays alive
  ```

### ✅ Session migration pitfalls (thinking server, June 2026)

When migrating a server from global state to per-session state, three silent
bug classes appear:

**Bug 1: `session` variable undefined in tool functions.** If you change
`_works.append(...)` to `session.works.append(...)` but forget to add
`session = _get_session(args.get("session_id"))` at the top of the function,
the server crashes with `NameError: name 'session' is not defined`. Affected:
`work_start`, `work_block`, `work_done`, `work_log`. Fix: add session retrieval
as the FIRST line of every tool function that accesses state.

**Bug 2: `global` declaration missing on module-level variables.** If
`_next_work_id` is a module-level variable and a function assigns to it with
`_next_work_id += 1`, Python treats it as a local unless `global _next_work_id`
is declared. Error: `UnboundLocalError: cannot access local variable '_next_work_id'`.
Fix: add `global _next_work_id` at function top.

**Bug 3: Helper functions use unqualified `session`.** `_load_works()` and
`_save_works()` access `session.works` but don't call `_get_session()`. Add
`session = _get_session()` as the first line. These are called at module
load time too — `_get_session()` creates a default session on first call.

**Bug 4: Tool in HANDLERS but NOT in TOOLS.** `model_scan` was implemented
and wired in HANDLERS, but its schema was never added to the TOOLS list.
Result: tool is callable by name but invisible to `tools/list` → MCP clients
never discover it. Fix: always add a corresponding TOOLS entry when adding
a new handler. Run `grep` to audit: handler count == tools count.

**Bug 5: Config toggle wipes `transport: lumen`.** When toggling a server
`enabled` off/on via `hermes config set mcp_servers.X.enabled false/true`,
the `transport` key is silently reset to `stdio`, losing the LUMEN transport.
After toggle, always verify: `grep -A5 "<name>" ~/.hermes/config.yaml`.
- **Windows stdout encoding for emoji** (fixed 2026-06-19):
  When stdout is a pipe (subprocess), Windows sets encoding to `cp1252`.
  If tool responses contain emoji (📋🔍✅⚠️), they produce invalid bytes
  and Hermes fails with `'utf-8' codec can't decode byte 0x97`.
  Fix: add `sys.stdout.reconfigure(encoding="utf-8")` after imports.
- **`send()` must be crash-proof** (fixed 2026-06-19):
  `sys.stdout.flush()` on Windows can raise `OSError` or `BrokenPipeError` when
  the pipe is broken. If `send()` crashes inside `handle_message()`, the exception
  may propagate before the outer handler catches it, killing the server.
  Fix: wrap `send()` body in `try/except (OSError, BrokenPipeError, ValueError)`.
  ```python
  def send(msg):
      try:
          sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
          sys.stdout.flush()
      except (OSError, BrokenPipeError, ValueError):
          pass
  ```
- **Tool handlers must use `.get()` for ALL params** (fixed 2026-06-19):
  Even if a param is marked `required` in the schema, the handler should use
  `args.get("param", default)` instead of `args["param"]`. If an LLM sends
  wrong param names, bracket access raises `KeyError` which reaches Hermes as
  `McpError: Tool error: 'param'`. Using `.get()` with graceful fallback
  prevents cascading failures.
  ```python
  # ❌  Crashes on missing param
  thought_text = args["thought"]
  # ✅  Returns helpful error message
  thought_text = args.get("thought", "")
  if not thought_text:
      return {"content": [{"type": "text", "text": "Pass 'thought' parameter."}]}
  ```

### ✅ Multi-agent
- Use in-memory cache with TTL (e.g., 300s for web search)
- Hard cap output sizes (100K chars for files, 80K for search)
- Prune old chains to avoid memory bloat (keep last 10)
- **Hermes MCP tools limit** (observed 2026-06-19): Hermes may only register
  the first N tools from a server's tools/list response. Our thinking server
  has 29 tools but only 7 appeared in Hermes. If tools 8+ are missing,
  reorder the TOOLS list so critical tools come first. Check Hermes MCP
  client for a `max_tools_per_server` config or truncation bug.

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

### ⚠️ `_load_state()` `global` declaration — CRITICAL scope pitfall

When adding a NEW module-level global variable that will be persisted via `_save_state()`/`_load_state()`, you MUST add THREE things:

1. **Declaration**: `_my_var: type = default` at module level
2. **`_save_state()`**: add to the state dict: `"my_var": _my_var,`
3. **`_load_state()`**: add `global _my_var` in the `global` statement block, THEN `_my_var = state.get("my_var", default)`

**🐛 The silent failure (discovered June 2026)**: Without `global _my_var` in `_load_state()`, Python treats the assignment `_my_var = state.get(...)` as a LOCAL variable inside `_load_state()` — the MODULE-level `_my_var` stays at its default value (`{}` or `0.0`). The dashboard server (which reads module-level `_my_var`) sees EMPTY data.

**Detection**: After adding a new persisted variable, run a standalone test:
```python
import server
server._load_state()
print(f"{len(server._my_var)} items loaded")  # Should show data, not 0
```

**Affected fix (June 2026)**: `_web_snapshots` and `_last_state_mtime` were added without `global` declarations in `_load_state()`. All other globals loaded there (`_niches`, `_tasks`, `_last_state_mtime`, `_file_claims`) already had proper `global` declarations. The `_web_snapshots` bug took 15+ iterations to diagnose because:
  - MCP tool `web_snapshot` correctly saved to state file (via its own `global _web_snapshots` declaration)
  - `_load_state()` silently created a local copy → module-level var stayed at `{}`
  - Dashboard endpoint `/web-snapshots` always returned empty array
  - Everything "worked" in isolation tests (direct `_load_state()` call from Python REPL showed data), but the dashboard server saw nothing

**See also**: `references/web-cognitive-integration.md` for the web_snapshot tool architecture.

### ⚠️ Nested class method variable scope — `globals()` pitfall

When the dashboard HTTP handler (MetricsHandler nested inside `_start_dashboard()`) needs to RELOAD shared state from `.thinking_state.json`, **never use bare name assignment**:

```python
# ❌ WRONG — Python might use the closure/enclosing scope instead of module scope
_web_snapshots = _st.get("web_snapshots", {})

# ✅ CORRECT — explicitly targets module globals dict
_g = globals()
_g['_web_snapshots'] = _st.get("web_snapshots", {})
```

Why? Methods of nested classes resolve variable names through: local → enclosing class → enclosing function → module. If `_start_dashboard()` ever acquires a local variable with the same name (even via a future refactor), the method will use the closure variable instead of the module global. Using `globals()` bypasses the entire scope chain.

**Reading** back from `globals()`:
```python
# Bare name is fine for reading (if module-level)
snaps = _web_snapshots.values()  # ✅ resolves to module-level

# But for defensive coding, use globals() for reads too:
snaps = globals().get("_web_snapshots", {}).values()  # ✅ always works
```

**Affected**: `/web-snapshots` HTTP endpoint in the dashboard server's do_GET handler. Fixed June 2026 by using `globals().get("_web_snapshots", {})`.

### ✅ State persistence (updated June 2026)

**Cross-process file locking**: When dashboard and MCP server share `.thinking_state.json`,
Windows may lock the file during reads, causing `os.replace()` to fail with `WinError 32`.
**Fix**: retry with exponential backoff (5 attempts, 10→80ms). See `references/file-locking-cross-process.md`.
Clean stale `.tmp` files before writing. Fallback to direct write on last attempt.

### ⚠️ Custom global-state tools MUST call `_save_state()` explicitly

Tools that modify global state (like kanban's `_tasks`, `_niches`) but DON'T go through
`_get_session()` will NEVER trigger `_auto_save()`, because `_auto_save()` only fires
inside `_get_session()`. Result: modifications are lost on server restart.

**Fix**: Add `_save_state()` at the end of every handler that mutates global state:

```python
def tool_my_create(args: dict) -> dict:
    global _my_global_data
    _my_global_data[new_id] = new_item
    _save_state()  # ← REQUIRED for global-state tools
    return {"content": [{"type": "text", "text": "✅ Created"}]}
```

**Affected tools fixed June 2026**: `niche_create`, `niche_update`, `task_create`,
`task_move`, `task_link`, `task_delete` — all kanban cognitive tools.

**Detection**: After creating data via MCP and restarting the server, if `task_list`
or `niche_list` returns empty, `_save_state()` is missing.

### ✅

Thinking servers persist cognitive state to disk so chains, models, patterns,
and decisions survive restarts. **JSON auto-save every N tool calls + atexit graceful shutdown.**

**Pattern**:
```python
class Session:
    def to_dict(self) -> dict:
        return {"chains": self.chains, "assumptions": self.assumptions, ...}
    @classmethod
    def from_dict(cls, d: dict) -> "Session":
        s = cls(); s.chains = d.get("chains", {}); ...

_SAVE_INTERVAL = 10  # save every N calls

def _auto_save():
    global _save_counter
    _save_counter += 1
    if _save_counter >= _SAVE_INTERVAL:
        _save_state()

def _save_state():
    state = {"sessions": {sid: s.to_dict() for sid, s in _sessions.items()}, ...}
    tmp = str(STATE_FILE) + ".tmp"
    json.dump(state, open(tmp, 'w'))
    os.replace(tmp, STATE_FILE)  # atomic on all platforms

def _load_state():
    if STATE_FILE.exists():
        state = json.load(open(STATE_FILE))
        _sessions = {sid: Session.from_dict(sd) for sid, sd in state["sessions"].items()}
```

**Key rules:**
1. Place `_auto_save()` inside `_get_session()`, NOT in `handle_message()`.
   All 3 server variants (server.py, server_native.py, server_shm.py) call
   `_get_session()` → single hook covers all dispatch paths.
2. SHM server MUST import and call `_load_state()` before `run()`:
   ```python
   from server import _load_state, _save_state
   if __name__ == "__main__":
       _load_state()
       try: server.run()
       finally: _save_state()
   ```
3. Graceful shutdown: `_save_state()` in `finally:` or via `atexit.register()`.
4. **Named chains never pruned.** Only auto-generated (`chain_N_*`) compete for slots.
5. **Use `.get()` for ALL handler params** — `args["rationale"]` → KeyError kills persistence.

**Anti-patterns:**
- Saving on every `handle_message()` — misses SHM server dispatch path
- Saving in `tools/call` branch only — native servers have different dispatch
- Using bracket access for params in persistence-sensitive handlers

---

## Dashboard HTTP Metrics API (June 2026)

Thinking servers can expose a lightweight HTTP metrics endpoint for dashboards.
**Runs on a daemon thread — zero interference with MCP operations. Stdlib only.**

**Integration:**
```python
def _start_dashboard(port: int = 9876):
    import threading, http.server
    dashboard_html = open(Path(__file__).parent / "dashboard.html").read()
    
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/":          # HTML dashboard
                body = dashboard_html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/metrics": # JSON API
                body = json.dumps(_build_metrics()).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(body)
            elif self.path == "/health":  # Health check
                self.send_response(200); self.end_headers()
                self.wfile.write(b"OK")
    
    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

# In main():
if "--dashboard" in sys.argv:
    port = int(sys.argv[sys.argv.index("--dashboard") + 1]) if ... else 9876
    _start_dashboard(port)
```

**`_build_metrics()` structure:**
```json
{
  "server": "lumen-thinking", "version": "3.0.0",
  "totals": {"chains": N, "patterns": N, "decisions": N, "model_entities": N, ...},
  "top_chains": [{"chain_id": "...", "thoughts": N, "session": "..."}],
  "preserved": [{"label": "...", "priority": "high", "content": "..."}],
  "sessions_detail": {"default": {"chains": N, ...}, ...},
  "timeline": [{"ts": timestamp, "calls": N}, ...]
}
```

**Dashboard HTML**: Vanilla JS (no Alpine.js — timing issues with x-data registration).
Fetch `/metrics` every 3s, render with `innerHTML`. Canvas-based SVG chart for timeline.

**CORS REQUIRED** for cross-origin dashboards (Vercel → localhost).

**Pitfall**: NEVER inline HTML as Python `r"""..."""` string. Em dashes (`—`), `</script>` tags,
and CSS backslash sequences break Python raw strings. Load from file: `open("dashboard.html").read()`.

**Pitfall — Dashboard ID mismatches (June 2026)**: `getElementById` calls must match actual HTML `id` attributes. 3 mismatches found — `tb-` vs `brk-`, `mem-t` vs `mem-total`, `mem-c` vs `mem-chains`. Also verify bridge field names match the API (`chain_id`, not `chain_a`/`chain_b`). See `references/dashboard-fixes-june-2026.md`.
`x-init` evaluation, and `_x_dataStack` access all have timing issues that are hard to debug.
Use **vanilla JavaScript**: `fetch('/metrics')` + `innerHTML` + Canvas for charts. Zero dependencies,
zero timing issues. This is the approach used in the production dashboard at
`implementations/mcp-servers/thinking/dashboard.html`.

## ✅ Dashboard rendering pitfalls (June 2026)

25 tools had the return `len(clusters) themes · len(thoughts) thoughts` from thought_summarize copy-pasted to them — those variables don't exist in any other function. **Audit**: `grep -c 'len(clusters) themes' server.py` should return exactly 1. See `references/dashboard-rendering-pitfalls.md`.

`window.renderData` must be defined in the dashboard HTML, called by both WebSocket client and HTTP fallback. Update KPIs by element ID (`kpi-thoughts`, `kpi-score`, `kpi-contra`, `kpi-calls`) not by CSS class name.

System Pulse cards: encode work objects via `encodeURIComponent(JSON.stringify(w))` for safe onclick embedding. NOW filter only shows works started <60min ago.

---

## Post-Patch Validation (June 2026)

After every patch that modifies `server.py` or `dashboard.html`, run the built-in validator:

```bash
python implementations/mcp-servers/thinking/post-patch-validator.py
```

The validator checks:
1. **Python syntax** — `py_compile` ensures server.py parses
2. **JS brace balance** — dashboard inline scripts must have matching `{`/`}`
3. **HTML div balance** — `<div>` and `</div>` counts must match
4. **JS element ID consistency** — every `$('id')` reference must have a matching `id="id"` in the HTML
5. **No duplicate function definitions** — prevents corrupted plugin files

**Pitfall discovered (June 2026)**: `execute_code` string replacements often break brace balance or create duplicate function definitions. Always validate after multi-tool edits. The validator catches these before the server crashes.

See `references/post-patch-validation.md`.

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

**Real benchmark data (June 2026)**: See `references/shm-benchmark-2026-06-19.md`
for latency, wire compression, and vs-built-in comparison across 19 tools.

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

| Server | Patterns | Tools | Key Learnings |
|--------|----------|-------|---------------|
| `filesystem/` | A + B + C | **13** 🔥 | Schema parity, output_mode, bulk ops, streaming. **4 new Windows parity tools (June 2026):** `file_info`, `disk_usage`, `search_filename`, `find_duplicates`. SHM: 8 MiB ring buffers, MAX_SPIN=50M. **9× faster than Hermes built-ins** (4.1ms vs 33ms avg). 280-call stress: 0 errors. |
| `web/` | A + B + C | 2 | DuckDuckGo API + HTML fallback, multi-agent cache. |
| `thinking/` | A + B + C | **44** 🔥 | TF-IDF in stdlib, cognitive safety, session isolation. **5 token-efficient tools (June 2026):** `state_snapshot`, `thought_compress`, `chain_diff`, `tool_cache`, `batch_call` — output <50 chars each, 90-95% savings. **Enterprise verified:** 20K calls/sec, 40% batch savings, 36% cache savings over 3 days. **LUMEN WebSocket transport (June 2026):** 80% compression on dashboard data. See `references/token-efficient-tools-pattern.md`. |

## Transport Comparison

| Feature | Pattern A (wrapper) | Pattern B (native) | Pattern C (SHM) |
|---------|:---:|:---:|:---:|
| Wire savings | 32-60% | 55-80% | 55-80% |
| Payload copy | ×2 (kernel) | ×1 (kernel) | **Zero-copy** |
| PROBE/ACK | ❌ (force_json_rpc) | ✅ Auto-negotiate | ✅ Auto-negotiate + SHM |
| MUX channels | ❌ | ✅ | ✅ |
| STREAM_DATA | ❌ | ✅ | ✅ |
| Client config | `lumen_force_json_rpc: true` | `transport: lumen` | Plugin `lumen-shm-bridge` |
| Server file | `server.py` | `server_native.py` | `server_shm.py` |
| Hermes ready | ✅ | ❌ (binary pipes via MCP config) | ✅ (via plugin bridge — auto-spawns SHM servers) |
| Windows parity | ✅ | ✅ | ✅ (native, no shell deps) |
| Benchmark vs Hermes | — | — | **9× faster** (4.1ms vs 33ms avg) |
| Windows parity | ✅ | ✅ | ✅ (native, no shell deps) |
| Benchmark vs Hermes | — | — | **9× faster** (4.1ms vs 33ms avg) |

## Hermes Plugin Bridge Pattern (Binary Pipes Workaround)

**When Hermes' `LumenStdioTransport` can't use binary pipes, a Hermes plugin can bypass the limitation entirely.**

**Plugin handler signature (CRITICAL — June 2026)**:
Hermes passes ALL tool parameters as a **single dict in the first positional
argument**, NOT as individual keyword arguments. Handlers MUST use `*args`:

```python
# ❌ WRONG — receives dict as 'path', returns empty silently
def handle_read_file(path: str, offset: int = 1, limit: int = 500) -> str:
    # path = {"path": "C:\\...", "offset": 1, "limit": 500}  ← DICT, not string!
    ...

# ✅ CORRECT — extracts params from dict
def handle_read_file(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    path = params.get("path", "")
    offset = params.get("offset", 1)
    limit = params.get("limit", 500)
    ...
```

**Debugging silent handler failures**: When a handler returns empty (0 chars,
no error logged), it's almost always a signature mismatch. Hermes silently
converts the TypeError to an empty string. Evidence: `tool read_file completed
(0.35s, 0 chars)` with 0.35s latency — too fast for actual server work,
confirming the handler short-circuited before any I/O.

**Plugin config format (migrated June 2026)**:
The old legacy dict format no longer works. Use the manifest-based list format:

```yaml
# ✅ CORRECT (manifest-based)
plugins:
  enabled:
    - lumen-shm-bridge

# ❌ WRONG (legacy — silently ignored)
plugins:
  lumen-shm-bridge:
    enabled: true
```

**`hermes config set` string trap**:
The CLI command stores values as YAML STRINGS, not native types:

```bash
# ❌ Sets plugins.enabled = "['lumen-shm-bridge']"  (STRING, not list!)
hermes config set plugins.enabled "['lumen-shm-bridge']"

# ✅ Use Python to write proper YAML list
python -c "
import yaml
cfg = yaml.safe_load(open('config.yaml'))
cfg['plugins'] = {'enabled': ['lumen-shm-bridge']}
yaml.dump(cfg, open('config.yaml', 'w'))
"
```

Verify with `hermes plugins list | grep shm` — should show `enabled`, not `not enabled`.

**Plugin manifest requirement (CRITICAL)**:
Hermes discovers plugins via `plugin.yaml` manifests, NOT bare `__init__.py`:

```yaml
# ~/.hermes/plugins/lumen-shm-bridge/plugin.yaml
name: lumen-shm-bridge
version: 1.0.0
description: "LUMEN Level 2 zero-copy MCP bridge"
author: Cadences Lab
kind: standalone
```

Without `plugin.yaml`, `hermes plugins list` won't show the plugin and it
won't load — even with `plugins.enabled` correctly configured. The directory
must contain BOTH `plugin.yaml` AND `__init__.py` (with `register(ctx)`).

**Valid plugin kinds**: `standalone` (hooks/tools, opt-in via `plugins.enabled`),
`backend` (provider for existing tool), `exclusive` (single active provider),
`platform` (gateway adapter), `model-provider`.

**Architecture**: `LLM → Hermes → Plugin handler → SHM ring buffer → Server`
The LLM sees standard tool names (`read_file`, `web_search`, etc.) — the plugin
overrides built-ins with `override=True`. Zero Hermes core changes needed.

**Reference plugin**: `hermes/plugins/lumen-shm-bridge/__init__.py` —
`ShmServerConnection` class, 44 tool handlers (13 filesystem + 29 thinking + 2 web),
`register(ctx)` function. Uses generic `_make_thinking_handler` factory for
the 29 cognitive tools. All 44 tools verified in full benchmark (June 2026): 0 errors, 3,662 thinking calls/sec, 525 FS calls/sec burst.

**MCP config path deprecated**: The `config.yaml` MCP server entries (`lumen_filesystem`,
etc.) cannot use `transport: lumen` because Hermes' `LumenStdioTransport` spawns
subprocesses with text pipes. Native LUMEN binary frames fail with UTF-8 decode errors.
The plugin path is the sole working integration method. Hermes PR #47740 was closed
in favor of this approach.

## Protocol Development Workflow

For protocol-level changes (new frame types, RFC updates, cross-language interop),
see `references/protocol-development.md`. Covers the audit→fix→implement→RFC cycle,
publishing workarounds, and project conventions.

- **[SHM Benchmarks & Limits](references/shm-benchmarks.md)** — 280-call stress test results, latency comparisons vs Hermes built-in, ring buffer limits, wire savings by payload size.

## Related Skills

- **[lumen-thinking-server-dev](lumen-thinking-server-dev)** — STREAM_DATA token streaming, MUX channel multiplexing, Windows-safe frame parsing for thinking servers
- **[lumen-mcp-server-pattern](lumen-mcp-server-pattern)** — Proven patterns: shared_tools (anti-duplication), session isolation, eval framework, security hardening
