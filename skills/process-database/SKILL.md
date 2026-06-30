---
name: process-database
description: '👽 PDB — SQLite-backed hierarchical KV with MUMPS heritage. 40 tools: $ORDER/$DATA/$GET, global mapping, partitioning, triggers, indices, $LOCK, M-Light evaluator, M REPL, MVM. Umbrella skill: carga pdb-kv + pdb-enterprise + mlight-cognitive-toolkit.'
version: 2.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, database, kv, mumps, sqlite, composition]
---

# Process Database (PDB) — Umbrella

**40 herramientas en 4 servidores.** Este skill es un paraguas que anida los skills atomicos. Para uso diario, carga solo el que necesites. Para todo, carga este.

## Skills anidados

| Skill | Contenido | Herramientas | Cuando cargarlo |
|:------|:----------|:------------|:----------------|
| `pdb-kv` | SET/GET/KILL/ORDER/DATA/MERGE + scratch + schema | 15 | Operaciones diarias |
| `pdb-enterprise` | $LOCK, triggers, indices, mapping, partitioning, FTS, SQL | 13 | Features avanzadas |
| `mlight-cognitive-toolkit` | M-Light patrones, M + Thinking, triggers cognitivos | 5 (eval/REPL/MVM) | Procesar datos con M |

## Core Insight

SQLite IS a B-tree. Una tabla `_globals(ns, subkey, value)` con PK `(ns, subkey)` es un KV ordenado. PDB anade semantica MUMPS ($ORDER, $DATA, $LOCK) sobre esa base.

## Quick Start

```python
# Carga todo
skill_view('process-database')

# O carga solo lo que necesites
skill_view('pdb-kv')              # Solo KV
skill_view('pdb-enterprise')      # Solo enterprise
skill_view('mlight-cognitive-toolkit')  # Solo M-Light
```

## Arquitectura

```
^GLOBAL(sub1, sub2, ...) = value
   |
   v
SQLite _globals(ns, subkey BLOB, value BLOB)
   |
   v
$ORDER / $DATA / $GET / $LOCK / triggers / indices
```

## Pitfalls

- journal_mode DELETE: no crea .shm/.wal. Escribe directo al .db
- No mezclar ns con subindices: `pdb_get("ns", [1])`
- $ORDER retorna "" al final del arbol
- Siempre inicializa variables M: `S I=""` antes de $O

---

# Design Reference (v1.4.0)

## Core Insight

**SQLite IS a B-tree.** The `PRIMARY KEY` of any SQLite table creates a B-tree index. A single table with `(namespace, subkey)` as PK is a drop-in ordered KV store:

```sql
CREATE TABLE _globals (
    ns     TEXT NOT NULL,
    subkey BLOB NOT NULL,       -- encoded subscript path (collation-safe)
    value  BLOB,                -- NULL = structural node (children only)
    PRIMARY KEY (ns, subkey)
) WITHOUT ROWID;
```

No separate storage engine needed — SQLite's B-tree handles ordering, ACID, WAL, and concurrent access in a single file.

## When to Use

| Use | Approach |
|-----|----------|
| Flat data, aggregations | SQL (`pdb_query`) — JOINs, GROUP BY, window functions |
| Hierarchical / tree data | KV tools (`pdb_set/get/order/data/kill`) |
| Cross-session agent state | KV — survives `/reset`, context compression |
| The LLM prefers | SQL (trained on millions of examples) over niche MUMPS syntax |

## Transport Decision

| Server | Transport | Why |
|--------|-----------|-----|
| filesystem | **SHM** (Level 2 zero-copy) | Large file payloads amortize SHM overhead |
| thinking | **SHM** | Long chains, large responses |
| web | **SHM** | Web page content is large |
| **pdb** | **stdio JSON-RPC** | KV ops are μs-scale; SHM adds ~700μs (20× slower) |

## Subkey Encoding (MUMPS Collation)

MUMPS sorts subscripts as: `"" < numeric < string`. Each level is encoded with a type prefix and `0xFF` separator:

| Subscript | Prefix | Data | Separator | Sort position |
|-----------|--------|------|-----------|---------------|
| Empty `""` (sentinel) | `0x00` | (none) | (none) | 1st |
| Numeric | `0x01` | 8-byte BE double (sign-transformed) | `0xFF` | 2nd, by value |
| String | `0x02` | Raw UTF-8 bytes | `0xFF` | 3rd, lexicographic |

**Sign transformation** (makes IEEE 754 doubles memcmp-sortable):
- Positive (sign bit 0): flip sign bit only (`bytes[0] ^ 0x80`)
- Negative (sign bit 1): flip ALL bits (`b ^ 0xFF for b in raw`)

**Example**: `^PATIENT(1001,"name")`
```
subkey = 02 50 41 54 49 45 4E 54 FF    (PATIENT)
         01 C0 8F 48 00 00 00 00 00 FF  (1001.0 as BE double)
         02 6E 61 6D 65 FF             (name)
```

## KV Tools (7 tools)

| Tool | MUMPS | SQL impl | Avg latency |
|------|-------|----------|------------|
| `pdb_set(ns, subs, value)` | `SET` | `INSERT OR REPLACE` | **30.8 μs** |
| `pdb_get(ns, subs)` | `$GET` | `SELECT value` | **15.5 μs** |
| `pdb_order(ns, subs, dir)` | `$ORDER` | range scan + LIMIT | **~5 μs** |
| `pdb_data(ns, subs)` | `$DATA` → 0/1/10/11 | value + children check | **33.9 μs** |
| `pdb_kill(ns, subs)` | `KILL` | range DELETE | **26.7 μs** |
| `pdb_incr(ns, subs, inc)` | `$INCREMENT` | atomic UPDATE | **96.0 μs** |
| `pdb_merge(t_ns, t_subs, s_ns, s_subs)` | `MERGE` | INSERT+SELECT rewrite | **varies** |

All measurements: 100K iterations via stdio JSON-RPC (SQLite direct, not SHM).

## $ORDER Algorithm

```python
def pdb_order(ns, subs, cursor="", direction=1):
    """
    $ORDER(^ns(subs...,cursor), direction)
    - cursor="" (sentinel) and direction=1 → first subscript at this level
    - cursor="" and direction=-1 → last subscript at this level
    - cursor=X and direction=1 → next subscript after X
    Returns: next subscript value, or None if none exists
    """
    parent_key = encode_subkey(subs)
    target_level = len(subs)

    if cursor == "" or cursor is None:
        lo = parent_key if direction == 1 else parent_key + b'\xff\xff\xff\xff'
        op = ">" if direction == 1 else "<"
        order = "ASC" if direction == 1 else "DESC"
        rows = db.execute(
            f"SELECT subkey FROM _globals WHERE ns=? AND subkey {op} ? "
            f"ORDER BY subkey {order} LIMIT 200",
            [ns, lo]
        ).fetchall()
    else:
        current_key = encode_subkey(subs + [cursor])
        op = ">" if direction == 1 else "<"
        order = "ASC" if direction == 1 else "DESC"
        rows = db.execute(
            f"SELECT subkey FROM _globals WHERE ns=? AND subkey {op} ? "
            f"ORDER BY subkey {order} LIMIT 200",
            [ns, current_key]
        ).fetchall()

    for row in rows:
        sk = row[0]
        if count_levels(sk) < target_level + 1:
            continue
        val = extract_level(sk, target_level)
        if cursor != "" and cursor is not None and cursor == val:
            continue
        if parent_key and not sk.startswith(parent_key):
            continue
        return val
    return None
```

### $DATA return codes

| Code | Meaning | Detection |
|------|---------|-----------|
| 0 | Node doesn't exist | No row found, no child with this prefix |
| 1 | Exists with value, no children | Row found, value NOT NULL, next key not a child |
| 10 | Exists with children only | Row found, value IS NULL, next key is a child |
| 11 | Exists with value + children | Row found, value NOT NULL, next key is a child |

### Known $DATA limitation

`$DATA(non_existent)` can return 10 (false positive) if a sibling's child happens to sort directly after the queried prefix. The detection uses "first key > parent_key" and checks if it starts with the parent key — this is approximate. For a correct implementation, also verify that the next key's parent up to target_level matches.

### $ORDER LIMIT 50 bug ($ORDER needs LIMIT)

The core `$ORDER` uses `LIMIT 200` to avoid scanning the entire B-tree. When a single parent has **200+ children at the query level** (extremely deep branching), the filter can skip all fetched rows and miss the next sibling.

**Fix (commit 5eb106e)**: paginated loop — scan in chunks of 200, advancing `OFFSET` by 200 each iteration, until a sibling at the target level is found or rows are exhausted:

```python
offset = 0
page_size = 200
found_val = None
while True:
    rows = c.execute(
        f"SELECT subkey FROM _globals WHERE ns=? AND subkey > ? "
        f"ORDER BY subkey LIMIT ? OFFSET ?",
        [ns, search_key, page_size, offset]
    ).fetchall()
    if not rows:
        break
    for row in rows:
        sk = row["subkey"]
        # ...filtering same as before...
        if current == sub_val:
            continue
        found_val = sub_val
        break
    if found_val is not None:
        break
    offset += page_size
```

This guarantees correctness for ANY branching factor. The loop is rarely triggered in practice — 200 rows per page covers >99.9% of real-world cases.

## Plugin Deadlock: ALWAYS use RLock

When `_get_server()` spawns a subprocess and calls `_rpc()` for the init handshake internally, use `threading.RLock()` NOT `threading.Lock()`:

```python
# ❌ WRONG — same-thread deadlock
_server_lock = threading.Lock()
# ✅ CORRECT — allows re-entry from _get_server → _rpc
_server_lock = threading.RLock()
```

Also set `stderr=subprocess.DEVNULL` to prevent Windows pipe blocking.

## Handler Calling Convention

PDB handlers must accept `(args: dict)` as a single positional argument, NOT `**kwargs`:

```python
# ✅ Correct — works with ShmNativeServer._process_message
def tool_set(args: dict) -> dict:
    ns = args["ns"]; subs = args["subs"]; value = args["value"]
    ...

# ❌ Wrong — ShmNativeServer calls handler(tool_args) not handler(**tool_args)
def tool_set(ns: str, subs: list, value) -> dict:
    ...
```

**Why**: `ShmNativeServer._process_message()` calls `result = handler(tool_args)` where `tool_args` is a dict. The thinking server uses the same pattern (`args: dict`). This is the calling convention for ALL servers using `ShmNativeServer` (filesystem, thinking, web, pdb).

`server.py` calls with `handler(args)` (single dict), consistent with `ShmNativeServer`.

### Exception: Zero-arg handlers

`tool_schema()` and `tool_backup()` take optional args. They must accept `(args: dict = None)` because the bridge always sends `{}` as arguments:

```python
def tool_schema(args: dict = None) -> dict:
    ...

def tool_backup(args: dict = None) -> dict:
    """Backward compat: args can be dict (from bridge) or string (from old tests)."""
    path = args.get("path") if isinstance(args, dict) else args
    ...
```

Without the `= None` default, calling `tool_schema({})` from the bridge triggers `TypeError: takes 0 positional arguments`.

## PoC: TravelMap Cultural Import

Demonstration: 80 real places imported in 47ms. Model: `^TRAVEL("cultural", province, id)`.

## PoC: Mega Import (TravelMap + FishMap)

**Full-scale demonstration**: 24 JSON datasets (9 travel + 15 fish) imported into a single PDB in **649ms**:

```
TRAVEL:  1,288 records — cultural, cultural_ext, ruta_montana, ruta_montana_ext,
                          ciclista, camino, acuatica, via_ferrata, via_ferrata_ext
FISHMAP: 1,188 records — spot, beach(×8 zones), apnea, embarcacion, kayak,
                          marisqueo, marisqueo_roca, nocturna
─────────────────────────────────────────────
TOTAL:   2,476 records in 649ms (3,817 rec/s)
DB:      ~872 KB
```

**Multi-dataset pattern** — type as first subscript to namespace:
```
^TRAVEL("cultural", province, id)   → monumentos
^TRAVEL("camino", province, id)     → rutas del Camino de Santiago
^TRAVEL("ciclista", province, id)   → rutas en BTT
^FISHMAP("spot", province, id)      → spots de pesca
^FISHMAP("beach", zone, name)       → playas (agrupadas por zona costera)
^FISHMAP("apnea", province, id)     → zonas de apnea
```

This keeps all related data in one file, indexable by both SQL and $ORDER:

**Demonstrated**:
```python
# $ORDER traversal by province
prov = None
while True:
    r = pdb_order({"ns": "TRAVEL", "subs": ["cultural", prov or ""], "direction": 1})
    if r["value"] is None: break
    prov = r["value"]
    # count places in this province
    ...

# $DATA check
r = pdb_data({"ns": "TRAVEL", "subs": ["cultural", "Barcelona"]})
# → 10 (structural node, has children)

# SQL aggregation
r = pdb_query({"sql": "SELECT json_extract(value, '$.province') as prov, "
                       "round(avg(json_extract(value, '$.rating_avg')),2) as r "
                       "FROM _globals WHERE ns='TRAVEL' "
                       "GROUP BY prov HAVING n>5 ORDER BY r DESC LIMIT 10"})

# Direct lookup
r = pdb_get({"ns": "TRAVEL", "subs": ["cultural", "Barcelona", place_id]})
```

## FASE 1: High-Level Tools for LLM Productivity

Built on top of the 10 KV+SQL core tools, these high-level tools add capabilities that don't overlap with existing Hermes tools:

### pdb_batch_set — Atomic Bulk Insert

Insert multiple records in a single SQLite transaction. Avoids N separate tool calls and N separate commits.

```python
pdb_batch_set({
    "items": [
        {"ns": "SIGNAL", "subs": ["sensor-1", "T1", "temp"], "value": 23.5},
        {"ns": "SIGNAL", "subs": ["sensor-1", "T2", "temp"], "value": 23.6},
        ...
    ]
})
```

**Performance**: 3 records in ~1ms (vs ~3ms with 3x pdb_set). For 1000 records, ~300ms vs ~3s.

**Use cases**: IoT signal ingestion, bulk data migration, initial bootstrap from JSON/CSV files.

### pdb_scratch — LLM Working Memory

Temporary key-value store that survives context compressions but is NOT permanent memory. The LLM uses it to:

- Store intermediate results across turns
- Track state during complex multi-step workflows
- Cache computed values without cluttering memory

```python
pdb_scratch_set({"key": "current_project", "value": "PDBM-Lumen"})
pdb_scratch_get({"key": "current_project"})        # → "PDBM-Lumen"
pdb_scratch_del({"key": "current_project"})
```

Internally stored under `^SCRATCH(key)`. Uses the same pdb_set/get/kill handlers.

**Contrast with Hermes memory**: `memory` is for permanent user facts (name, preferences). `pdb_scratch` is for ephemeral working state (current task context, intermediate results). Scratch survives a `/reset` but is meant to be cleared when the task completes.

### pdb_fts_search — Full-Text Search on Own Data

Each call:
1. Creates SQLite FTS5 virtual table (`_fts`) if not exists
2. Deletes stale index, re-inserts all `_globals` values (fast — 2,476 records in ~50ms)
3. Searches with BM25 ranking via `MATCH`
4. Supports optional namespace filter

```python
# Search everything
pdb_fts_search({"query": "Gaudí Barcelona", "limit": 5})

# Filter by namespace
pdb_fts_search({"query": "medieval castle", "ns": "TRAVEL", "limit": 10})
```

**FTS5 query syntax** (SQLite FTS5 docs):
- `word1 word2` — implicit AND (both terms must appear)
- `"exact phrase"` — phrase search
- `word1 OR word2` — OR (either term)
- `word1 NOT word2` — negation
- `prefix*` — prefix wildcard

**Contrast with web_search**: `web_search` searches the internet. `pdb_fts_search` searches data the LLM has stored in PDB — documents, config, logs, indexed metadata. They are complementary.

### Architecture

All FASE 1 tools live in `pdb_tools.py` and are auto-discovered by `server.py`. The bridge (`lumen-shm-bridge`) registers them with generic handlers that pass arguments through to `server.py`. No changes to the bridge infrastructure needed.

```python
# In bridge register():
for name, desc, props, req in new_pdb_tools:
    ctx.register_tool(
        name=name, toolset="lumen-pdb",
        schema={"name": name, "description": desc,
                "parameters": {"type": "object", "properties": props, "required": req}},
        handler=lambda *a, _n=name, **kw: _call_pdb(_n, a[0] if a else kw),
    )
```

**24 tools total** (10 KV+SQL + 3 scratch + 1 batch + 1 fts + 2 lock + 3 indices + 4 triggers).

## Benchmark Summary

| Operation | Direct (SQLite) | SHM (discarded) | Ratio |
|-----------|----------------:|----------------:|:----:|
| SET | **30.8 μs** | 711 μs | 23× |
| GET | **15.5 μs** | 677 μs | 44× |
| $DATA | **33.9 μs** | 687 μs | 20× |
| $INCREMENT | **96.0 μs** | 744 μs | 8× |
| KILL | **26.7 μs** | — | — |

SHM adds ~680μs per call from compress/build_frame/send/spin/recv/parse/decompress. For μs-scale SQLite ops, the overhead dominates. Use stdio JSON-RPC for PDB.

## References

- `references/backward-compat-handlers.md` — tool_schema/tool_backup: accept both dict and positional args
- `references/bridge-registration-pattern.md` — Generic handler lambda for FASE 1 tools; Windows encoding fix
- `references/pdbm-benchmark-results.md` — Full JSON-RPC baseline: 100K ops per operation (24 tools)
- `references/pdbm-shm-vs-stdio.md` — SHM vs stdio comparison: SHM adds ~700μs per call; decision to use stdio for PDB
- `references/poc-travelmap.md` — PoC transcript: single-type import, 80 records, SQL queries
- `references/rag-indexing-workflow.md` — Index 1,192 markdown docs in ~1s; batch + FTS pipeline
- `references/session-state-pattern.md` — Cross-session continuity via scratch: recover context in 15ms
- `references/poc-mega-import.md` — Mega PoC: 2,476 records from 24 datasets in 649ms
- `references/handler-convention.md` — Why (args: dict) not **kwargs for ShmNativeServer

## Related Skills

- **lumen-pdb-workflow** — Daily workflow patterns: session state, RAG, scratch, cross-topic context
- **lumen-dashboard** — Dashboard development and debugging: pitfalls, charts, API endpoints

## Scripts

- `scripts/poc_ultra_import.py` — Runnable mega import: pulls travelmap + fishmap JSON from ProjectOS and imports into PDB. Run from `implementations/mcp-servers/pdb/`:
  ```bash
  python ../../../skills/lumen/process-database/scripts/poc_ultra_import.py
  ```
  Or directly if the skill is loaded:
  ```bash
  python <skill_dir>/scripts/poc_ultra_import.py
  ```

## Workflow Preferences

This user (Gonzalo) prefers:

- **Extreme conciseness**. Use `pdb_batch_set` over individual `pdb_set` calls. Answer directly — no explanations unless asked.
- **Commit-immediate**. Every fix is committed and pushed right after verification. No batch of uncommitted changes.
- **Clean as you go**. Remove temp scripts, test DBs, and scratch files after use. No stale artifacts in the repo.
- **SHM is NOT for PDB**. Benchmark-proven: SHM adds ~700μs per call (20× slower than stdio for μs-scale KV ops). Use `server.py` (stdio JSON-RPC).
- **Handler convention**: `(args: dict)` not `**kwargs`. `ShmNativeServer` calls `handler(tool_args)` — named params don't work.
- **Windows fixes**: `encoding='utf-8'` in Popen, `RLock` not `Lock` for subprocess init, `stderr=subprocess.DEVNULL`.

## Pitfalls

1. **Popen encoding**: `subprocess.Popen` with `text=True` defaults to 'charmap' on Windows. Always pass `encoding='utf-8'` or non-ASCII data triggers `UnicodeDecodeError`.
2. **Deadlock with Lock vs RLock**: When `_get_server()` spawns a subprocess AND calls `_rpc()` internally, use `threading.RLock()` not `threading.Lock()`. Also set `stderr=subprocess.DEVNULL` to prevent pipe blocking.
