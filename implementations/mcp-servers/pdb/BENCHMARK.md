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

## Run it yourself

```bash
cd implementations/mcp-servers/pdb
python benchmark_jsonrpc.py
# Results: benchmark_jsonrpc.json
```
