#!/usr/bin/env python3
"""Full benchmark for all 15 PDBM-Lumen tools (FASE 1 included)."""
import os, sys, json, time, tempfile

DB = "C:\\temp\\pdb_bench_full.db"
try:
    os.unlink(DB)
except:
    pass
os.environ["PDB_PATH"] = DB
os.makedirs("C:\\temp", exist_ok=True)
sys.path.insert(0, ".")
import pdb_tools as PDB

print("=" * 65)
print("  PDBM-Lumen: Full Benchmark (15 tools)")
print("=" * 65)

results = []
N = 5000  # standard iteration count for most tests

def bench(name, fn, n=N):
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    t = time.perf_counter() - t0
    avg_us = (t / n) * 1_000_000
    rate = n / t
    print(f"  {name:35s} {n:>6,} ops  {t*1000:>8.1f}ms  {avg_us:>6.1f}us  {rate:>8,.0f} ops/s")
    results.append({"name": name, "n": n, "total_ms": t*1000, "avg_us": avg_us, "rate_per_sec": rate})

# ── 1. KV tools ──
print("\n📦 KV Tools:")
bench("pdb_set (single)", lambda: PDB.tool_set({"ns":"K","subs":[0],"value":"x"}))
bench("pdb_get (exact)", lambda: PDB.tool_get({"ns":"K","subs":[0]}))
bench("pdb_order (first)", lambda: PDB.tool_order({"ns":"K","subs":[""],"direction":1}))
bench("pdb_data (exists)", lambda: PDB.tool_data({"ns":"K","subs":[0]}))
bench("pdb_incr (atomic)", lambda: PDB.tool_incr({"ns":"K","subs":["c"],"increment":1}))
bench("pdb_kill (subtree)", lambda: PDB.tool_set({"ns":"K","subs":[0],"value":None}))

# ── 2. SCRATCH tools ──
print("\n📝 SCRATCH Tools:")
bench("pdb_scratch_set", lambda: PDB.tool_scratch_set({"key":"k","value":"v"}))
bench("pdb_scratch_get", lambda: PDB.tool_scratch_get({"key":"k"}))
bench("pdb_scratch_del", lambda: PDB.tool_scratch_del({"key":"k"}))

# ── 3. BATCH set ──
print("\n📦 BATCH Tools:")
# Prepare batch data
batch_10 = [{"ns":"B","subs":[i],"value":f"val-{i}"} for i in range(10)]
batch_100 = [{"ns":"B","subs":[i],"value":f"val-{i}"} for i in range(100)]
batch_1000 = [{"ns":"B","subs":[i],"value":f"val-{i}"} for i in range(1000)]

t0 = time.perf_counter()
for _ in range(500):
    PDB.tool_batch_set({"items": batch_10})
t = time.perf_counter() - t0
print(f"  pdb_batch_set(10 items)         500 runs  {t*1000:>8.1f}ms  {t/500*1e6:>6.1f}us/run  {500*10/t:>8,.0f} items/s")
results.append({"name":"pdb_batch_set(10)","n":500,"total_ms":t*1000,"avg_us":t/500*1e6,"rate_per_sec":500*10/t})

t0 = time.perf_counter()
for _ in range(50):
    PDB.tool_batch_set({"items": batch_100})
t = time.perf_counter() - t0
print(f"  pdb_batch_set(100 items)         50 runs  {t*1000:>8.1f}ms  {t/50*1e6:>6.1f}us/run  {50*100/t:>8,.0f} items/s")
results.append({"name":"pdb_batch_set(100)","n":50,"total_ms":t*1000,"avg_us":t/50*1e6,"rate_per_sec":50*100/t})

# Compare: batch_set vs individual pdb_set
print("\n  ⚖️  batch_set vs individual pdb_set:")
t_batch = time.perf_counter()
PDB.tool_batch_set({"items": batch_1000})
t_batch = time.perf_counter() - t_batch

t_indiv = time.perf_counter()
for i in range(1000):
    PDB.tool_set({"ns":"I","subs":[i],"value":f"val-{i}"})
t_indiv = time.perf_counter() - t_indiv

speedup = t_indiv / t_batch
print(f"     batch_set(1000): {t_batch*1000:.1f}ms")
print(f"     pdb_set x1000:   {t_indiv*1000:.1f}ms")
print(f"     speedup: {speedup:.1f}x")
results.append({"name":"batch_vs_individual_1000","n":1000,"batch_ms":t_batch*1000,"individual_ms":t_indiv*1000,"speedup":speedup})

# ── 4. FTS Search ──
print("\n🔍 FTS Search:")
# First populate some data
PDB.tool_batch_set({"items": batch_1000})
PDB.tool_set({"ns":"FTS_DOC","subs":["doc1"],"value":"Sagrada Familia Barcelona disenada por Antoni Gaudi"})
PDB.tool_set({"ns":"FTS_DOC","subs":["doc2"],"value":"Museo Picasso en Barcelona obras de arte"})
PDB.tool_set({"ns":"FTS_DOC","subs":["doc3"],"value":"Castillo medieval Toledo fortaleza historia"})

N_fts = 100
t0 = time.perf_counter()
for _ in range(N_fts):
    PDB.tool_fts_search({"query": "Barcelona", "limit": 5})
t = time.perf_counter() - t0
avg = t/N_fts*1000
print(f"  pdb_fts_search('Barcelona', limit=5)  {N_fts:>3,} runs  {t*1000:>8.1f}ms total  {avg:>6.1f}ms/query")
results.append({"name":"fts_search_simple","n":N_fts,"total_ms":t*1000,"avg_ms_per_query":avg})

# FTS with more data
t0 = time.perf_counter()
for _ in range(N_fts):
    PDB.tool_fts_search({"query": "Barcelona", "limit": 10})
t = time.perf_counter() - t0
avg2 = t/N_fts*1000
print(f"  pdb_fts_search('Barcelona', limit=10) {N_fts:>3,} runs  {t*1000:>8.1f}ms total  {avg2:>6.1f}ms/query")
results.append({"name":"fts_search_more","n":N_fts,"total_ms":t*1000,"avg_ms_per_query":avg2})

# FTS with namespace filter
t0 = time.perf_counter()
for _ in range(N_fts):
    PDB.tool_fts_search({"query": "Barcelona", "ns": "FTS_DOC", "limit": 5})
t = time.perf_counter() - t0
avg3 = t/N_fts*1000
print(f"  pdb_fts_search('Barcelona', ns=FTS_DOC) {N_fts:>3,} runs  {t*1000:>8.1f}ms total  {avg3:>6.1f}ms/query")
results.append({"name":"fts_search_ns_filter","n":N_fts,"total_ms":t*1000,"avg_ms_per_query":avg3})

# ── 5. Schema ──
print("\n📊 Schema:")
bench("pdb_schema", lambda: PDB.tool_schema({}), n=1000)

# ── Summary ──
print("\n" + "=" * 65)
print("  SUMMARY")
print("=" * 65)
print(f"\n  DB file: {os.path.getsize(DB):,} bytes")

# Save results
os.environ.pop("PDB_PATH", None)
out = {
    "benchmark": "PDBM-Lumen Full (15 tools including FASE1)",
    "date": time.strftime("%Y-%m-%d %H:%M"),
    "results": results,
}
with open("benchmark_full.json", "w") as f:
    json.dump(out, f, indent=2)

print("\n  Results saved to benchmark_full.json")
print("  DONE")
