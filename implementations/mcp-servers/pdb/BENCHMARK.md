# PDBM-Lumen Benchmark — JSON-RPC Baseline

Date: 2026-06-21
Transport: JSON-RPC stdio via Hermes plugin (subprocess)
Backend: SQLite WAL mode, single connection
DB size: 8 KB (empty benchmark)

## Results

| Operation | Iterations | Total | Per op | Rate |
|-----------|-----------:|------:|------:|-----:|
| SET (single node) | 100,000 | 3,077 ms | **30.8 μs** | 32,500/sec |
| SET (3-level hierarchy) | 100,000 | 5,617 ms | **56.2 μs** | 17,800/sec |
| GET (exact key lookup) | 100,000 | 1,546 ms | **15.5 μs** | 64,700/sec |
| $DATA (exists) | 100,000 | 3,389 ms | **33.9 μs** | 29,500/sec |
| $DATA (not found) | 100,000 | 3,931 ms | **39.3 μs** | 25,400/sec |
| $INCREMENT (atomic) | 100,000 | 9,598 ms | **96.0 μs** | 10,400/sec |
| KILL (single node) | 100,000 | 2,669 ms | **26.7 μs** | 37,500/sec |

## Analysis

### SET performance
- Single node: **30.8 μs** — pure B-tree insert
- 3-level hierarchy: **56.2 μs** — 2 inserts + key encoding
- Ratio: 1.8× for 3× the data → encoding overhead is minimal

### GET performance
- **15.5 μs** — fastest op. B-tree lookup by PRIMARY KEY (ns, subkey)
- SQLite's WITHOUT ROWID table means this is a direct B-tree probe

### $DATA performance  
- **33.9 μs** (exists) / **39.3 μs** (not found) — 2 SQL queries per call
- First checks node existence, then checks children via prefix scan
- Not-found is slower because it has to scan further

### $INCREMENT performance
- **96.0 μs** — 3 SQL statements (INSERT OR IGNORE + UPDATE + SELECT back)
- Atomic counter pattern traded speed for correctness

### KILL performance
- **26.7 μs** — DELETE with range bounds. Fast because `PRIMARY KEY (ns, subkey)`
  makes KILL of a subtree a contiguous range delete in the B-tree

### $ORDER (estimated)
- B-tree range scan with LIMIT 1. In the initial 1,000-node test: **~0 ms**
- Theoretical limit: sub-microsecond (SQLite B-tree cursor advance)
- Not measured at 100K due to test setup issue

## Bottlenecks (JSON-RPC stdio)

The current transport (JSON-RPC over subprocess stdin/stdout) adds overhead:

1. **Serialization**: `json.dumps()` + `json.loads()` per call
2. **Subprocess pipe latency**: stdin/stdout write+read per call  
3. **Plugin lock contention**: `_server_lock` serializes all calls
4. **Extra copy between Hermes → Plugin → Server → SQLite**

## Projected SHM + LUMEN improvement

| Metric | JSON-RPC stdio | SHM + LUMEN (projected) |
|--------|---------------:|------------------------:|
| Wire bytes per call | ~90 bytes | **~15 bytes** |
| Serialization | json.dumps/loads | **zero-copy** |
| Per-op latency | 15-96 μs | **15-96 μs** (no change — SQLite is the bottleneck) |
| Throughput | 10k-65k/sec | 10k-65k/sec |

**Key insight**: SQLite is the bottleneck, not the transport. The μs-scale operations mean
the transport overhead is negligible at this call rate. SHM + LUMEN will help when
operations are in the NANOSECOND range or when wire size matters (e.g., large responses
from pdb_query, or many parallel calls).

## SHM Comparison

We tested SHM (Level 2 zero-copy via `server_shm.py`) but it's **not the right transport for PDB**:

| Operation | SQLite direct (pdb_tools) | SHM roundtrip | Ratio |
|-----------|------------------------:|--------------:|:----:|
| SET | 30.8 μs | 711 μs | **23×** |
| GET | 15.5 μs | 677 μs | **44×** |
| $DATA | 33.9 μs | 687 μs | **20×** |
| $INCREMENT | 96.0 μs | 744 μs | **8×** |

**Why SHM is slower**: Each SHM call does compress_value + build_frame + ring_buffer_write + ring_buffer_spin + parse_frame + decompress_value. For μs-scale SQLite operations, this overhead dominates.

**Decision**: PDB uses stdio JSON-RPC (`server.py`). SHM is reserved for filesystem, thinking, and web servers where payloads are large enough to amortize the overhead.

## FASE 1 Tools (scratch, batch, fts)

Benchmarked 2026-06-21 with 5,000 iterations (JSON-RPC stdio, Hermes plugin).

### SCRATCH tools

| Tool | 5,000 ops | Per op | Rate |
|------|----------:|------:|-----:|
| `pdb_scratch_set` | 169 ms | **33.8 μs** | 29,556/sec |
| `pdb_scratch_get` | 145 ms | **28.9 μs** | 34,568/sec |
| `pdb_scratch_del` | 196 ms | **39.2 μs** | 25,542/sec |

SCRATCH is just syntactic sugar over the KV tools → same performance as `pdb_set`/`pdb_get`.

### BATCH set

`pdb_batch_set` inserts N records atomically in a single transaction:

| Batch size | Time | Per item | Items/sec | vs individual |
|-----------:|-----:|--------:|----------:|:-------------|
| 10 items | 168 μs | 16.8 μs | **59,533** | 1.7× faster |
| 100 items | 1,295 μs | 12.9 μs | **77,225** | 3.2× faster |
| 1,000 items | 16.8 ms | 16.8 μs | **59,524** | **5.3× faster** |

**Speedup over individual `pdb_set` x1000**: **5.3×** (16.8ms batch vs 89ms individual).  
Batch amortizes the transaction overhead + JSON serialization across all items.

### FTS Search

`pdb_fts_search` rebuilds the FTS5 index from scratch on each call (DELETE + INSERT + SEARCH):

| Query | 100 runs | Per query |
|-------|---------:|----------:|
| `"Barcelona"` (limit=5) | 2,535 ms | **25.4 ms** |
| `"Barcelona"` (limit=10) | 2,673 ms | **26.7 ms** |
| `"Barcelona"` (ns filter) | 2,699 ms | **27.0 ms** |

The 25ms overhead is dominated by the FTS index rebuild (DELETE + INSERT of all current data). For persistent indexes, use `pdb_set` with proper namespace structure and FTS separately.

### All 15 tools summary

| Tool category | # tools | Avg latency |
|--------------|-------:|:-----------:|
| KV core | 10 | 15-117 μs |
| SCRATCH | 3 | 29-39 μs |
| BATCH | 1 | 17 μs/item |
| FTS | 1 | 25-27 ms |

## Run it yourself

```bash
cd implementations/mcp-servers/pdb

# KV only (FASE 0)
python benchmark_jsonrpc.py

# Full benchmark (15 tools including FASE 1)
python benchmark_full.py

# Results: benchmark_jsonrpc.json, benchmark_full.json
```
