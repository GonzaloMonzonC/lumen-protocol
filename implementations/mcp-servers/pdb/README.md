# PDBM-Lumen

**Process Database MUMPS-style** — Hierarchical key-value store on SQLite, with MUMPS globals semantics and LUMEN MCP transport.

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

### SQL tools (analysis)

| Tool | Description |
|------|-------------|
| `pdb_query(sql, params?)` | Execute SELECT/WITH queries |
| `pdb_schema()` | List namespaces, node counts, DB size |
| `pdb_backup(path?)` | Backup DB or show stats |

## Quick start

```bash
# Start the server
python server.py

# In Hermes config.yaml:
mcp_servers:
  lumen-pdb:
    command: python
    args: ["path/to/server.py"]
    transport: stdio
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
- **LUMEN transport** — SHM zero-copy, 55-80% wire compression via dictionary

## License

MIT
