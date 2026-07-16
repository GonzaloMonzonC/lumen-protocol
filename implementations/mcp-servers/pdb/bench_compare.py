import time, os, sys, json
os.environ["PDB_PATH"] = "bench_test.db"
sys.path.insert(0, ".")

import pdb_tools
from mvm import MVM

# Clean
for f in ["bench_test.db", "bench_test.db-wal", "bench_test.db-shm"]:
    try: os.remove(f)
    except: pass

vm = MVM(pdb_tools)
engine = getattr(MVM, "engine", "python")

N = 50
t0 = time.perf_counter()
for i in range(N):
    vm.spawn(f'S x={i} W x Q', name=f"b-{i}")
vm.tick_all(N * 2)
t1 = time.perf_counter()
ms = (t1 - t0) * 1000

print(f"Engine: {engine}")
print(f"  Spawn {N} jobs: {ms:.0f}ms total, {ms/N*1000:.0f}us/job")

# Read-back
vm.spawn("S ^BENCH('val')=99", name="w")
vm.tick_all(5)
t0 = time.perf_counter()
for i in range(100):
    pdb_tools.tool_get({"ns":"BENCH","subs":["val"]})
t1 = time.perf_counter()
ms2 = (t1 - t0) * 1000
print(f"  100 ^GLOBAL reads: {ms2:.0f}ms, {ms2/100*1000:.0f}us/read")

if hasattr(vm, "close"):
    vm.close()
for f in ["bench_test.db", "bench_test.db-wal", "bench_test.db-shm"]:
    try: os.remove(f)
    except: pass
