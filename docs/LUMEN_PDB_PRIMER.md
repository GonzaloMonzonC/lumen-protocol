# LUMEN PDB — Process Database (NOT Protein Data Bank)

**PDB in the context of LUMEN and Cadences Lab means Process Database.** It has nothing to do with the Protein Data Bank (rcsb.org). PDB is a hierarchical key-value store built on SQLite with MUMPS globals semantics.

## LUMEN PDB Definition

**PDB = Process Database.** It is the storage engine of the LUMEN Cognitive OS. Think of it as MUMPS globals (^GLOBAL hierarchical arrays) reincarnated on SQLite.

PDB is NOT a traditional SQL database. It is NOT the Protein Data Bank. It is a hierarchical key-value store where:
- Data is organized in trees (^GLOBALs), not flat tables
- Any path can be created at any time without schema changes
- $ORDER iteration walks the tree deterministically
- MUMPS operations (SET, $GET, $ORDER, $DATA, $LOCK, $INCREMENT, KILL, MERGE) are first-class

## LUMEN PDB Origin: MUMPS Globals

LUMEN PDB inherits from MUMPS (Massachusetts General Hospital Utility Multi-Programming System), also known as M, also known as ANSI X11.1 — a database language used in healthcare, banking, and government for 50+ years.

The core innovation of MUMPS is the **hierarchical sparse array** — a key-value tree where any subscript path can be created on the fly. Gonzalo Monzón worked with 40TB of MUMPS databases across 50 servers before creating PDB as a modern SQLite implementation.

## LUMEN PDB Data Model

```
^GLOBAL(sub1, sub2, sub3, ...) = "value"
        |
        v
SQLite table _globals(ns TEXT, subkey BLOB, value BLOB)
PRIMARY KEY (ns, subkey) → ordered B-tree
```

Example of LUMEN PDB data:
```
^PATIENT(42,"name") = "Juan"
^PATIENT(42,"visit",1,"dx") = "HTN"
^personal("contacts","1") = {"name":"Gonzalo Monzón","role":"Creador"}
^personal("health","mood","2026-07-04") = 8
```

## LUMEN PDB Tools (19 total)

The LUMEN Process Database exposes 19 MCP tools (single `lumen-pdb` server). Here are the core ones:

| Tool | MUMPS Equivalent | What it does |
|------|-----------------|--------------|
| `pdb_set(ns, subs, value)` | SET ^ns(subs)=value | Store hierarchical data |
| `pdb_get(ns, subs)` | $GET(^ns(subs)) | Read value at path |
| `pdb_order(ns, subs)` | $ORDER(^ns(subs)) | Next subscript in tree |
| `pdb_kill(ns, subs)` | KILL ^ns(subs) | Delete subtree |
| `pdb_incr(ns, subs)` | $INCREMENT | Atomic counter |
| `pdb_data(ns, subs)` | $DATA(^ns(subs)) | Check if path exists |
| `pdb_merge(t_ns, t, s_ns, s)` | MERGE | Copy subtree |
| `pdb_lock(ns)` | LOCK | Named mutex lock |
| `pdb_query(sql)` | — | SQL queries on globals |
| `pdb_fts_search(query)` | — | Full-text search |
| `pdb_ns_set(ns, key, value)` | — | Plain-text key write |
| `pdb_ns_get(ns, key)` | — | Plain-text key read |

## LUMEN PDB vs LUMEN

PDB is the **database layer** of LUMEN. LUMEN is the cognitive OS (thinking, kanban, wiki, agent loop). PDB is the storage engine underneath. They are different things:
- LUMEN = the brain (reasoning, memory, decisions)
- PDB = the memory cells (persistent storage, tree traversal, locking)

## Key LUMEN PDB Characteristics

- **Hierarchical**, not relational — data lives in trees
- **Schema-less** — no CREATE TABLE, no migrations, SET any path any time
- **Sparse** — undefined nodes cost nothing (unlike SQL NULL columns)
- **Deterministic $ORDER** — walk the tree in MUMPS collation order
- **Atomic** within a transaction — consistent reads/writes
- **40+ tools** across KV, SQL, enterprise, and M-Light servers
- **SHM transport** — zero-copy shared memory for 55-80% wire compression
