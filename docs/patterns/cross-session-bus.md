# Cross-Session Communication Bus

**Status:** ✅ Verified  
**Date:** 2026-07-16  
**Tags:** `pdb`, `cross-session`, `multi-agent`, `bus`, `communication`

## Abstract

PDB (Process Database) provides a **shared SQLite store** accessible from every Hermes Agent session — Telegram, CLI, Gateway, or any MCP client connected to the same PDB server. This creates a natural cross-session communication bus with zero additional infrastructure.

Any session can write a value into a `^GLOBAL` namespace, and any other session can read it. This is the MUMPS equivalent of a shared memory bus, built on SQLite.

## Pattern

```
┌──────────────┐     ┌──────────┐     ┌──────────────┐
│ Session A    │     │   PDB    │     │ Session B    │
│ (Telegram)   │     │ (SQLite) │     │ (CLI)        │
└──────┬───────┘     └────┬─────┘     └──────┬───────┘
       │   pdb_set(pending)│                  │
       ├──────────────────►│                  │
       │                   │   pdb_get(pending)│
       │                   │◄─────────────────┤
       │                   │   pdb_set(done)  │
       │                   ├──────────────────►│
       │   pdb_get(done)   │                  │
       │◄──────────────────┤                  │
       │                   │                  │
```

## API (PDB tools)

| Tool | Purpose | Example |
|------|---------|---------|
| `pdb_set` | Write value with MUMPS subscripts | `pdb_set(ns="cross-session", subs=["pending","id-1"], value=...)` |
| `pdb_ns_set` | Write with plain-text key | `pdb_ns_set(ns="cross-session", key="pending:id-1", value=...)` |
| `pdb_get` / `pdb_ns_get` | Read value | `pdb_get(ns="cross-session", subs=["done","id-1"])` |
| `pdb_order` / `pdb_ns_order` | List keys | `pdb_order(ns="cross-session", subs=["pending"])` |
| `pdb_data` | Check existence | `pdb_data(ns="cross-session", subs=["pending","id-1"])` |
| `pdb_lock` / `pdb_unlock` | Mutex for concurrent writes | `pdb_lock(ns="cross-session")` |

## Recommended namespace convention

```
^cross-session("pending", "<task-id>")       → queued tasks
^cross-session("in-progress", "<task-id>")    → claimed/running tasks
^cross-session("done", "<task-id>")           → completed tasks
^cross-session("error", "<task-id>")          → failed tasks
```

## Verification (real test, 2026-07-16)

1. **Session A (Telegram)** wrote a task into `^cross-session("pending","test-1")` with status `"pending"`
2. **Session B (CLI)** read the task from pending, processed it, and wrote the result into `^cross-session("done","test-1")` with status `"done"`
3. **Session A (Telegram)** read the done node and confirmed the result

**Result:** Cross-session communication via PDB confirmed working.

## Advantages

- **Zero infrastructure** — shared SQLite, no message broker
- **Deterministic** — MUMPS `$ORDER`, `$GET`, `$DATA` semantics
- **Persistent** — data survives session restarts
- **Cost** — $0, local only
- **LUMEN compatible** — patterns, decisions, Q&A all share the same PDB

## Limitations

- No push notifications (consumer must poll)
- No automatic locks for concurrent writes (use `pdb_lock`)
- No guaranteed FIFO ordering (use `$ORDER` for traversal)
- No built-in TTL (can be added via `pdb_trigger` or application logic)

## See also

- [PDB Primer](PDB_PRIMER.md)
- [LUMEN Cognitive OS](COGNITIVE_OS.md)
- [PAPER.md](../PAPER.md)
