# PDBM-Lumen

**Process Database MUMPS-style** — Hierarchical key-value store on SQLite, with MUMPS globals semantics and LUMEN MCP transport. **20 tools.**

## What it is

PDBM-Lumen is a database for AI agents. Think of it as **MUMPS globals reincarnated on SQLite with SHM zero-copy transport**.

```
^PATIENT(42,"name") = "Juan"
^PATIENT(42,"visit",1,"dx") = "HTN"
^IDX_APELLIDO("Caballero","Garcia","Juan") = 42
```

## Why not SQL?

- **No schema.** SET any path any time. No CREATE TABLE, no ALTER TABLE, no migrations.
- **Natural hierarchy.** Trees map directly to agent data (patient → visits → diagnoses).
- **$ORDER iteration.** Walk the tree level by level, same as MUMPS.
- **SQL when you need it.** Use pdb_query for aggregations and analytics.

## Tools

### KV tools (daily work)

| Tool | MUMPS | Description |
|------|-------|-------------|
| `pdb_set(ns, subs, value)` | `SET ^ns(subs)=value` | Store a value |
| `pdb_get(ns, subs, default?)` | `$GET(^ns(subs))` | Read a value |
| `pdb_order(ns, subs, dir?)` | `$ORDER(^ns(subs),dir)` | Next/prev subscript |
| `pdb_data(ns, subs)` | `$DATA(^ns(subs))` | Check existence (0/1/10/11) |
| `pdb_kill(ns, subs)` | `KILL ^ns(subs)` | Delete subtree |
| `pdb_incr(ns, subs, inc?)` | `$INCREMENT(^ns(subs),inc)` | Atomic increment |
| `pdb_merge(t_ns, t_subs, s_ns, s_subs)` | `MERGE ^t(t_s)=^s(s_s)` | Copy subtree |
| `pdb_lock(ns, subs, timeout?)` | `LOCK ^ns(subs)` | Acquire resource lock |
| `pdb_unlock(ns, subs?)` | `LOCK` (no args) | Release resource lock |

### SQL tools (analysis)

| Tool | Description |
|------|-------------|
| `pdb_query(sql, params?)` | Execute SELECT/WITH queries |
| `pdb_schema()` | List namespaces, node counts, DB size |
| `pdb_backup(path?)` | Backup DB or show stats |

### FASE 1 — LLM productivity tools

| Tool | Description |
|------|-------------|
| `pdb_batch_set(items)` | Atomic bulk insert (N records, 1 transaction) |
| `pdb_scratch_set(key, value)` | LLM working memory — survives compressions |
| `pdb_scratch_get(key)` | Read scratchpad value |
| `pdb_scratch_del(key)` | Delete scratchpad key |
| `pdb_fts_search(query, limit?, ns?)` | Full-text search across all stored values (FTS5) |

### Auto-Indices — ^IDX automáticos al SETear

| Tool | Description |
|------|-------------|
| `pdb_index_define(ns, idx_name, sub_pos?)` | Define auto-index: cada SET a `^ns(..., valor, ...)` crea `^_IDX_ns_idxname(valor, ...)` |
| `pdb_index_list()` | List all defined auto-indices |
| `pdb_index_drop(ns, idx_name)` | Remove index definition and all its stored data |

Los índices se actualizan automáticamente:
- **SET** → crea/actualiza entrada en `^_IDX_{ns}_{name}(valor_indexado, subscripts_originales...)`
- **KILL** → limpia todas las entradas hijas del path eliminado
- **Batch** → mismo comportamiento que SET

### Resource Locks — $LOCK

| Tool | MUMPS | Description |
|------|-------|-------------|
| `pdb_lock(ns, subs, timeout?)` | `LOCK ^ns(subs)` | Acquire a resource lock. Blocks other sessions. |
| `pdb_unlock(ns, subs?)` / `pdb_unlock(all=true)` | `LOCK` (no args) | Release specific lock or all held locks. |

**20 tools total** via the PDB server.

## Quick start

```bash
# Via Hermes plugin (recommended — integrated into lumen-shm-bridge)
# Enable in config.yaml:
plugins:
  enabled:
    - lumen-shm-bridge

# Then /reset or restart. 15 PDB tools appear alongside 44 other LUMEN tools.

# Standalone server (for testing or custom integration):
python server.py
```

## Patterns for agents

```python
# Simple K/V config
pdb_set("CONFIG", ["theme"], "dark")
theme = pdb_get("CONFIG", ["theme"])

# Record with fields
pdb_set("PATIENT", [42, "name"], "Juan")
pdb_set("PATIENT", [42, "age"], 35)

# Index (inverse lookup)
pdb_set("IDX_EMAIL", ["juan@x.com"], 42)

# Atomic counter
next_id = pdb_incr("SEQ", ["patient_id"], 1)

# Iterate with $ORDER
a1 = "Caballero"
a2 = ""
while True:
    a2 = pdb_order("PATIENT_I2", [a1, a2 or ""], 1)
    if not a2: break
    n = ""
    while True:
        n = pdb_order("PATIENT_I2", [a1, a2, n or ""], 1)
        if not n: break
        pid = pdb_get("PATIENT_I2", [a1, a2, n])
        data = pdb_get("PATIENT", [pid])

# SQL analytics
pdb_query("SELECT ns, count(*) as nodes FROM _globals GROUP BY ns ORDER BY nodes DESC")
```

## Design

- **Single SQLite file** (default: `lumen-pdb.db`, override with `PDB_PATH` env var)
- **WAL mode** — concurrent reads, crash-safe writes
- **Level encoding** — type-prefixed, collation-correct byte sequences
- **Transport: stdio JSON-RPC** — PDB uses `server.py` over stdio. SHM (Level 2 zero-copy) is available via `server_shm.py` but **not recommended**: SHM adds ~700μs overhead per call, while SQLite operations take 15-96μs. For μs-scale KV ops, stdio is 20× faster.

## License

MIT
