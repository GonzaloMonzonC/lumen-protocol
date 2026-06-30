"""PDB + M-Light — Benchmark rápido"""
import os, sys, time, tempfile

db_dir = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(db_dir, "b.db")
if "pdb_tools" in sys.modules: del sys.modules["pdb_tools"]
if "m_light" in sys.modules: del sys.modules["m_light"]
sys.path.insert(0, ".")
import pdb_tools
from m_light import MEvaluator

N = 500  # Small batch for reliability

def timer(fn, n=N):
    for _ in range(20): fn()  # warmup
    t0 = time.perf_counter()
    for _ in range(n): fn()
    t = time.perf_counter() - t0
    ops = n / t
    us = (t / n) * 1_000_000
    return ops, us

print("=" * 55)
print("PDB + M-Light BENCHMARK")
print("=" * 55)

# 1. RAW SET
i = [0]
def do_set():
    i[0] += 1
    pdb_tools.tool_set({"ns": "B", "subs": [i[0]], "value": f"v{i[0]}"})
ops, us = timer(do_set)
print(f"  pdb_set:         {ops:>7.0f} ops/s  ({us:.1f} µs)")

# 2. RAW GET
i[0] = 1
def do_get():
    i[0] += 1
    if i[0] > N: i[0] = 1
    pdb_tools.tool_get({"ns": "B", "subs": [i[0]]})
ops, us = timer(do_get)
print(f"  pdb_get:         {ops:>7.0f} ops/s  ({us:.1f} µs)")

# 3. $ORDER
i[0] = ""
def do_order():
    r = pdb_tools.tool_order({"ns": "B", "subs": [i[0]]})
    i[0] = r.get("value") or ""
    if not i[0]: i[0] = ""
ops, us = timer(do_order)
print(f"  pdb_order:       {ops:>7.0f} ops/s  ({us:.1f} µs)")

# 4. M-Light eval_expr $GET
m = MEvaluator(pdb_tools)
i[0] = 1
def do_ml_get():
    i[0] += 1
    if i[0] > N: i[0] = 1
    m.eval_expr(f'$G(^B({i[0]}))')
ops, us = timer(do_ml_get)
print(f"  m_light \$GET:    {ops:>7.0f} ops/s  ({us:.1f} µs)")

# 5. M-Light eval SET
m2 = MEvaluator(pdb_tools)
i[0] = N + 1
def do_ml_set():
    i[0] += 1
    m2.eval(f'S ^B({i[0]})="{i[0]}"')
ops, us = timer(do_ml_set)
print(f"  m_light SET:     {ops:>7.0f} ops/s  ({us:.1f} µs)")

# 6. F loop
m3 = MEvaluator(pdb_tools)
def do_floop():
    m3.eval('S I="" F  S I=$O(^B(I)) Q:I=""')
ops, us = timer(do_floop, 100)
print(f"  m_light F loop:  {ops:>7.0f} ops/s  ({us:.1f} µs)")

# 7. M-Light real-world mixed
m4 = MEvaluator(pdb_tools)
def do_mixed():
    m4.eval('S I="" F  S I=$O(^B(I)) Q:I=""  S V=$G(^B(I))')
ops, us = timer(do_mixed, 100)
print(f"  m_light \$O+\$GET: {ops:>7.0f} ops/s  ({us:.1f} µs)")

print()
print("OVERHEAD (vs raw PDB):")
# Compare
s1, u1 = timer(do_get)
s2, u2 = timer(do_ml_get)
print(f"  M-Light GET is {s2/s1:.1f}x slower than raw PDB")

s1, u1 = timer(do_set)
s2, u2 = timer(do_ml_set)
print(f"  M-Light SET is {s2/s1:.1f}x slower than raw PDB")

# DB size
sz = os.path.getsize(os.environ["PDB_PATH"])
print(f"\nDB: {sz/1024:.0f} KB for {N*2+100} records")
print(f"Avg: {sz/(N*2+100):.0f} bytes/record")
print()
print("=" * 55)
print("DONE")
