#!/usr/bin/env python3
"""PDBM-Lumen benchmark suite — JSON-RPC baseline.
Run from implementations/mcp-servers/pdb/"""

import os, sys, time, json
sys.path.insert(0, '.')
os.environ["PDB_PATH"] = "/tmp/bench_100k.db"

from pdb_tools import *


def bench(name, fn, n, warmup=10):
    """Run fn() n times, measure total + p50/p95/p99. Warmup first."""
    # Warmup
    for _ in range(warmup):
        fn()
    
    times = []
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    t1 = time.perf_counter()
    total_ms = (t1 - t0) * 1000
    avg_us = total_ms * 1000 / n
    print(f"  {name:30s}  {n:>6,} ops  {total_ms:>8.1f}ms  {avg_us:>6.1f}μs/op")
    return {"name": name, "n": n, "total_ms": total_ms, "avg_us": avg_us}


print("=" * 65)
print("  PDBM-Lumen BENCHMARK (JSON-RPC stdio)")
print("=" * 65)

results = []

# 1. SET — write 100K nodes
def do_set(i):
    tool_set("B", [i], i)
results.append(bench("SET (single node)", lambda: do_set(0), 100_000))

# 2. SET — hierarchical (3 levels)
def do_set_hier(i):
    tool_set("B", [i, "name"], f"user-{i}")
    tool_set("B", [i, "meta", "created"], "2024-01-15")
results.append(bench("SET (3-level tree)", lambda: do_set_hier(1), 100_000))

# 3. GET — exact key lookup
results.append(bench("GET (exact key)", lambda: tool_get("B", [50000, "name"]), 100_000))

# 4. $ORDER — iteration (traverse 100K)
a = None
def do_order():
    global a
    a = tool_order("B", [a or ""], 1)
    return a["value"]
# Warmup with actual traversal
a = None
for _ in range(100):
    r = do_order()
    if not r:
        a = None
        break
a = None
# Reset and benchmark traversal
t0 = time.perf_counter()
count = 0
a = None
while True:
    r = tool_order("B", [a or ""], 1)
    if not r["value"]:
        break
    a = r["value"]
    count += 1
t1 = time.perf_counter()
total = (t1 - t0) * 1000
avg = total * 1000 / count if count else 0
print(f"  $ORDER traversal{'':29s}  {count:>6,} ops  {total:>8.1f}ms  {avg:>6.1f}μs/op")
results.append({"name": "$ORDER traversal", "n": count, "total_ms": total, "avg_us": avg})

# 5. $DATA — existence check
results.append(bench("$DATA (exists)", lambda: tool_data("B", [50000]), 100_000))

# 6. $INCREMENT — atomic counter
results.append(bench("$INCREMENT (atomic)", lambda: tool_incr("CNT", ["x"], 1), 100_000))

# 7. $DATA — not found
results.append(bench("$DATA (not found)", lambda: tool_data("B", [-1]), 100_000))

# 8. KILL subtree
results.append(bench("KILL (single node)", lambda: tool_kill("B", [99999]), 100_000))

# Summary
print("-" * 65)
print(f"  Total operations: {sum(r['n'] for r in results):,}")
print(f"  DB size: {tool_backup()['size_bytes']:,} bytes")
r = tool_schema()
if 'namespaces' in r:
    print(f"  Namespaces: {len(r['namespaces'])}")
print("=" * 65)

# Save results
out = {"benchmark": "PDBM-Lumen JSON-RPC Baseline", "date": time.strftime("%Y-%m-%d %H:%M"), "results": results}
with open("benchmark_jsonrpc.json", "w") as f:
    json.dump(out, f, indent=2)
print(f"Saved to benchmark_jsonrpc.json")
print("DONE")
