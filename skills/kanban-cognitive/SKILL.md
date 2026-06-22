---
name: kanban-cognitive
description: Cross-session Kanban by cognitive niche — task management with auto-sync to work_log, linked to chains/patterns/decisions, dashboard drag & drop. SHM + MCP, independent of Hermes built-in kanban.
version: 3.5.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, kanban, tasks, cross-session, cognitive, niche, SHM, MCP]
---

# Kanban Cognitive

> Cross-session Kanban by **cognitive niche** (project/area). **16 tools** (10 kanban + 3 web + 3 Q&A scratchpad) + dashboard UI with drag & drop, HTTP endpoints, integrated with existing LUMEN systems (sequential_thinking chains, patterns, decisions, work_log, cognitive Q&A). **Not tied to Hermes** — runs via LUMEN SHM + MCP, works with any MCP client.
>
> Also includes cognitive web tools (web_snapshot, web_snapshots_list, task_link_url) for saving web research results as persistent snapshots linked to tasks.

## Architecture

```
NICHO (Cognitive Niche)          TASK (Card)
┌─────────────────────┐         ┌─────────────────────────────┐
│ id: "lumen-protocol"│         │ title: "Implement /negotiate"│
│ name: string        │         │ niche: "lumen-protocol"      │
│ columns: [Backlog,  │         │ status: backlog|in_progress   │
│   In Progress, Done]│         │   |done|blocked              │
│ color: "#22d3ee"    │         │ priority: low|medium|high     │
└─────────────────────┘         │ links: [chain_id, pattern_id] │
                                └─────────────────────────────┘
```

## 15 LUMEN Tools (10 Kanban + 3 Web + 2 Unified)

| Tool | Params | Function |
|------|--------|---------|
| `niche_create` | name, desc, color, [columns] | Create cognitive niche (project/area) |
| `niche_list` | - | List/navigate all niches |
| `niche_update` | niche_id, [name, desc, color, archived] | Edit niche properties or archive |
| `task_create` | niche_id, title, desc, priority, tags | Create task in backlog |
| `task_move` | task_id, to_column, [title, desc, priority, tags] | Move across columns + edit |
| `task_link` | task_id, [chain_id, pattern_id, decision_id] | Link to LUMEN cognitive context |
| `task_list` | niche_id, status, tag, search | Filter & search tasks |
| `task_delete` | task_id | Permanently delete a task |
| `kanban_stats` | [niche_id] | KPIs: counts by column, priority, links, blockers |
| `task_search` | query, [niche_id, status, priority, tag, limit] | Full-text search across title, desc, tags, reference IDs |
| `web_snapshot` | url, [max_chars, task_id] | Extract web page + save as persistent cognitive snapshot, optionally link to task |
| `web_snapshots_list` | [task_id, limit] | List saved web snapshots by task or all |
| `task_link_url` | task_id, url | Link a URL to a kanban task's references |
| `unified_search` 🆕 | query, [limit] | Search across ALL subsystems: tasks, patterns, decisions, Q&A, model, web snapshots. Results grouped by type |
| `cognitive_integrity` 🆕 | - | Health check: unlinked tasks, unanswered Q&A, stale decisions, unused patterns. Returns health score 0-100 |
| `qa_ask` | question, [answer, context, tags] | Ask a question and store Q&A pair as persistent cognitive artifact — the deterministic brain recording what the LLM non-deterministic brain processed |
| `qa_list` | [tags, limit] | List stored Q&A pairs, filterable by tags |
| `qa_link` | qa_id, [task_id, chain_id] | Link a Q&A pair to a kanban task or reasoning chain |

### HTTP Endpoints (Dashboard)

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/kanban` | GET | All niches + tasks (optional `?niche_id=X`) |
| `/kanban/stats` | GET | KPIs per niche (optional `?niche_id=X`) |
| `/kanban/move` | POST | Move task column (receives `{task_id, to_column}`) |

### Auto-Sync with work_log

```
task_move(task_id, to_column="in_progress")
  → work_start(title=task.title)  [auto]
  → Adds duration tracking

task_move(task_id, to_column="done")
  → work_done(block_id=task_id)   [auto]
  → Records completion time

task_move(task_id, to_column="blocked")
  → work_block(block_id=task_id)  [auto]
  → Shows in ⬛ BLOCKED pulse zone

Tasks in "backlog" status:
  → NOT synced to work_log
  → Only visible in kanban view
```

### Dashboard Integration ✅

The kanban dashboard is served by the thinking server's HTTP server (port 9876 or custom via `--dashboard N`). See `references/dashboard-kanban-panel.md` for full implementation details.

- **Kanban panel**: Collapsible section below System Pulse, with niche selector dropdown, drag-and-drop cards, New Task button
- **Per-niche view**: Select a niche from dropdown → shows columns (Backlog, In Progress, Review, Done, Blocked) with task cards
- **Task cards**: Title, priority icon (▽/◇/▲/!!), truncated description, link badges (🔗 chains, 🐞 patterns, 📋 decisions)
- **Drag & drop**: Drag card between columns → POST /kanban/move → auto-refresh
- **New task form**: Prompt title + description → POST /kanban/move (internal create) → auto-refresh
- **Niche selector**: Shows all non-archived niches with their color
- **KPIs panel**: `/kanban/stats` returns counts per column, per priority, total links, blocked count per niche
- **Niche stats panel**: Can be shown in dashboard via dedicated stats calls

### HTML Structure

The kanban panel is added inline in `dashboard.html`:
- HTML: A `<div id="kanban-board">` that renders columns horizontally (overflow-x auto)
- JS: `loadKanban()` fetches `/kanban` or `/kanban?niche_id=X`, `renderKanban()` builds column HTML with draggable cards
- Drag handlers: `kanbanDrag()` (sets data-transfer), `kanbanDrop()` (reads target column, calls POST /kanban/move)
- New task: `showNewTaskForm()` (prompt → POST with `_create` action)
- Autoload: `loadKanban()` called at the end of `refresh()` (every 10s alongside metrics)

### Server-side Registration

The kanban endpoint is registered in `do_GET` and `do_POST` inside `_start_dashboard()`:
- `/kanban` handler reads `_niches` and `_tasks` globals, returns JSON
- `/kanban/move` POST handler updates task status and calls `_save_state()`
- `/kanban/stats` GET handler returns computed statistics

## Links to LUMEN Systems

| System | Link | Dashboard shows |
|--------|------|----------------|
| work_log | Auto-sync on task_move | Duration, status, start/done timestamps |
| chains | task_link(chain_id) | 🔗 badge, click → modal con thoughts |
| patterns | task_link(pattern_id) | 📋 badge, click → pattern description |
| decisions | task_link(decision_id) | 📝 badge, click → decision rationale |

## Status: IMPLEMENTED ✅ (16 tools + HTTP + dashboard + web + Q&A integration)

All 10 kanban tools + 3 web tools + dashboard + HTTP endpoints + /negotiate + auto-sync + web integration (web_snapshot, web_snapshots_list, task_link_url) are fully implemented in:

### File locations

| Component | File | Lines |
|-----------|------|-------|
| Data structures | `server.py` → `_niches`, `_tasks` globals + state persistence | +10 lines |
| Handler functions | `server.py` → 10 tool_* functions (niche_create/list/update, task_create/move/link/list/delete, kanban_stats, task_search) | ~300 lines |
| Tool registration | `plugin/__init__.py` → 10 register_tool calls | ~150 lines |
| HTTP endpoints | `server.py` → do_GET (3 routes), do_POST (1 route) in _start_dashboard Handler | ~100 lines |
| Dashboard HTML | `dashboard.html` → kanban section with JS rendering, drag & drop, niche selector | ~200 lines |
| Persistence | `server.py` → `_save_state()` + `_load_state()` includes niches/tasks | ~8 lines |

## /negotiate Endpoint (Cross-Session Auto-Negotiation) ✅

The `/negotiate` POST endpoint (in do_POST) implements Phase C of LUMEN Cognitive OS — cross-session state sharing:

- Export patterns, chains, decisions from source session
- Import into target session (deduplication)
- Resource filtering (type=patterns|chains|decisions|all)
- Returns bundle metadata (size, version, source)

## Q&A Cognitive Scratchpad (Deterministic Brain) 🧠

Three tools that implement the **cognitive scratchpad** — a bridge between the deterministic brain (LUMEN) and the non-deterministic brain (LLM). Questions and answers are stored persistently as cognitive artifacts, linkable to tasks and chains.

### Architecture Vision

```
DETERMINISTIC (LUMEN)          NON-DETERMINISTIC (LLM)
══════════════════════         ══════════════════════
state_snapshot                 creative writing
pattern_record/match           interpretation
decision_log                   hypothesis generation
model_add/map/query            response generation
assume/check_assumption        context understanding
work_start/done/log            ambiguous queries
niche/task kanban              ...
web_snapshot                   
qa_ask/list/link ← BRIDGE ───→ LLM answers the question
```

LUMEN provides the **memory and structure** that the LLM lacks on its own. The scratchpad stores the Q&A pairs deterministicly (what was asked, what was answered, when, linked to what). The LLM side generates the creative response.

### Tools

| Tool | Purpose | File |
|------|---------|:----:|
| `qa_ask(question, answer?, context?, tags?)` | Store a Q&A pair. Answer can be provided immediately or as "(pending LLM response)" for later filling. Tags enable filtering. | server.py: `tool_qa_ask` |
| `qa_list(tags?, limit?)` | List Q&A pairs sorted by newest first. Filter by tag (string or array). Shows question preview + answer preview + links. | server.py: `tool_qa_list` |
| `qa_link(qa_id, task_id?, chain_id?)` | Link a Q&A pair to a kanban task (appears in `references.qa[]`) and/or a reasoning chain. Updates both the qa record and the task's references. | server.py: `tool_qa_link` |

### Storage

`_qa_pairs` dict maps `qa_<unix_timestamp>` → `{id, question, answer, context, tags[], task_id, chain_id, created_at, updated_at}`. Persisted in `_save_state()` under `"qa_pairs"` key alongside niches, tasks, and web_snapshots.

**CRITICAL**: Unlike session-bound tools, `_qa_pairs` is a global-state tool. It does NOT call `_get_session()` and thus never triggers `_auto_save()`. Every tool handler that modifies `_qa_pairs` MUST call `_save_state()` explicitly.

### Plugin Registration

```python
ctx.register_tool(name="qa_ask", ...)
ctx.register_tool(name="qa_list", ...)
ctx.register_tool(name="qa_link", ...)
```

All use `_make_thinking_handler("tool_name")`.

### Deterministic Brain Pattern (recorded as Pattern #25)

The `pattern_record` and `decision_log` tools were used to formally capture this architecture:

- **Pattern #25**: `lumen-deterministic-brain` — LUMEN = deterministic brain (structure, persistence, rules, tracking). LLM = non-deterministic brain (creativity, interpretation, generation). Together they form a complete cognitive system.
- **Decision #9**: LUMEN Cognitive Architecture — LUMEN handles state, memory, patterns, decisions, model, work tracking, persistence. LLM handles creativity, interpretation, response generation. Communication via MCP tools.
- **Model entity**: `LUMEN:cognitive-architecture` with the full architecture document.

When to use Q&A tools:
- User asks a question that should be remembered across sessions → use `qa_ask` with the answer
- User gives instructions for future behavior → store as Q&A with relevant tags
- Need to link research to a task → `qa_ask` then `qa_link`
- Reviewing past Q&A → `qa_list` with tag filter

### Reference

- Pattern #25 `lumen-deterministic-brain` — recorded with `pattern_record`
- Decision #9 LUMEN Cognitive Architecture — recorded with `decision_log`
- Model entity `LUMEN:cognitive-architecture` — recorded with `model_add`



| Tool | Purpose | File |
|------|---------|:----:|
| `web_snapshot(url, max_chars=10000, task_id=None)` | Extract web page + save as persistent cognitive snapshot + optionally link to kanban task via `_tasks[id].references.urls[]` | server.py: `tool_web_snapshot` |
| `web_snapshots_list(task_id=None, limit=20)` | List saved web snapshots filtered by task or all | server.py: `tool_web_snapshots_list` |
| `task_link_url(task_id, url)` | Link a URL to a kanban task's references. Post-link, the URL appears in `GET /kanban` output under `references.urls`. | server.py: `tool_task_link_url` |

**Architecture**: `web_helpers.py` (in `implementations/mcp-servers/thinking/`) contains `extract_page()`, `safe_fetch()`, `is_safe_url()` — SSRF-safe web extraction with IPv4/IPv6 private network filtering, redirect following, and 5MB size cap. Imported by server.py as `from web_helpers import extract_page`.

**Storage**: `_web_snapshots` dict maps `snap_<unix_timestamp>` → `{id, url, title, content, word_count, task_id, created_at}`. Persisted in `_save_state()` under `"web_snapshots"` key.

**Plugin**: 3 tools registered in `lumen-shm-bridge/__init__.py` with `_make_thinking_handler("tool_name")`.

See `references/web-snapshot-tools.md` for full design and code snippets.


## State Sync: MCP ↔ HTTP Dashboard (Architecture Notes)

The kanban system runs **two separate Python processes** sharing `.thinking_state.json`:

| Process | Role | When it runs |
|---------|------|-------------|
| MCP server | Handles tool calls (niche_create, task_create, etc.) | Spawned by Hermes plugin via STDIN/STDOUT |
| HTTP dashboard | Serves `/kanban`, `/kanban/stats`, `/kanban/move` | `server.py --dashboard N --standalone` |

Both use the same `server.py` and state file but have **separate in-memory copies** of `_niches`/`_tasks`. A `task_create` via MCP updates the MCP process's memory + saves to disk. The HTTP process only loads state at startup.

**Sync mechanism**: `_reload_state_if_changed()` watches file mtime. If changed since last read, reloads.

**Closure scoping lesson**: Methods of a nested class (`MetricsHandler.do_GET`) are NOT closures over the enclosing function's locals. Defining a helper inside `_start_dashboard()` does NOT make it accessible from `do_GET`/`do_POST`. The helper must be a module-level function or a method of MetricsHandler.

**Correct approaches**:
1. Inline reload logic at the start of each handler (simplest)
2. Define reload as a method of MetricsHandler: `def _reload_state_if_changed(self):`
3. Define at module level, reference globals

## 👽 LUMEN Tool Convention (June 2026)

All LUMEN MCP tools are prefixed with **👽** in Hermes chat to visually distinguish them from built-in Hermes tools:

```
👽 state_snapshot → 10c · 32t · 418 calls    (LUMEN tool)
👽 niche_list     → 14 niches                  (LUMEN tool)
terminal          → build output...             (Hermes built-in, NO 👽)
```

**Display rules:**
1. 👽 appears BEFORE the tool name in the assistant's response text
2. Built-in Hermes tools (terminal, read_file, web_search from Hermes) NEVER get 👽
3. **NO descriptions by default** — the user is an expert who already knows what each tool does. Descriptions are ONLY added when: (a) the tool is complex/rarely used, (b) the result is unexpected, or (c) the user asks "what does this do?".
4. The reader should instantly know "this went through our MCP" vs "this used Hermes internals"

This convention was user-requested (June 2026) to provide visual confidence that our custom tools are being used, not Hermes defaults.

Built-in Hermes tools (terminal, read_file, web_search from Hermes) do NOT carry the marker.

## Debugged During Session 🔧

Two bugs were found and fixed during development:

### 1. POST /kanban/move → "Unknown endpoint" (FIXED ✅)
- **Root cause**: Port 9876 accumulated zombie Python processes that served stale code (without `/kanban/move` handler). The new server couldn't bind the port.
- **Fix**: Kill ALL listeners on :9876 before restarting. See `references/port-zombie-cleanup.md`.
- **Secondary fix**: Moved `/kanban/move` from an `elif` deep in the chain to the FIRST `if` in `do_POST`, avoiding any elif chain issues.
- **Lesson**: Always check for zombies when POST endpoints mysteriously return 404 but GET works.

### 2. task_search shows wrong task ID (FIXED ✅)
- **Root cause**: The handler used the outer loop variable `tid` (last value from `for tid, task in _tasks.items()`) instead of `t['id']` in the render loop.
- **Fix**: Changed `#{tid}` to `#{t['id']}` in the render string.

## Pitfalls

- **Plugin must be re-loaded**: Adding new tools to the plugin __init__.py requires a Hermes restart (or new session) to take effect. Server-side changes to server.py take effect on MCP server restart.
- **POST /kanban/move "Unknown endpoint" → check zombies**: The most common cause is zombie server processes on port 9876 (left by Hermes plugin spawning `server.py --dashboard` on each restart). Fix: kill all processes on that port via `taskkill //F //PID ...` or use the PID file mechanism in server.py (`.dashboard.pid`). The code itself is correct.
- **batch_call uses `args` not `params`**: When using `batch_call`, the tool argument key is `"args"`, NOT `"params"`. Incorrect: `{"name":"task_create","params":{...}}`. Correct: `{"name":"task_create","args":{...}}`. Using `params` silently drops all arguments (no error, but task_create returns "niche_id required" which batch_call counts as success since no exception is thrown).
  ```python
  # ✅ CORRECT
  batch_call(tools=[{"name": "task_create", "args": {"niche_id": "niche_X", "title": "..."}}])
  # ❌ WRONG — silently fails
  batch_call(tools=[{"name": "task_create", "params": {"niche_id": "niche_X", "title": "..."}}])
  ```

- **Python bytecode cache (`.pyc`) can serve stale handlers**: After editing `server.py`, delete `__pycache__` and all `.pyc` files before restarting: `rm -rf __pycache__ && find . -name '*.pyc' -delete`. Use `python -B server.py` during development to disable bytecode caching entirely.
- **Use Hermes venv Python for standalone server**: The system `python` (uv cpython) may lack permissions to bind ports. Always use: `/c/Users/gonzalo/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe server.py --dashboard N --standalone`
- **elif/else chain in do_GET/do_POST**: When adding new HTTP endpoints inside `_start_dashboard()`, the if/elif/else chain ends with a final `else: 404`. You CANNOT insert a new `elif` after the `else` — Python syntax error. Fix: insert the new endpoint BEFORE the final `else`, or use a standalone `if` (not `elif`) before the else/404 block.
- **pyc cache on Windows**: The compiled `.pyc` bytecode file may persist after editing `server.py`, causing the server to run old code even after restart. Fix: `rm -rf __pycache__` or use `python -B` to disable bytecode caching entirely.
- **task_search variable scoping**: When iterating tasks in `task_search`, use `t['id']` not `tid` — `tid` is the last value from the outer loop (`for tid, task in _tasks.items()`), not the current result's ID.
- **niche_create before task_create**: You MUST create a niche first. `task_create` will fail with "Niche not found" if the niche_id doesn't exist.
- **work_log duplication risk**: Kanban tasks are NOT work_log items. Kanban manages BACKLOG (planned tasks). work_log manages ACTIVE (in progress/done work). Only tasks moved to "in_progress" or "done" should sync to work_log.
- **State explosion cap**: Max 500 tasks total, 100 per niche. Auto-prune tasks older than 90 days.
- **Niche name uniqueness**: IDs are auto-generated (niche_1, niche_2...). Name is a display string, not an ID.
- **Cross-session visibility**: Tasks created in session A are visible in session B immediately (same state.json on disk). No MUX channels needed.
- **Archived niches**: Use `niche_update(niche_id, archived=true)` to soft-delete. Data is preserved.
- **Task columns**: Must match the niche's columns. Default: ["Backlog", "In Progress", "Review", "Done", "Blocked"].
- **VS Hermes built-in kanban**: Our kanban is SHM + MCP, works with any MCP client, not locked to Hermes. Hermes has its own kanban (`hermes kanban` CLI) with dispatch/workers — use that for Hermes-specific multi-profile workflow. Use ours for portable cross-session project management.
- **Server must use --standalone for background**: The thinking server reads stdin (MCP protocol). In background mode (`terminal(background=true)`), stdin closes immediately → the main loop exits → daemon thread (dashboard) stops. Fix: use `--standalone` flag (or modify main() to detect missing tty). The `--standalone` flag was added server-side and is required when not connected via MCP stdio.
- **Port zombie on Windows**: Port 9876 can accumulate zombie listeners after server restarts. These zombies serve STALE code, causing phantom "Unknown endpoint" errors. See `references/port-zombie-cleanup.md` for detection, kill procedure, and prevention.
- To list all reference files: `skill_view(name="kanban-cognitive")` and check `linked_files`.
- **Plugin registration requires Hermes restart**: Adding new register_tool() calls to plugin/__init__.py requires a full Hermes restart (or new session). Server-side changes to server.py take effect on MCP server restart.
- **Kanban JS structure**: The kanban panel in `dashboard.html` uses inline vanilla JS. Key patterns:
  - Columns use `data-col` attribute and `.kanban-col` CSS class for drag-drop detection — NOT fragile CSS selectors like `[style*="min-width:200px"]`
  - `drag-over` CSS class adds border highlight on column during drag; cleaned up via `document.addEventListener('dragend', ...)`
  - The niche `<select>` populates on every `renderKanban()` call (not just first load), preserving current selection
  - Task title truncation at 60 chars, task ID shown as `#task_N`, link badges (🔗🐞📋) shown as colored spans
  - The `_kanbanNiches` and `_kanbanTasks` arrays are cached in-memory and refreshed by `loadKanban()`
  - `loadKanban()` is called from `refresh()` every 10s alongside metrics refresh
- **_decisions is session-scoped, not module-level** (June 2026): `_decisions` is stored inside `Session.decisions`, NOT as a module-level global like `_tasks` or `_niches`. Tools like `cognitive_integrity` and `unified_search` must use `globals().get("_decisions", [])` — but this returns `[]` if decisions are stored inside sessions. Fix: iterate `_sessions.values()` to collect decisions. Same applies to `_patterns` (per-session) vs `_global_patterns` (module-level). Always verify whether a state variable is session-scoped or module-scoped before accessing it.
