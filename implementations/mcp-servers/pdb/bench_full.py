"""Benchmark comparativo: Python/Rust MVM × SQLite/REDB."""
import os, sys, time, json

sys.path.insert(0, ".")

def run_bench(engine_name, mvm_env, pdb_env, db_path):
    os.environ["MVM_ENGINE"] = mvm_env
    os.environ["PDB_ENGINE"] = pdb_env
    os.environ["PDB_PATH"] = db_path

    # Clean
    for f in [db_path, db_path + "-wal", db_path + "-shm"]:
        try: os.remove(f)
        except: pass

    import pdb_tools
    from mvm import MVM
    vm = MVM(pdb_tools)

    # Workload A: 30 jobs simples (5 SET locales)
    CODE = "S a=1\nS b=a+1\nS c=b+1\nS d=c+1\nS e=d+1"
    N = 30
    t0 = time.perf_counter()
    for i in range(N):
        vm.spawn(CODE, name=f"b-{i}")
    spawn_t = time.perf_counter() - t0

    t0 = time.perf_counter()
    vm.tick_all(N)
    tick_t = time.perf_counter() - t0

    # Workload B: ^GLOBAL writes
    vm.spawn("S ^BENCH('val')=0", name="init")
    vm.tick_all(5)
    t0 = time.perf_counter()
    for i in range(50):
        vm.spawn(f"S ^BENCH('v{i}')={i}", name=f"w-{i}")
    vm.tick_all(60)
    gl_t = time.perf_counter() - t0

    if hasattr(vm, "close"):
        vm.close()
    for f in [db_path, db_path + "-wal", db_path + "-shm"]:
        try: os.remove(f)
        except: pass

    return {
        "engine": engine_name,
        "spawn_ms": round(spawn_t * 1000, 1),
        "spawn_jobs_s": round(N / spawn_t, 1),
        "tick_ms": round(tick_t * 1000, 1),
        "tick_jobs_s": round(N / tick_t, 1),
        "global_write_ms": round(gl_t * 1000, 1),
        "global_write_s": round(50 / gl_t, 1),
        "ops": N + 50,
    }

results = []
results.append(run_bench("Python+SQLite", "python", "sqlite", "bench_py_sql.db"))
results.append(run_bench("Python+REDB", "python", "redb", "bench_py_redb.redb"))
results.append(run_bench("Rust+SQLite", "rust", "sqlite", "bench_rs_sql.db"))
# Rust+REDB fails with disk I/O error, skip

print(json.dumps(results, indent=2))

# Summary table
print("\n" + "=" * 70)
print(f"{'Engine':<20} {'Spawn':>8} {'Tick':>8} {'^GLOBAL w':>10}")
print("-" * 70)
for r in results:
    print(f"{r['engine']:<20} {r['spawn_jobs_s']:>6.1f}/s {r['tick_jobs_s']:>6.1f}/s {r['global_write_s']:>8.1f}/s")
print("=" * 70)
