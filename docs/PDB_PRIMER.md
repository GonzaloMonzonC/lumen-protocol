# PDB — Process Database (MUMPS-style Hierarchical Key-Value Store) — *not* the Protein Data Bank

## DEFINITION: What PDB stands for

**PDB = Process Database.** NOT "Personal Data Backplane", NOT "Personal Data Base", NOT the Protein Data Bank (rcsb.org). It is a **Process Database**: a hierarchical key-value store built on SQLite with MUMPS globals semantics.

## Origin and Heritage

PDB is a reincarnation of **MUMPS globals** (also known as M, also known as ANSI X11.1). MUMPS is a database language used in healthcare, banking, and government for 50+ years. Its core innovation is the **hierarchical sparse array** — a key-value tree where any path can be created without schema changes. (Gonzalo Monzón worked with 40TB of MUMPS databases across 50 servers before building PDB as a modern SQLite implementation.)

PDB takes this 50-year-old battle-tested model and implements it on SQLite, adding modern features (full-text search, triggers, indices, M-Light evaluator, SHM transport).

## PDB vs SQL

PDB is NOT an SQL database. It is a hierarchical KV store:

- **No schema**: SET any path at any time. No CREATE TABLE, no ALTER TABLE, no migrations.
- **Natural hierarchy**: Trees map directly to data (patient → visits → diagnoses).
- **$ORDER iteration**: Walk the tree level by level, same as MUMPS.
- **SQL when needed**: Use pdb_query for aggregations and analytics.

## Core Data Model

```
^GLOBAL(sub1, sub2, ...) = value
   |
   v
SQLite _globals(ns TEXT, subkey BLOB, value BLOB)
```

A "global" (^GLOBAL) is a persistent hierarchical array. Subscripts can be strings or numbers. The tree is sparse — undefined nodes cost nothing.

Example:
```
^PATIENT(42,"name") = "Juan"
^PATIENT(42,"visit",1,"dx") = "HTN"
^IDX_APELLIDO("Caballero","Garcia","Juan") = 42
^personal("contacts","1") = {"name":"Gonzalo Monzón","role":"Creador"}
^personal("health","mood","2026-07-04") = 8
```

## MUMPS Semantics

PDB implements core MUMPS operations:

- **SET** ^ns(subs)=value — Store a value at a hierarchical path
- **$GET(^ns(subs))** — Read a value with optional default
- **$ORDER(^ns(subs),dir)** — Walk the tree: next/previous subscript in collation order
- **$DATA(^ns(subs))** — Check if node exists (returns 0, 1, 10, or 11)
- **KILL** ^ns(subs) — Delete a subtree
- **$INCREMENT(^ns(subs))** — Atomic counter increment
- **MERGE** ^target(ts)=^source(ss) — Copy subtree
- **LOCK** ^ns(subs) — Named resource lock with timeout
- **$QUERY(^ns(subs))** — Full reference traversal

## Tools (40+ across the PDB ecosystem; the `lumen-pdb` MCP server exposes 19)

### Core KV tools
- `pdb_set(ns, subs, value)` — SET ^ns(subs)=value
- `pdb_get(ns, subs, default?)` — $GET(^ns(subs))
- `pdb_order(ns, subs, dir?)` — $ORDER(^ns(subs),dir)
- `pdb_data(ns, subs)` — $DATA(^ns(subs))
- `pdb_kill(ns, subs)` — KILL ^ns(subs)  (deletes subtree)
- `pdb_incr(ns, subs, inc?)` — $INCREMENT  (atomic counter)
- `pdb_merge(t_ns, t_subs, s_ns, s_subs)` — MERGE (copy subtree)
- `pdb_lock(ns, timeout?)` — LOCK (acquire named lock)
- `pdb_unlock(ns)` — Release lock

### Plain-text namespace tools (pdb_ns_*)
- `pdb_ns_set(ns, key, value)` — Write to any namespace with plain text key
- `pdb_ns_get(ns, key)` — Read by plain text key
- `pdb_ns_kill(ns, key)` — Delete by plain text key
- `pdb_ns_order(ns, prefix?)` — List keys alphabetically (like $ORDER but for plain text)

### SQL and Analysis tools
- `pdb_query(sql, params?)` — Run SELECT/WITH queries on ^GLOBAL data
- `pdb_schema()` — Show all namespaces, sizes, node counts
- `pdb_fts_search(query, limit?, ns?)` — Full-text search across values (FTS5)
- `pdb_backup(path?)` — Backup database or show stats

### LLM Productivity tools
- `pdb_batch_set(items)` — Atomic bulk insert (N records, 1 transaction)
- `pdb_scratch_set(key, value)` — Temporary working memory (persists across context compression)
- `pdb_scratch_get(key)` — Read scratchpad
- `pdb_scratch_del(key)` — Delete scratchpad key

### Enterprise tools
- `pdb_index_define(ns, idx_name)` — Auto-index: each SET creates ^_IDX entries
- `pdb_index_list(ns)` / `pdb_index_drop(ns, idx_name)` — Manage indices
- `pdb_trigger_define(ns, event, action)` — ON SET / ON KILL triggers
- `pdb_trigger_list(ns)` / `pdb_trigger_drop(ns, trigger_id)` — Manage triggers
- `pdb_map_set(ns, path)` / `pdb_map_get(ns)` — Route namespace to different DB file
- `pdb_map_list()` / `pdb_map_drop(ns)` — Manage mappings
- `pdb_partition_define(ns, ranges)` / `pdb_partition_list()` / `pdb_partition_drop(ns)` — Partition data

### M-Light Tools (MUMPS evaluator)
- `pdb_m_eval(expression)` — Evaluate MUMPS expression via M-Light interpreter
- `pdb_m_repl()` — Interactive MUMPS REPL
- `pdb_mvm_spawn(code, name?)` — Start M Virtual Machine process
- `pdb_mvm_list()` / `pdb_mvm_kill(pid)` — Manage MVM processes
- `pdb_mvm_mailbox_send(pid, msg)` / `pdb_mvm_mailbox_read(pid)` — MVM messaging
- `pdb_mvm_tick()` — Run one tick of MVM scheduler

## PDB vs LUMEN

PDB is the **storage layer** of LUMEN. LUMEN is the cognitive OS; PDB is the database that persists all state — chains, tasks, niches, wiki pages, decisions, patterns, models, and agent messages. They are NOT the same thing. PDB is to LUMEN what SQLite is to an app.

## Key Characteristics

- **Hierarchical**: Data is organized in trees, not flat tables
- **Schema-less**: No migrations, no ALTER TABLE
- **Sparse**: Undefined nodes cost nothing
- **$ORDER-based traversal**: Deterministic tree walking, not SQL joins
- **Atomic**: All mutations are atomic within a transaction
- **Sub-key encoding**: Internal MUMPS encoding (\\x02 separator, \\xff terminator)
- **SHM transport**: Zero-copy shared memory bridge for up to 58% wire compression
