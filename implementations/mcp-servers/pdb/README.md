# PDBM-Lumen

**Process Database MUMPS-style** — Hierarchical key-value store on SQLite, with MUMPS globals semantics, RAG, and LUMEN MCP transport. **19 tools.**

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

**21 tools total** via the PDB server.

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

- **SQLite por defecto** (default: `lumen-pdb.db`, override con `PDB_PATH`)
- **redb experimental para las 7 operaciones núcleo** mediante
  `lumen_pdb.connect()` y `PDB_ENGINE=redb`; ver
  [`../../rust/lumen-pdb/README.md`](../../rust/lumen-pdb/README.md)
- **WAL mode** — concurrent reads, crash-safe writes
- **Level encoding** — type-prefixed, collation-correct byte sequences
- **Transport: stdio JSON-RPC** — PDB uses `server.py` over stdio. SHM (Level 2 zero-copy) is available via `server_shm.py` but **not recommended**: SHM adds ~700μs overhead per call, while SQLite operations take 15-96μs. For μs-scale KV ops, stdio is 20× faster.

### Embedding / RAG tools (semantic search)

Semantic search over PDB: index any text, then search "by meaning" with cosine similarity. Runs 100% local on CPU via fastembed — zero API keys, zero token cost.

| Tool | Description |
|------|-------------|
| `pdb_embed(texts, source?)` | Generate embeddings via fastembed (all-MiniLM-L6-v2, 384 dims) and store in PDB. First call downloads the model (~80MB). Deduplicates identical texts by content hash. |
| `pdb_embed_search(query, limit?)` | Semantic search by cosine similarity (vectorized numpy). Returns top-N with exact text, source and score. ~100ms/query with cached matrix (~1.7K vectors). |

**Storage layout** (MUMPS-style namespaces):

```
^EMBED(hash, dim)           — one row per dimension (float value)
^EMBED_VEC(hash)            — full vector as single JSON array (source of the search matrix)
^EMBED_META(hash, "text")   — original text
^EMBED_META(hash, "source") — source label
^EMBED_META(hash, "created")— epoch timestamp
```

- `hash` = first 16 hex chars of sha256(text) → re-embedding the same text upserts, no duplicates.
- All values are stored JSON-encoded (standard `_encode_value`), like every PDB value.
- **Search cache**: the numpy `(N×384)` matrix is built on the first query (~3s for 1.7K vectors) and cached in memory. `pdb_embed` **invalidates the cache automatically** whenever new hashes are stored, so searches always see fresh data — no manual reset needed.
- The sqlite-vec mirror tables (`_vec_embeddings`, `_vec_hierarchical`) feed `pdb_vec_search` (KNN with optional `path` partition); their failure never breaks primary PDB storage (best-effort).

Usage:
```python
# Index knowledge
pdb_embed(texts=["texto1", "texto2"], source="wiki")

# Semantic search
pdb_embed_search(query="busqueda semantica", limit=5)
# → [{"text": "...", "score": 0.86, "source": "wiki"}, ...]
```

Requires: `pip install fastembed numpy`

**Limitations:**
- `all-MiniLM-L6-v2` is English-optimized; Spanish queries work but a multilingual model would improve precision.
- `pdb_embed_search` does a linear scan over the full matrix — numpy-optimal up to ~50K vectors; beyond that a pre-filter is needed.
- No source/path filter in `pdb_embed_search`; use `pdb_vec_search(path=...)` for partitioned KNN.

**Tests:** `test_eb_regression.py` (runs against a temp DB via `PDB_PATH` — safe anywhere).

## Benchmarks

- `bench_full.py` / `bench_exec.py` / `bench_compare.py` (este directorio) — benchmarks de velocidad cruda de PDB.
- RAG medido: 1.729 vectores indexados → primera query ~3s (build de matriz), queries cacheadas ~100ms.

## Changelog (2026-06-27)

- **Embedding/RAG**: `pdb_embed` and `pdb_embed_search` via fastembed + numpy
- **M-Light fix**: commands (FOR, SET, KILL) now work via `pdb_m_eval`
- **Subkey fix**: empty strings no longer break multi-level subkeys
- **Arithmetic**: compound expressions (`T+$G(^X(I))`) now evaluate correctly
- **Vectors**: EMBED_VEC stores vectors as JSON arrays for ~100ms search

## License

MIT
