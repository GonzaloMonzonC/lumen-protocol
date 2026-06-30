---
name: lumen-mcp-server-pattern
description: Proven pattern for creating LUMEN MCP servers — JSON-RPC wrapper + LUMEN native binary. Used for filesystem (9 tools), web (2 tools), and thinking (29 tools). Covers session isolation, evaluation framework, and security patterns.
version: 1.1.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, mcp, server-creation, pattern]
---

# LUMEN MCP Server Creation Pattern

Proven pattern for building MCP servers that speak LUMEN. Used successfully
for 3 production servers (40 tools total: filesystem 9, web 2, thinking 29).

## Quick Start

Copy `filesystem/server.py` as template and replace the `TOOLS` list and `HANDLERS`.

## Pattern A: JSON-RPC + LUMEN wrapper (recommended)

```python
# server.py — ~400 lines
import sys, json

TOOLS = [...]  # Your tool schemas
HANDLERS = {}  # Your tool implementations

def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def handle_message(msg):
    # initialize, tools/list, tools/call dispatch
    ...

def main():
    while True:
        line = sys.stdin.readline()
        if not line: break
        msg = json.loads(line.strip())
        handle_message(msg)
```

## Pattern B: LUMEN native binary (advanced)

```python
# server_native.py — ~500 lines
from lumen import build_frame, parse_frame, compress_value, decompress_value
from lumen import TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED, ParseComplete

def read_lumen_frame():
    # Read 1 byte at a time on Windows (read(N) blocks on pipes)
    buf = bytearray()
    while True:
        b = sys.stdin.buffer.read(1)
        if not b: return None
        buf.extend(b)
        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            payload = result.frame.payload
            if result.frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload
```

## Pattern C: Shared Tool Module (anti-duplication)

When both `server.py` and `server_native.py` exist, extract shared code to `shared_tools.py`:

```python
# shared_tools.py — ~600 lines
TOOLS = [...]          # Tool schemas (identical for both transports)
HANDLERS = {...}       # Tool implementations (identical for both transports)

def resolve_path(path: str) -> Path:  # Sandboxed path resolution
    ...

def suggest_similar(filename: str, ...) -> str:
    ...
```

```python
# server.py — ~100 lines (down from ~700)
import shared_tools

def send(msg): ...
def handle_message(msg):
    tool = shared_tools.HANDLERS.get(name)
    ...

# server_native.py — ~165 lines (down from ~570)
import shared_tools

def process_message(msg):
    tool = shared_tools.HANDLERS.get(name)
    ...
```

**Result**: 608 lines extracted from `server.py`, 392 from `server_native.py`. Changes to tool implementations only need one edit. Both servers gain any tools added to `shared_tools` automatically (e.g., `server_native.py` gained `stream_read` + `server_stats` for free).

This pattern was applied to the filesystem server (June 2026). See `implementations/mcp-servers/filesystem/shared_tools.py` for the canonical example.

## Design Principles

1. **Superiority bar**: Only build if strictly better than Hermes built-in equivalent
2. **Structure over content**: LUMEN compresses JSON keys, not file content
3. **Cognitive safety**: Tools that EXPAND perception, never REPLACE judgment.
   - SAFE: Assumption Tracker, Mental Model Builder, Context Decay Detector — show info, don't decide
   - DANGEROUS: Decision Journal, Confidence Tracker — risk of bias, overfitting, dogmatism
   - Rule of thumb: if a tool could automate a decision, it's dangerous. If it only shows information, it's safe.
   - See `references/cognitive-safety.md` for full analysis.
4. **Zero deps**: Python stdlib only (web server uses urllib, no API keys)

## Tool Categories (proven patterns)

### Core Tools (filesystem, web)
Standard request-response. JSON-RPC wrapper + LUMEN transport. ~50-200 lines each.

### Structured Reasoning (thinking)
Chain-based tools with external persistence. ~100-250 lines each.
- sequential_thinking: record, revise, branch
- thought_*: similarity, contradiction, summarize, bridge, evaluate, to_plan

### Cognitive Safety Tools (NEW)
Self-awareness tools that expose blind spots without judging. ~80-150 lines each.
- **Assumption Tracker**: `assume` → `list_assumptions` → `check_assumption`
- **Mental Model Builder**: `model_add` → `model_query` → `model_stats` → `model_map` → `model_remove`
- **Context Decay Detector**: `context_preserve` → `context_check`

### Work Tracking Tools
Persistent work state across sessions. ~80-120 lines each.
- **Work Tracker**: `work_start` → `work_block` → `work_done` → `work_log` — persists `.work_log.json`
- **Context Estimator**: `context_estimate` — rough token usage estimate

### Institutional Memory Tools (NEW)
Cross-session knowledge that survives context compression. ~80-120 lines each.
- **Pattern Memory**: `pattern_record` → `pattern_match` — capture bug patterns and fix strategies. Match new problems against recorded patterns via Jaccard similarity. Tags, categories, match_count tracking.
- **Decision Log**: `decision_log` → `decision_list` — record design decisions with rationale, alternatives, and revisit triggers. Newest-first sorted, filterable by category. Prevents repeated debates about settled questions.

## Silent Override Plugin Pattern (Hermes)

Proven pattern for transparently replacing Hermes built-in tools with LUMEN
MCP equivalents without changing tool names or schemas — the LLM never knows.

### Architecture

```
Hermes Agent
    │
    │  read_file("config.yaml")
    ▼
Plugin (lumen-native-fs)          ← ctx.register_tool(override=True)
    │
    │  JSON-RPC via persistent subprocess
    ▼
LUMEN filesystem MCP server (1 process, N calls)
    │
    ▼
Filesystem
```

### Plugin Template (~100 lines)

```python
# plugins/<name>/__init__.py
import json, subprocess, threading, os

_server = None
_server_lock = threading.Lock()

def _get_server():
    global _server
    with _server_lock:
        if _server is None or _server.poll() is not None:
            _server = subprocess.Popen(
                [PYTHON, "-u", SERVER_PATH],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, text=True, bufsize=1,
                cwd=os.path.expanduser("~"),  # ALLOWED_ROOTS sandbox
            )
            # Initialize MCP handshake
            ...
        return _server

def _call_tool(name, args):
    server = _get_server()
    with _server_lock:
        server.stdin.write(json.dumps({...}) + "\n")
        server.stdin.flush()
        return json.loads(server.stdout.readline())

def register(ctx):
    ctx.register_tool(
        name="read_file",           # Same name as built-in
        toolset="lumen-native",
        schema=READ_FILE_SCHEMA,     # Same schema
        handler=_handle_read_file,   # Routes to MCP
        override=True                # ← Replaces built-in
    )
```

### Key Requirements

- **`cwd` at user home**: Server sandboxes to ALLOWED_ROOTS (default: cwd). Set
  cwd to `os.path.expanduser("~")` so all user files are accessible.
- **Persistent subprocess**: One `subprocess.Popen` per plugin lifetime, not
  per call. Use `threading.Lock` for thread safety.
- **Schema parity**: Copy the EXACT built-in schema from
  `hermes-agent/tools/file_tools.py`. Any divergence breaks prompt cache.
- **`override=True`**: Critical — without it, registry rejects duplicate names.
- **Config**: `hermes config set plugins.<name>.enabled true`

### When to Use

- Replacing 1-4 built-in tools with MCP equivalents for wire savings
- Adding multi-agent shared filesystem access
- Preserving prompt cache while changing I/O backend

**Reference implementation**: `~/AppData/Local/hermes/plugins/lumen-native-fs/__init__.py` (444 lines, Hermes plugin) and `lumen-protocol/implementations/mcp-servers/plugins/lumen-native-fs/__init__.py` (repo copy). Overrides read_file, write_file, search_files, patch with LUMEN filesystem MCP backend. Persistent subprocess, thread-safe, ALLOWED_ROOTS sandbox via cwd.

### Pitfalls

- **Windows Unicode**: Add `sys.stdout.reconfigure(encoding="utf-8")` to server.py
  or replace emoji/box-drawing chars with ASCII. See `lumen-server-development`.
- **Sandbox**: ALLOWED_ROOTS restricts to cwd. Set cwd carefully.
- **Process lifecycle**: Server restarts on crash. Poll `_server.poll()` before use.
- **Python path**: Use full path to hermes venv Python, not system Python.

### Path Sandboxing (filesystem servers)
Prevent path traversal attacks with `ALLOWED_ROOTS` env var:

```python
_ALLOWED_ROOTS = None  # lazy init

def _get_allowed_roots():
    global _ALLOWED_ROOTS
    if _ALLOWED_ROOTS is None:
        env_val = os.environ.get("ALLOWED_ROOTS", "")
        if env_val:
            _ALLOWED_ROOTS = [os.path.realpath(p) for p in env_val.split(",") if p.strip()]
        else:
            _ALLOWED_ROOTS = [os.path.realpath(os.getcwd())]
    return _ALLOWED_ROOTS

def resolve_path(path: str) -> Path:
    p = Path(path).expanduser()
    resolved = p.resolve()
    for root in _get_allowed_roots():
        if resolved.is_relative_to(root):
            return resolved
    raise PermissionError(f"Path escapes allowed roots: {resolved}")
```

### SSRF Protection (web server)
Block requests to private/internal IPs:

```python
import ipaddress, socket, urllib.parse
### SSRF Protection (web server)

Block requests to private/internal IPs. Complete list (12 entries) covers
IPv4 current network, RFC 1918, CGNAT, link-local, multicast, reserved,
plus IPv6 loopback, unique-local, and link-local.

Additionally:
- **Default port**: 443 for HTTPS, 80 for HTTP (not always 80)
- **Redirect handling**: SSRF-check each hop (max 5). `_safe_fetch()` wraps
  `urllib.request.urlopen()` with per-hop `_is_safe_url()` validation.
- **Streaming read**: Never `resp.read()` all-at-once. Use 8KB chunked read
  with a total byte cap (5MB).
- **Cache key**: Include `max_chars` parameter to prevent wrong-cache hits.
  `_cached(f"extract:{url}:{max_chars}", ...)` not `f"extract:{url}"`.

### Filesystem Hardening

- **Default ignore dirs**: .git, node_modules, __pycache__, .venv, venv,
  target, dist, build, .tox, .eggs, .mypy_cache, .pytest_cache, .ruff_cache,
  bower_components, .next, .nuxt + any hidden dir (starts with `.`)
- **Safe rglob**: Don't use `Path.rglob()` directly — it traverses everything
  including node_modules (100K+ files). Use a custom walker that skips ignored
  dirs and enforces a hard file-count limit (10,000).
- **Atomic writes**: `tempfile.NamedTemporaryFile()` + `os.fsync()` +
  `os.replace()` — atomic on both POSIX and Windows. Prevents corrupted files
  on crash.
- **Content size limits**: 5MB max for writes, 10MB max for reads.
  `readlines()` with a size hint prevents loading huge files into memory.
- **File type check**: Always verify `path.is_file()` before reading — not
  just `path.exists()`.

```python
def _should_skip_dir(entry: Path) -> bool:
    return entry.name in _DEFAULT_IGNORE_DIRS or entry.name.startswith(".")

def _safe_rglob(base: Path, pattern: str):
    count = 0
    stack = [base]
    while stack:
        dirpath = stack.pop()
        try:
            for entry in dirpath.iterdir():
                if _should_skip_dir(entry):
                    continue
                if entry.is_dir():
                    stack.append(entry)
                elif entry.match(pattern):
                    count += 1
                    if count > _MAX_SEARCH_FILES:
                        return  # hard stop
                    yield entry
        except (PermissionError, StopIteration):
            continue
```

## Pitfalls

### Frame building
- **`build_size()` positional arg trap**: `build_size(len(payload))` calls `build_size(frame_type=len, payload_len=0)` because `frame_type` was the first positional parameter. This always returns 3 bytes (Hyb128 for 0 + 2 + 0) regardless of payload size. Fixed by making `frame_type` keyword-only: `def build_size(payload_len: int = 0, *, frame_type: int = 0)`. Always verify `build_size()` call sites pass `payload_len` explicitly if unsure.
- **Double-counting build_size**: The original `server_native.py` did `build_size(payload) + len(payload)` — this allocates WAY too much memory. `build_size()` ALREADY includes the payload length. Just use `build_size(len(payload))`. This was bug #70 in plan-mejoras-2.
- `build_frame(type, flags, payload, buf, offset)` writes `build_size(len(payload))` bytes. The buffer must be exactly that size — not larger.
- `decompress_value()` returns dict, not bytes. Don't `json.loads()` it.
- **FLAG_COMPRESSED with raw JSON**: Never set FLAG_COMPRESSED on frames containing `serde_json::to_vec()` output. FLAG_COMPRESSED is only for `compress_value()` output. Getting this wrong causes the receiver to attempt binary decompression on JSON text → silent corruption.
- **Double-counting build_size**: The original `server_native.py` did `build_size(payload) + len(payload)` — this allocates WAY too much memory. `build_size()` ALREADY includes the payload length. Just use `build_size(len(payload))`. This was bug #70 in plan-mejoras-2.

### Platform
- Windows pipes: `sys.stdin.buffer.read(N)` blocks until N bytes or EOF. Use `read(1)`.
- MCP stdio is NOT thread-safe. Benchmark sequentially.
- **Windows charmap encoding (🐛 June 2026)**: All servers MUST add `sys.stdout.reconfigure(encoding="utf-8")` at the top. Without it, any Unicode output (emojis, accented web content, box-drawing chars) crashes `json.dumps(ensure_ascii=False)` + `sys.stdout.write()` with `'charmap' codec can't encode character`. The crash is silent — Hermes retries 4 times in 8 seconds then marks the server unreachable. Also replace non-ASCII chars in output: `█`→`#`, `═══`→`===`, `📁`→`[DIR]`, etc. See `references/windows-encoding-fix.md`.
- **MCP retry exhaustion (🐛 June 2026)**: After 4 consecutive failures, Hermes permanently stops trying to connect an MCP server. Fix: toggle `enabled false` → `enabled true` in config, then `/reset`. The server won't auto-retry otherwise.
- **Python 3.9 compatibility**: `list[str] | None` fails on Python <3.10 at runtime. Add `from __future__ import annotations` to every `.py` file in the MCP server directory. This must be the first import after the docstring. Without it, `filesystem/server.py` crashes on import with `TypeError: unsupported operand type(s) for |`.

### Test portability
- **Never use hardcoded absolute paths** in tests (e.g. `C:\Users\gonzalo\...`). Use `sys.executable` for Python path, `os.path.dirname(__file__)` for repo-relative paths, and `os.path.join(REPO_ROOT, ...)` for server imports.
- `test_roundtrip.py` and `test_suite.py` had hardcoded Windows paths and failed on checkout. Fixed with `sys.executable` + `__file__`-relative resolution.

### Server organization
- `server.py` pattern works everywhere. `server_native.py` needs LUMEN-aware client.
- **`server_native.py` duplicates 95% of `server.py`** — extract shared code to `shared_tools.py` (see Pattern C above). Applied to filesystem server June 2026.
- **Hidden handlers (🐛 recurring)**: `model_scan` was in `HANDLERS` but not in `TOOLS` — callable by name but invisible to `tools/list`. This means the tool exists at runtime but clients never discover it. Every handler MUST have a corresponding schema in `TOOLS` OR be removed from `HANDLERS`. A quick check: `grep -c HANDLERS` should equal `grep -c '"name"' in TOOLS`. The thinking server (June 2026) had 29 handlers but only 28 TOOLS entries — `model_scan` was the hidden one. Fixed by adding the missing schema.
- **Schema parameter naming consistency**: Tool schema parameter names MUST match Hermes built-in equivalents exactly. `search_with_context` used `context_lines` while built-in `search_files` uses `context`. This causes agent confusion. Always check the built-in tool schema for the canonical parameter name. Fixed June 2026.
- **REPO_ROOT in nested test files**: Tests at `implementations/mcp-servers/filesystem/test_roundtrip.py` need `os.path.join(os.path.dirname(__file__), '..', '..', '..')` (3 levels) to reach repo root. Using 2 levels creates a doubled `implementations/implementations/` prefix.

### Thinking server specifics
- **Model staleness**: when files are deleted from the project, call `model_remove` to keep the mental model current. Dependencies auto-update.
- **Assumption overconfidence**: if track record shows >80% confirmed, the tool warns about overconfidence. Don't ignore this.
- **`bare except:` catches SystemExit/KeyboardInterrupt** — always use `except Exception:` instead.
- **`thought_to_plan` dependency direction**: each step depends on the PREVIOUS step (`Step {i-1}`), not the next. The original code had `Step {i+1}` which is logically inverted.
- **TF-IDF vector construction duplicated** in similarity/contradiction/bridge tools — extract to a shared helper.
- **Session migration bugs in work tracker (🐛 June 2026)**: `work_start`, `work_block`, `work_done`, `work_log` used `session` without calling `_get_session()`. `_next_work_id` was missing `global` declaration. `_load_works()` and `_save_works()` also lacked session resolution. All 4 tools raised `NameError` at runtime. Fix: add `session = _get_session(args.get("session_id"))` as the first line of every stateful tool function, and declare `global _next_work_id` where needed. This is a REFACTORING PITFALL — when migrating from global state to per-session state, every function that accesses state needs the session parameter.
- **Session migration**: work tracker tools had incomplete migration from global state to `_get_session()`. `session` variable not defined + `global _next_work_id` was commented out. See `references/session-migration-pitfalls.md`.
- **Hidden handlers**: `model_scan` was in `HANDLERS` but missing from `TOOLS` — callable by name, invisible to `tools/list`. Always verify `tools/list` against `HANDLERS.keys()`. See `references/session-migration-pitfalls.md`.

### Security
- **Path traversal**: Always sandbox filesystem tools with `ALLOWED_ROOTS`. Without it, `../../../etc/passwd` works.
- **SSRF in web tools**: Always validate URLs against private IP ranges before making HTTP requests.
- **SSRF redirect bypass**: `urllib.request.urlopen()` follows redirects automatically WITHOUT re-checking SSRF. Must use a custom `_safe_fetch()` that calls `_is_safe_url()` on every redirect hop (max 5).
- **Cache key missing parameter**: If a cache key is `f"extract:{url}"` but the function's output depends on `max_chars`, two calls with different `max_chars` get the same cached (wrong) result. Cache key must include all parameters that affect output.

### Documentation
- **Honesty over hype**: Never claim "reference implementation", "production-ready", "MUX", "streaming", or specific wire savings % unless reproducible benchmarks exist. Label as "Experimental / Alpha / Demo" until CI is green and security tests pass. See plan-mcp.md for the full audit criteria.

## Multi-Agent Session Isolation

When multiple agents share a single transport (WebSocket, QUIC), they need
private state. The thinking server implements this with a `Session` class:

```python
class Session:
    def __init__(self, label: str = ""):
        self.label = label
        self.chains: dict[str, dict] = {}
        self.assumptions: list[dict] = []
        self.model: dict[str, dict] = {}
        self.works: list[dict] = []

_sessions: dict[str, Session] = {}
_DEFAULT_SESSION = "default"

def _get_session(session_id: str | None = None) -> Session:
    sid = session_id or _DEFAULT_SESSION
    if sid not in _sessions:
        _sessions[sid] = Session(label=sid)
    return _sessions[sid]
```

**Key design decisions:**
- Default session for backward compatibility (no session_id → default)
- `session_init(label)` tool creates/resumes named sessions
- `session_list()` tool shows all active sessions with stats
- Every tool accepts optional `session_id` parameter
- Global state (`_chains`, `_assumptions`, `_model`, `_works`) becomes per-session
- Legacy compat: alias functions return default session state

**Pitfalls during refactoring:**
- `_chains` changed from dict to function — `chain_id in _chains` breaks
  silently. Replace ALL direct accesses with `session.chains`.
- Functions using `_chains.items()`, `_chains.keys()` fail with
  "argument of type 'function' is not iterable". Do a global replace.
- `_update_dependents()` had `session` in scope but didn't receive it
  as parameter. Add `session: Session` parameter explicitly.

## Objective Evaluation Framework

To test MCP tools objectively, use the `eval_framework.py` pattern:

```python
from eval_framework import MCPTestRunner

runner = MCPTestRunner("SERVER NAME")

# Each test captures: tool name, category, pass/fail, latency
runner.test("tool_name", "correctness",
    lambda: "expected" in response_text,
    "detail message")
runner.test("tool_name", "error-handling",
    lambda: "error" in response,
    "invalid input returns error")
runner.test("tool_name", "edge-cases", lambda: ...)
runner.test("security", "security", lambda: ...)

print(runner.report())
# → Scored report per tool with █░░ bars, pass%, avg latency
```

**Test categories:** correctness, error-handling, edge-cases, security.
**Output:** per-tool bar charts with pass%, avg latency, detail messages.

## Project Structure

```
implementations/mcp-servers/<name>/
├── server.py          # JSON-RPC + LUMEN wrapper
├── server_native.py   # LUMEN native binary (optional)
├── test_suite.py      # Comprehensive tests
├── README.md          # Quick start + Hermes config
└── (optional: MEMORY_COMPARISON.md, RETROSPECTIVE.md)
```

## Related

- `references/cognitive-safety.md` — Full analysis of safe vs dangerous cognitive tools
- **[lumen-cognitive-safety](../skills/lumen-cognitive-safety/SKILL.md)** — SAFE/UNSAFE taxonomy, 7-gate audit checklist, implementation rule, regression tests (operationalized version)
- `references/security-hardening-patterns.md` — 10 vulnerability patterns from external audit: X25519 validation, macaroon expiry, depth limits, SHM size, Arc refactoring, TOCTOU, ReDoS, version validation, MITM scope
- `references/windows-encoding-fix.md` — **NEW** — Windows charmap encoding bug: `reconfigure(encoding="utf-8")` + ASCII-safe output replacements for all 3 servers
- `references/session-migration-pitfalls.md` — **NEW** — Work tracker session migration case study: missing `session` variable, `global` declaration, hidden handlers
- `references/plugin-override-pattern.md` — **NEW** — Phase 1 silent override: replacing Hermes built-in file tools with LUMEN MCP via `ctx.register_tool(override=True)`