---
name: lumen-thinking-hermes-integration
description: '👽 Deep integration guide for Lumen Thinking in Hermes Agent — hooks, plugins, config, subagent usage. Activates the cognitive layer natively. LUMEN tools prefixed 👽 in chat.'
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, thinking, hermes, integration, plugin]
---

# Lumen Thinking — Hermes Deep Integration

How to connect Lumen Thinking's 22 cognitive tools as a native Hermes cognitive
layer. Beyond "MCP server configured" — this is **activation as infrastructure**.

---

## Adding a New Tool to the Thinking Server

Every tool requires changes in **4 places**. Missing any one means the tool won't appear or won't work.

### The 4 places

```python
# 1. TOOLS list — tool schema (name, description, inputSchema)
TOOLS = [
    ...
    {
        "name": "my_new_tool",
        "description": "...",
        "inputSchema": {"type": "object", "properties": {...}, "required": [...]}
    },
] + OBJECTIVE_SCHEMAS

# 2. HANDLERS dict — maps tool name → handler function
HANDLERS = {
    ...
    "my_new_tool": tool_my_new_tool,
    ...
}

# 3. Handler function — actual implementation
def tool_my_new_tool(args: dict) -> dict:
    \"\"\"...\"\"\"
    session = _get_session(args.get("session_id"))
    # ... logic ...
    _auto_save()
    return {"content": [{"type": "text", "text": "..."}]}

# 4. Bridge plugin — register in ~/AppData/Local/hermes/plugins/lumen-shm-bridge/__init__.py
ctx.register_tool(
    name="my_new_tool", toolset="lumen-shm",
    schema={"name":"my_new_tool", "description":"...", "parameters":{...}},
    handler=_make_thinking_handler("my_new_tool"),
)
```

### Critical: Bridge registration is MANUAL

The bridge plugin registers EACH tool explicitly with `ctx.register_tool()`. Adding to `TOOLS` and `HANDLERS` in `server.py` is NOT enough — the bridge won't pick it up. You MUST also add the `ctx.register_tool()` call in the bridge's `__init__.py`.

### Required restart

After modifying `server.py` AND the bridge plugin:
1. Full Hermes restart (the bridge re-imports server.py at startup)
2. The dashboard server also needs restart (it loads HTML once at startup)

`/reset` does NOT refresh MCP tools — only a full restart does.

### Cross-process sync (dashboard vs bridge)

The bridge and dashboard run as SEPARATE processes. Each has its own `_sessions` in memory. The JSON state file (`.thinking_state.json`) is the sync mechanism:
- `_JSON_SNAPSHOT_INTERVAL` controls how often the JSON is written (default 1 = every `_save_state()`)
- Dashboard's `_build_metrics()` reloads from JSON when `file_mtime` changes
- PDB-first writes to SQLite, but dashboard currently reads from JSON for cross-process sync

The thinking server now has 3 variants:
- `server.py` — JSON-RPC over stdio (needs `force_json_rpc: true`)
- `server_native.py` — LUMEN binary protocol (needs binary pipes — blocked on Hermes)
- `server_shm.py` — Level 2 zero-copy SHM (used by plugin bridge, **recommended**)

### Recent fixes (June 2026)

Four thinking server bugs fixed during cognitive wiki benchmark:

1. **Custom chainId now auto-creates** — `sequential_thinking` accepts any `chainId` on first call. Previously returned "Chain 'X' not found" for custom IDs.
2. **`model_add` accepts `entity` parameter** — Plugin passes `"entity"` but handler expected `"path"`. Now accepts both.
3. **`context_preserve` stores labels** — Labels are now persisted in the item dict, making `context_check` able to find items by label.
4. **`model_scan` depth-limited** — Changed from recursive `rglob` (19s on large dirs) to `os.walk` with `max_depth=1` default (10ms typical).

```yaml
# ~/.hermes/config.yaml
mcp_lumen:
  enabled: true

mcp_servers:
  lumen_thinking:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/thinking/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true
```

After `/reset`, all 29 thinking tools appear as `mcp_lumen_thinking_*`.

**IMPORTANT**: The thinking server speaks JSON-RPC natively (not LUMEN binary). Always use `lumen_force_json_rpc: true` in the config. Using `false` (native LUMEN binary transport) will fail silently — tools won't appear.

---

## Phase 1: Auto-Context Preservation Hook

Long conversations (>30 turns) silently lose critical constraints. `context_preserve`
anchors them against decay.

### Hermes Plugin: `lumen-context-anchor`

Create `~/AppData/Local/hermes/plugins/lumen-context-anchor/__init__.py`:

```python
"""Auto-anchor critical context to Lumen Thinking on long conversations."""
from hermes.plugin_api import PluginContext

TURN_THRESHOLD = 30
_anchored = set()

async def on_turn_end(ctx: PluginContext, turn_number: int) -> None:
    label = f"auto_turn_{turn_number}"
    if label in _anchored:
        return
    msgs = ctx.get_recent_messages(n=5)
    content = "\n".join(f"[{m['role']}] {m['content'][:300]}" for m in msgs)
    ctx.call_mcp_tool("lumen_thinking", "context_preserve", {
        "label": label, "content": content, "ttl_seconds": 3600
    })
    _anchored.add(label)

def register(ctx: PluginContext) -> None:
    ctx.register_hook("on_turn_end", on_turn_end)
```

---

## Phase 2: Thought-to-Plan Bridge

`thought_to_plan` converts reasoning chains to actionable plans. Bridge it to
Hermes's `.hermes/plans/` directory.

### Hermes Plugin: `lumen-plan-bridge`

```python
"""Bridge Lumen thought_to_plan → .hermes/plans/ directory."""
from hermes.plugin_api import PluginContext
import pathlib, datetime

def register(ctx: PluginContext) -> None:
    plans_dir = pathlib.Path(ctx.hermes_home) / "plans"

    def lumen_to_plan_handler(args: dict) -> dict:
        result = ctx.call_mcp_tool("lumen_thinking", "thought_to_plan", {
            "chainId": args["chainId"], "format": "markdown"
        })
        chain_id = args["chainId"]
        ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
        plan_path = plans_dir / f"lumen-plan-{chain_id}-{ts}.md"
        plans_dir.mkdir(parents=True, exist_ok=True)
        plan_path.write_text(result["plan"])
        return {"content": [{"type": "text", "text":
            f"Plan saved to {plan_path}\n\n{result['plan']}"}]}

    ctx.register_tool(
        name="mcp_lumen_thinking_thought_to_plan",
        toolset="lumen-native",
        schema=THOUGHT_TO_PLAN_SCHEMA,
        handler=lumen_to_plan_handler,
        override=True
    )
```

---

## Phase 3: Cognitive Tools as Subagent Capabilities

Subagents can use Lumen Thinking tools for isolated reasoning via `inherit_mcp_toolsets: true`.

## Phase 5: Dashboard HTTP API (new — June 2026)

The thinking server now exposes a rich HTTP API alongside MCP stdio. Start with:

```bash
python server.py --dashboard 9876
# Dashboard: http://localhost:9876/
# Metrics:   http://localhost:9876/metrics
# Benchmarks: http://localhost:9876/benchmarks
```

Full endpoint catalog: **[Dashboard API Reference](references/dashboard-api-reference.md)**
Panel-to-metrics field mapping, POST endpoints, request/response examples.

Cognitive audit workflow: **[Cognitive Audit Template](references/cognitive-audit-template.md)**
Step-by-step example using LUMEN tools to audit the dashboard itself.

Key endpoints for agent use:
| Endpoint | Method | Purpose |
|---|---|---|
| `/metrics` | GET | Full cognitive state (chains, wiki, works, patterns, scores, timeline, presence, collisions) |
| `/chain?chain_id=X` | GET | Single chain with all thoughts, scores, revision/branch flags |
| `/benchmarks` | GET | Phase F scorecard: cognitive ROI, reasoning quality, comparative advantage |
| `/benchmarks` | GET | Phase F scorecard: cognitive ROI, reasoning quality, comparative advantage |
| `/wiki` | POST | Create/update wiki page `{title, content, author}` |
| `/claim` | POST | Phase D file lock `{session_id, path, ttl}` → 200 or 409 |
| `/release` | POST | Release file lock |
| `/collisions` | GET | Files touched by ≥2 sessions in 5min window |
| `/clear-chains` | POST | Wipe all chains for a session |
| `/clear-bridges` | POST | Wipe all bridges |

### Wiki persistence via HTTP

The agent can create wiki pages directly via the dashboard API without going through MCP:
```python
import urllib.request, json
data = json.dumps({"title": "My Page", "content": "Knowledge persists here.", "author": "agent"}).encode()
req = urllib.request.Request("http://127.0.0.1:9876/wiki", data=data,
    headers={"Content-Type": "application/json"}, method="POST")
urllib.request.urlopen(req)
```

### Phase D: File claim protocol

When multiple Hermes sessions may touch the same files, use claim/release to prevent conflicts:
```python
# Session A claims file
POST /claim {"session_id": "session-A", "path": "src/important.py", "ttl": 60}
→ 200 {"status": "claimed", "expires_in": 60}

# Session B tries same file
POST /claim {"session_id": "session-B", "path": "src/important.py", "ttl": 60}  
→ 409 {"status": "conflict", "owner": "session-A", "expires_in": 55}
# Session B auto-yields — no human needed

# Session A releases
POST /release {"session_id": "session-A", "path": "src/important.py"}
→ 200 {"status": "released"}
# Ownership auto-transfers to next waiting requester
```

The plugin auto-claims files before read/write operations. Conflicts are handled silently — the losing session yields.

---

## Adding New Thinking Tools

See **[Adding New Tools Guide](references/adding-new-tools.md)** — the 5-step workflow for adding tools to `server.py` and registering them in the bridge plugin. Required changes in `TOOLS[]`, handler function, `HANDLERS{}`, `Session` class (if needed), and bridge `__init__.py`. Always restart Hermes to make new tools available.

## Pitfalls

- **🔴 Silent `_save_state()` failure (critical)**: If `import threading` is missing at module level, or the `_json_snapshot()` function is undefined (lost in git reverts), `_save_state()` throws `NameError` which is silently caught by the try/except. Result: NO state is persisted — works, patterns, decisions, feeling data all exist in memory but never reach PDB or the JSON state file. The bridge and dashboard still serve stale data silently. **Symptoms**: `work_start` returns empty, dashboard shows old works, System Pulse is stale. **Fix**: verify `import threading` is in the imports, and `_json_snapshot()` is defined before `_save_state()`.

- **`_JSON_SNAPSHOT_INTERVAL` must be 1 for cross-process sync**: When bridge and dashboard run as separate processes, they only share state via `.thinking_state.json`. Setting `_JSON_SNAPSHOT_INTERVAL = 1` ensures every `_save_state()` call writes the JSON. The PDB-first docs say 50, but that's only correct when there's ONE process.

- **`work_start/block/done` must call `_save_state()` directly**, not `_auto_save()`. `_auto_save()` only persists when the internal counter reaches `_SAVE_INTERVAL` (10). If the counter hasn't tripped, the work is created in memory but never saved. Use `_save_state()` for immediate PDB + JSON persistence.

- **Dashboard works list uses `[-20:]` not `[:20]`**: The `/metrics` endpoint builds the works array with `for sid, sess in _sessions.items() for w in sess.works[:20]`. Works are in insertion order, so `[:20]` skips the most recent items. Use `[-20:]` to show the last 20 (most recent).

- **Prompt cache invalidation**: Adding MCP servers adds tools to schema. First turn after `/reset` costs more. Subsequent turns reuse cached prefix.
- **Windows Python path**: Always use full path to hermes venv python.
- **Plugin lifecycle**: Plugins loaded at Hermes start. After creating, restart or `/reload-plugins`.
- **ALLOWED_ROOTS sandbox in plugins (🐛 June 2026)**: When creating a plugin that spawns a LUMEN filesystem MCP server as a subprocess, the server's `ALLOWED_ROOTS` defaults to its CWD. If the plugin starts the server from the plugin directory, all file paths are rejected. Fix: set `cwd=os.path.expanduser("~")` in `subprocess.Popen()` so the sandbox covers the user's entire home directory. Without this, even absolute paths are rejected. This applies to any plugin spawning LUMEN MCP servers with sandboxed filesystem access.
- **🔴 BREAKING: `MCPLumenTransport` → `LumenStdioTransport` rename (June 2026)**. The lumen Python package renamed its transport class. If ALL LUMEN tools disappear after a Hermes restart, check the import in Hermes's MCP integration code. Run `python -c "from lumen.transport import LumenStdioTransport; print('OK')"` in the Hermes venv. If the old class name `MCPLumenTransport` is still referenced, the MCP bridge fails to initialize and tools vanish silently. **Fix**: update the import in Hermes to use `LumenStdioTransport` instead of `MCPLumenTransport`. Symptoms: `hermes doctor` shows no errors, `config.yaml` is correct, server works via stdin/stdout terminal test — but tools don't appear in the agent's tool list.
 See **[Transport Diagnostic](references/transport-diagnostic.md)** for a one-liner check.
- **Server reload ≠ Hermes tool refresh**: Reloading the MCP server (e.g. after adding new tools) does NOT update the agent's tool list. A full Hermes restart is required to re-negotiate `tools/list`. A `/reset` only clears conversation context — it does not re-fetch MCP tools.
- **`lumen_force_json_rpc` mismatch**: If the server speaks JSON-RPC natively (like the thinking server), you MUST set `lumen_force_json_rpc: true`. Set to `false` only for servers that speak native LUMEN binary (like the filesystem server). A mismatch causes silent connection failure — Hermes logs no error but tools are unavailable.
- **Dashboard HTML is read once at startup**: When running `server.py --dashboard 9876`, `dashboard.html` is loaded into memory at server start. Any edits to the file require a full server restart to be served. The user will NOT see dashboard changes until you kill and restart the server. Also, always check for duplicate processes on the port: `netstat -ano | grep ':9876 ' | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid; done`
- **`global _last_state_mtime` required in `_build_metrics()`**: Without this declaration, the cross-process state reload never triggers because Python creates a local variable instead of updating the module-level one. The dashboard server and MCP server share `.thinking_state.json` — if the reload is broken, the dashboard serves stale data forever. Always verify with: `grep -n "global _last_state_mtime" server.py`
- **State file overwrite on save**: `_save_state()` writes the current `_sessions` dict to `.thinking_state.json`. If a session was loaded from file with wiki data but then the server saves before processing the wiki, the wiki is zeroed. Always verify after creating wiki pages: `python -c "import json; d=json.load(open('.thinking_state.json')); print(d['sessions']['default']['wiki'])"`
- **Wiki panel overridden by model data**: In the dashboard, `loadWiki()` fetches `/model` and overwrites `#wiki-list` with mental model entities. The correct wiki data from `/metrics` is replaced. Fix: ensure wiki panel uses `d.wiki` from `/metrics`, and model panel uses a separate div `#model-list` with `d.model` from `/metrics`.
- **Server needs `sleep 999 |` on Windows bash**: Without piped stdin, `server.py`'s MCP loop gets EOF immediately and the process exits (taking the dashboard thread with it). Always start as background with: `sleep 999 | python -u server.py --dashboard 9876`. On Windows, never use `&` for backgrounding — use `terminal(background=true)`.

## 🔍 Dashboard Debugging Workflow

When the dashboard shows stale data or wrong HTML:

```bash
# 1. Check file sizes match
echo "Served: $(curl -s http://localhost:9876/ | wc -c) bytes"
echo "Disk:   $(wc -c < dashboard.html) bytes"

# 2. If sizes differ, multiple processes are on the port — kill ALL
netstat -ano | grep ":9876 " | grep LISTENING | awk '{print $5}' | \
  while read pid; do taskkill //F //PID $pid 2>/dev/null; done

# 3. Verify port is clear
netstat -ano | grep ":9876 " | grep LISTENING || echo "Port clear"

# 4. Start ONE clean server
sleep 999 | python -u server.py --dashboard 9876 &

# 5. Verify endpoints
curl -s http://localhost:9876/metrics | python -c "import sys,json; d=json.load(sys.stdin); print('OK:', d['server'])"
```

## 📊 Cognitive Audit Workflow

When the user asks for an exhaustive review, use the full LUMEN stack:

```python
# 1. Start work tracking
work_start({"item": "Audit task description", "category": "audit"})

# 2. Create reasoning chain
sequential_thinking({"thought": "Plan de auditoría...", "thoughtNumber": 1, "totalThoughts": N, "nextThoughtNeeded": true})

# 3. Evaluate each thought for quality
thought_evaluate({"chainId": "chain_X", "thoughtNumber": 1})

# 4. Convert chain to actionable plan  
thought_to_plan({"chainId": "chain_X", "format": "json"})

# 5. Record bugs found as patterns
pattern_record({"pattern_name": "descriptive-name", "description": "Bug description and fix"})

# 6. Document findings in wiki
# via POST /wiki or wiki_create

# 7. Mark work complete
work_done({"work_id": N, "result": "Summary of fixes"})
```

This produces: reasoning chain (survives), bug patterns (compound interest), wiki documentation (institutional memory), work log with duration. See **[Cognitive Audit Template](references/cognitive-audit-template.md)** for a full example and **[Dashboard Audit Pattern](references/dashboard-audit-pattern.md)** for the systematic panel-by-panel verification technique.

#### Security Audit Workflow (Example: Lumen Protocol)\n\nWhen auditing a Lumen‑based system for security issues, follow this pattern using the thinking tools:\n\n1. **Map the attack surface** – use `model_add` to create entities for each component (crypto, macaroon, handshake, filesystem, web, thinking). Record dependencies via `model_add` relationships.\n2. **Record hypotheses** – for each potential flaw, use `assume` with a clear statement and category (e.g., \"crypto\", \"auth\").\n3. **Test each hypothesis** – invoke `check_assumption` with evidence from code review, fuzzing, or benchmark results.\n4. **Detect contradictions** – after gathering evidence, run `thought_contradiction` on the chain to see if any assumptions conflict with proven facts.\n5. **Summarize findings** – use `thought_summarize` on the assumption/thought cluster to group related issues (e.g., crypto bugs, DoS vectors).\n6. **Convert to plan** – feed the summarized chain into `thought_to_plan` to get an actionable remediation checklist.\n7. **Record patterns** – each confirmed bug becomes a `pattern_record` for future detection.\n8. **Close the work item** – use `work_done` to mark the audit as complete, linking to the plan and patterns.\n\nThis workflow was applied to the Lumen protocol audit in this session, resulting in the identification and patching of: MAX_DEPTH missing in Rust/PHP/TS compress, ReDoS timeout missing in search_files, and TypeScript crypto runtime detection.\n\n## Model Tracking (June 2026)
The server now records which LLM model executes each cognitive tool. `Session.model_name` is set on first tool call per session. Plugin auto-detects model from `HERMES_MODEL` env var or `config.yaml`. `/metrics` exposes `model` in `sessions_detail`. `/benchmarks` has `model_usage` breakdown. Dashboard top bar shows active model(s). Enables analytics: which model scores highest on thought_evaluate, detects most contradictions, generates best bridges.
- **Cross-session persistence test**: To verify cognitive data survives across sessions: (1) create chains/wiki/works/patterns via MCP tools, (2) kill dashboard server, (3) restart server, (4) curl GET /metrics and confirm all data is present. The `.thinking_state.json` file in the server directory is the single source of truth — both the MCP server and dashboard server read/write it.