# LUMEN Cognitive OS — Design Concept (June 2026)

## Vision

Transform LUMEN from a cognitive toolkit into a **Cognitive Operating System**
where multiple Hermes agents coordinate as "cognitive processes" sharing a
common knowledge model, with the user controlling everything via a dashboard.

## Three Pillars

### 1. Wiki Mental Bidireccional

A dashboard where the user creates/edits/deletes entities in the mental model,
and those changes modify the agent's cognition in real time.

**Architecture**:
```
Usuario (dashboard HTML)
  │
  ├─ GET  /model?entity=X      → model_query("deps of X")
  ├─ POST /model               → model_add(entity, deps, role, notes, properties)
  ├─ DELETE /model?entity=X    → model_remove(entity)
  │
  ▼
Thinking Server (memoria compartida)
  │
  ├─ Agente Hermes lee modelo al iniciar → model_query("all")
  ├─ Agente Hermes usa modelo para decisiones
  └─ Cambios del usuario visibles instantáneamente (mismo dict en memoria)
```

**What exists today**: `model_add`, `model_query`, `model_map`, `model_remove`,
`model_stats`, `model_scan` — all functional. Missing: HTTP REST endpoints,
dashboard CRUD forms, `properties` dict libre en `model_add`.

**Effort**: ~150 lines. HTTP CRUD endpoints (~60 loc) + Alpine.js forms (~80 loc)
+ extend `model_add` for arbitrary `properties` (~10 loc).

### 2. Cross-Session Super-Cognition

Multiple Hermes sessions aware of each other, detecting repo collisions,
communicating via shared inbox.

**Architecture**:
```
Sesión A (Hermes)                Sesión B (Hermes)
  │                                │
  ├─ session_list() → ve que B     ├─ session_list() → ve que A
  │   está trabajando en repo X     │   está trabajando en repo X
  │                                │
  ├─ model_add("repo-file-1",      ├─ model_add("repo-file-1",
  │   deps=["session-A"])           │   deps=["session-B"])
  │                                │
  ├─ model_query("dependents       ├─ model_query("dependents
  │   of repo-file-1")              │   of repo-file-1")
  │   → ⚠️ session-B también!       │   → ⚠️ session-A también!
  │                                │
  ├─ agent_message("session-B",    ├─ agent_inbox()
  │   "¿Coordinamos merge?")        │   → "session-A: ¿Coordinamos merge?"
  │                                │
  └─ [Se coordinan vía mensajes]   └─ [Responden y sincronizan]
```

**What exists today**: `session_list`, `session_init`, `model_query` (for
collision detection via shared deps), `context_preserve`/`check` (for
cross-session anchoring). Missing: `agent_message`/`agent_inbox` tools,
collision detection logic, timeline dashboard.

**Effort**: ~250 lines. New tools (~60 loc) + collision detection (~20 loc) +
timeline dashboard (~60 loc) + activity feed (~50 loc).

### 3. Unified Dashboard — "Cognitive Desktop"

Single HTML dashboard showing all cognitive OS state:
- Wiki editor (CRUD entities, properties, relationships)
- Session monitor (all active agents, their tasks, files touched)
- Collision detector (shared deps between sessions)
- Timeline feed (all agent activity, interleaved)
- Inbox (inter-agent messages)

## Roadmap

| Phase | What | Effort | Value |
|-------|------|--------|-------|
| **A — Wiki Mental** | HTTP CRUD + forms + properties libres | ~150 loc, ~2h | User edits agent knowledge without prompts |
| **B — Cross-Session** | agent_message/inbox + collision + timeline | ~250 loc, ~4h | Coordinated agents, zero repo conflicts |
| **C — Cognitive OS** | Unified dashboard, auto-negotiation, pattern learning | ~300 loc, ~5h | Full multi-agent cognitive platform |

## Technical Foundation

All three pillars rest on the thinking server's shared-memory architecture:
- Single Python process with `_sessions` dict in memory
- All agents read/write the same objects (model, patterns, assumptions, decisions)
- State persists to `.thinking_state.json` every 10 tool calls
- Dashboard reads state via HTTP endpoints (dashboard runs on daemon thread)

## Key Design Decisions

1. **Shared memory, not message passing**: Agents don't IPC — they read/write
   the same Python objects. Simpler, faster, zero serialization overhead.
2. **Dashboard IS the control plane**: No separate admin tool. The dashboard
   is both monitor and editor.
3. **Incremental from existing tools**: Every new feature builds on existing
   LUMEN tools (model_add, session_list, context_preserve, etc.).
4. **Properties as free-form JSON**: `model_add` entities should accept
   arbitrary `properties` dict — this lets the wiki store any structured data
   without schema migrations.
