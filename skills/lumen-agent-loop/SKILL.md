---
name: lumen-agent-loop
description: 'Cognitive Agent Loop — objective-driven autonomous iteration with BUILDER (Q&A), BUILDING (plan→execute→judge loop), and TESTING (validation) phases. Semi-autonomous judge with heuristic scoring.'
version: 1.3.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, agent-loop, objectives, autonomous, judge]
---

# LUMEN Agent Loop

Objective-driven autonomous iteration engine. Define a goal, let the system plan tasks, execute, evaluate, and loop until the judge is satisfied.

## Tools (5)

| Tool | Phase | Function |
|------|-------|----------|
| `objective_create` | BUILDER | Create objective with title, description, criteria. Starts Q&A refinement. |
| `objective_judge` | ALL | Evaluate clarity/completeness. Returns score 0-10 + verdict (ASK/LOOP/PASS/DONE). `mark_done=true` marks all tasks done + verifies criteria + auto-adds test in TESTING. |
| `objective_plan` | BUILDING | Decompose objective into subtasks from criteria. |
| `objective_task_done` ⚠️ | BUILDING | Mark a single task as completed (by task_id). **Handler not yet implemented in objective_loop.py** — the schema/bridge registration exists, but calling it produces no effect. Use `work_done(work_id)` as fallback for granular tracking. |
| `objective_status` | ALL | Progress bar, phase, score, task completion. |

## Architecture

```
                 ┌──────────────┐
    ┌───ASK──────│   BUILDER    │─────score ≥ 8───┐
    │            │  score: 0-10 │                  │
    │            └──────────────┘                  │
    │   User answers questions                     │
    │   → objective refines → judge re-evaluates   │
    │                                              │
    └──────────────────────────────────────────────┘
                                                   │
                                                   ▼
                 ┌──────────────┐
                 │   BUILDING   │◄──────────┐
                 │  plan→do→judge│           │
                 └──────┬───────┘           │
                        │                  │
                 score ≥ 8         score < 8│
                        │                  │
                        ▼                  │
                 ┌──────────────┐           │
                 │   TESTING    │──fail─────┘
                 │  gen→run→judge│
                 └──────┬───────┘
                        │ all pass
                        ▼
                 ┌──────────────┐
                 │   ✅ DONE    │
                 └──────────────┘
```

## Judge Scoring

**Heuristic-based (0 LLM tokens):**

```python
# BUILDER phase: clarity score
desc_score = min(5, len(description) // 30)   # 0-5
criteria_score = min(3, len(criteria))         # 0-3
has_examples = 2 if examples_present else 0    # 0-2
score = min(10, desc_score + criteria_score + has_examples)

# BUILDING phase: completion + criteria verification
completion = done_tasks / total_tasks          # 0-1
score = completion * 7                         # 0-7
score += (verified_criteria / total_criteria) * 3  # 0-3

# TESTING phase: test pass rate
score = (passed_tests / total_tests) * 10      # 0-10
```

**Thresholds:**
- score ≥ 8 → PASS (move to next phase)
- score < 8 → LOOP (generate more tasks/questions)

## Usage Flow

### BUILDER Phase
```
> objective_create("Optimizar dashboard", "Hacerlo responsive para móvil", ["<2s load", "dark mode"])
🎯 Objective #1 → BUILDER | Score: 5/10
   ❓ "¿Qué significa 'responsive'? ¿Qué dispositivos?"

> "Móvil y tablet. <2s en 4G"
...refine criteria...
> objective_judge("goal_1")
⚖️ Score: 8/10 → READY → moving to BUILDING
```

### BUILDING Phase
```
> objective_plan("goal_1")
📋 6 tasks created: viewport meta, CSS queries, image optimization...

> ... execute tasks via tools ...
> objective_judge("goal_1")
⚖️ Score: 7/10 → LOOP (3/6 done, CSS needs work)
📋 Adding 2 more tasks...
```

### TESTING Phase
```
> objective_judge("goal_1") 
⚖️ Score: 10/10 → Testing passed → DONE ✅
```

## Persistence Architecture (PDB-First — June 2026)

Objectives survive server restarts through 3 layers. **PDB is primary, JSON is periodic backup:**

```text
Tool call → _get_session() → _auto_save()
→ every 10 calls: _save_state()
→ PDB: _pdb_save_all() — writes every entity as individual record to _globals(ns='STATE')
→ every 50 saves: _json_snapshot() — periodic JSON backup to .thinking_state.json
→ On restart: _load_state() → _pdb_load_all() first → JSON fallback
```

**Layer 1 — PDB primary**: `_pdb_save_all()` deletes ns='STATE' and re-inserts every entity as a separate record. Each objective becomes `global:objective:{gid}` under ns='STATE'. Single ACID transaction.

**Layer 2 — JSON fallback**: `_json_snapshot()` writes the full state dict to `.thinking_state.json` every 50 saves (not every 10 as before). Includes `**get_objective_state()`.

**Layer 3 — PDB load on restart**: `_load_state()` calls `_pdb_load_all()` first. If PDB has state, it restores everything. Only falls back to JSON if PDB is empty.

**Migration path**: When the server starts and finds only JSON (no PDB ns='STATE'), it loads from JSON. The next `_save_state()` call will write to PDB, completing the migration. After that, PDB is the primary source.

## Pitfalls

- **Cross-process state file corruption (kanban/dashboard GET handler)**: The dashboard HTTP server and the bridge's thinking server are SEPARATE processes sharing `.thinking_state.json`. When the GET /kanban handler calls `_save_state()` before reloading, it overwrites the state file with the dashboard process's in-memory data (which may be stale/empty), DESTROYING changes made by the bridge process. **Fix**: the GET /kanban handler must NOT call `_save_state()` — it should only RELOAD from the file. POST /kanban/move does call `_save_state()` correctly (it's the process that made the change). This applies to any read-only HTTP endpoint that shares state with another process.
- **Kanban mtime check skips reload**: The GET /kanban handler had `if _fm > _last_state_mtime` which skipped reload when mtime was equal (after `_build_metrics()` already read it). Changed to unconditional reload. If you add a new GET endpoint that reads shared state, always reload from file unconditionally.
- **LLM must execute tasks**: The Agent Loop PLANS tasks but the LLM must create/execute them via `task_create`, `work_start`, etc. The loop does NOT auto-execute.
- **Judge is heuristic**: Score relies on task counts and criteria verification. For complex judgment, use `thought_evaluate` to augment the score.
- **Dashboard panel now implemented**: Agent Loop objectives appear in `/metrics` endpoint (key: `objectives`) and dashboard.html has a dedicated panel. See `references/dashboard-integration.md`.
- **PDB persistence must be wired for EVERY new state module**: Adding a new module to the thinking server (like `objective_loop.py`) requires wiring ALL 3 persistence sub-layers. The JSON path is easy (`**get_state()`) but the PDB path (save + load + fallback call) is easy to forget. Without all three, objectives vanish on taskkill when JSON is lost.
- **State auto-save triggers every 10 tool calls**: `_save_counter` increments in `_get_session()`. With `_SAVE_INTERVAL=10`, state persists after every 10 tool calls. If the server is killed before the 10th call, state since the last save is lost.
- **Server_shm.py imports from server.py**: `server_shm.py` line 27: `from server import TOOLS, HANDLERS, _load_state, _save_state`. State persistence patches MUST go in `server.py`. Both `server.py` and `server_shm.py` share the same state file (`.thinking_state.json`).
- **Bridge auto-respawns the thinking server**: Spawns a new server process when the current one dies. The server runs `ShmNativeServer.run()` which blocks on SHM reads (not stdin). On Windows, `sleep 999 | python server_shm.py` adds nothing — the server doesn't read stdin.
- **`objective_task_done` is unimplemented**: The tool has a schema in the Hermes tool registry (registered by the bridge plugin), but the handler `tool_objective_task_done` was **never written** in `objective_loop.py`. Calling it silently does nothing — no error, no state change. **Fallback**: use `objective_judge(goal_id, mark_done=true)` to bulk-complete all tasks + verify criteria. This gap exists because the loop's 4 other tools (create, judge, plan, status, checklist) were implemented in v1, but `task_done` was left as a TODO stub.
- **`work_done` parameter silently fails with `block_id`**: The parameter name is `work_id` (integer), NOT `block_id` (string). Passing `block_id=N` returns empty success with no effect — the work stays `in_progress`. There is no error message. Always use `work_done(work_id=N)`. If even `work_id` produces no result, edit the state file directly: load `.thinking_state.json`, find the work by id, set `"status": "done"` and `"done_at": time.time()`, then save.
- **Stale objectives survive across sessions**: Old objectives (goal_1, goal_4, goal_5, etc.) persist in `objective_status` even after their real-world work was completed months ago. They show BUILDING with Score 0-3/10 because nobody ran `objective_judge(mark_done=true)` on them. **Cleanup**: run `objective_judge("goal_N", mark_done=true)` on each stale goal. If the judge scores < 8 in TESTING phase, the goal will show as TESTING instead of DONE — that's acceptable for historical cleanup. The orphan objectives don't affect current work but clutter the status output.
- **Capture `goal_id` from `objective_create` response**: The return value `🎯 Objective #goal_6` contains the ID. This ID is needed for ALL subsequent calls (`objective_judge`, `objective_plan`, `objective_status`). If you lose it, call `objective_status()` to list all goals with their IDs. The ID format is `goal_N` (1-indexed, sequential).
- **`objective_plan` goal_id required despite empty schema**: The Hermes tool registry schema for `objective_plan` shows no required parameters, but calling it without `goal_id` raises `Error: 'goal_id' required.`. Always pass e.g. `objective_plan(goal_id="goal_6")`. Same applies to `objective_judge` and `objective_status` — they all accept `goal_id` even though the schema doesn't expose it explicitly.

## Reference Files

- `references/agent-loop-test-results.md` — Verified end-to-end test (June 2026) with exact input/output shapes for all 4 tools, behavioral notes, and architecture diagram.
- `references/pdb-persistence-verification.md` — PDB persistence 3-layer fix, code patches applied to server.py, verification checklist.
- `references/full-cycle-verification-2026-06-22.md` — Full BUILDING→TESTING→DONE cycle with real-world doc audit. 3 objectives completed this session.
- `references/cross-process-state-file-corruption.md` — Kanban/dashboard fix: why GET handlers must never call `_save_state()`, and the mtime reload bug.
- `references/tool-count-verification.md` — Multi-server tool count audit: find TOOLS lists, count accurately, cross-reference all docs, handle edge cases (unimplemented stubs, overlapping counts, `+` notation).

## Related Skills

- `lumen-cognitive-workflows` — Advanced workflows
- `lumen-daily-workflows` — Core daily workflows
- `kanban-cognitive` — Task management (Agent Loop integrates)
- `lumen-server-development` — MCP server patterns (state persistence patterns)

## Implementation

- `objective_loop.py` — ~490 lines, imported by `server.py`
- Handlers registered in OBJECTIVE_HANDLERS dict + OBJECTIVE_SCHEMAS list
- Objective tools NOT in server.py's TOOLS list — they're registered separately via bridge plugin
- Bridge: 50 tools across ALL servers (filesystem 13 + web 2 + thinking 46 + pdb 15 = 76 total, but bridge only proxies a subset).
  - Thinking server TOOLS: 46 tools (chains, works, wiki, Q&A, patterns, decisions, model, state, sessions, cache)
  - Objective Loop SCHEMAS: 5 tools (create, judge, plan, status, checklist) — NOT included in server.py's 46
  - Total thinking ecosystem: 51 tools (46 + 5 objective)
- State persisted in `_objectives` dict + JSON + PDB snapshot (3 layers)
- Dashboard panel: implemented in dashboard.html (Agent Loop section). `/metrics` exposes `objectives` array with phase, score, tasks_done/total, criteria count.

## Real-World Case Study: Documentation Audit

This pattern was validated June 2026 to audit and correct all `.md` files in the `lumen-protocol` repo:

```text
1. objective_create("Auditar y corregir .md", desc, criteria=[6+ items])
2. objective_judge("goal_N") → BUILDING
3. objective_plan("goal_N") → 7 heuristic tasks from criteria
4. FOR each task:
   a. grep/read the target file for stale numbers (tool counts, server counts)
   b. Verify against actual source (bridge register_tool count, server.py TOOLS list)
   c. patch each file
5. objective_judge("goal_N", mark_done=true) → SCORE → TESTING
6. git add + git commit + git push
7. objective_judge("goal_N", mark_done=true) → DONE ✅
```

**Result**: 6 .md files corrected, 17 lines added, 39 insertions, all pushed in a single commit. Cycle: BUILDER → BUILDING (7 tasks executed) → TESTING → DONE. Score 10/10.

## User preference: high-confidence autonomous execution

Gonzalo explicitly prefers the Agent Loop to run **autonomously and with high confidence** — "usa agent loop y confianza alta". When he says "adelante" or "dale", execute immediately without asking for confirmation on intermediate steps.

Rules:
- Once the BUILDER phase produces score ≥ 8 and the user says "adelante", move to BUILDING and start implementing WITHOUT asking further permission
- Mark tasks done via `objective_judge(goal_id, mark_done=true)` to bulk-complete all tasks + verify criteria (since `objective_task_done` is registered but unimplemented — see Pitfalls). Don't batch-ask "which task next".
- If blocked, try one alternative before reporting failure—Gonzalo values resourcefulness
- Commit and push after each task completion, don't batch changes
- The kanban (task_create→task_move→task_link) must stay synced with objective progress
- At session end, offer to save any newly discovered workflow as a skill

This replaces the default "ask before each phase" behavior. Gonzalo is a technical user who wants results, not hand-holding.

## Real-World Case Study: Casity FASE 0

Validated June 2026 to implement a full-stack Python monitoring application (WiFi scanner + SQLite DB + FastAPI + AES vault + HTMX dashboard):

```text
1. objective_create("Implementar Casity FASE 0", "Backend completo...",
     criteria=[9 items: SQLite, scanner, API, vault, reports, dashboard, wiki, kanban, verification])
2. objective_judge("goal_N") → BUILDING (score 8/10)
3. objective_plan("goal_N") → 10 heuristic tasks from criteria
4. FOR each task:
   a. Write the module code (schema.py, scanner.py, vault.py, api.py)
   b. Test each module independently via python -c / CLI
   c. Fix bugs (unique constraint, port conflicts, DB paths)
   d. Deploy API as background process
5. objective_judge("goal_N", mark_done=true) → SCORE → TESTING (fallback: objective_task_done is unimplemented)
6. task_create → task_move(Done) → task_link(chain) → keep kanban synced
7. wiki_create × 2 → document architecture + API reference
8. objective_judge("goal_N", mark_done=true) → SCORE → TESTING
```

**Key observations from this real run:**

| Aspect | What happened |
|--------|---------------|
| Task granularity | 10 tasks from 9 criteria was right-sized. Added 1 verification task automatically. |
| Inline verification | Testing each module via `python -c` before API deploy caught bugs early (DB schema, unique constraints) |
| Kanban sync | `task_create` + `task_move(Done)` + `task_link(chain)` must happen in parallel to keep cognitive integrity >80 |
| Wiki timing | Create wiki pages only after code is verified, not during planning |
| Restart pitfall | API process must be killed+restarted after code changes. The old process serves stale code and produces confusing errors. |

**Result**: 5 modules implemented, 7 API endpoints working, dashboard live, wiki created. 6/7 kanban tasks Done, 1 pending (Android app). Cycle: BUILDER → BUILDING (6 tasks executed) → paused at user request before TESTING.
