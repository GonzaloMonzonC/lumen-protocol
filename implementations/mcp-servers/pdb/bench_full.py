"""Benchmark comparativo: Python/Rust MVM × SQLite/REDB.

Cada motor corre en un SUBPROCESO limpio (los env MVM_ENGINE/PDB_ENGINE/
PDB_PATH se leen al importar; cambiarlos en caliente no re-configura los
módulos ya cacheados). BDs temporales via tempfile, no en el repo.
"""
import os, sys, time, json, tempfile, subprocess


def bench_single():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import pdb_tools
    from mvm import MVM
    vm = MVM(pdb_tools)
    engine_name = f"{os.environ.get('MVM_ENGINE', 'python')}+{os.environ.get('PDB_ENGINE', 'sqlite')}"

    pids = []

    def spawn(code, name):
        pid = vm.spawn(code, name=name)
        need = len([l for l in code.split("\n") if l.strip()])
        pids.append((str(pid), need))

    def drain(deadline_s=30):
        """El scheduler Python reinicia procesos al terminar (daemon-style):
        'hecho' = gas_total >= líneas; después se aparcan (HALTED). El motor
        Rust termina sus jobs: se drena hasta 0 vivos."""
        end = time.perf_counter() + deadline_s
        procs = getattr(vm, "processes", {})
        tracked = [(procs.get(p), need) for p, need in pids]
        if tracked and all(pr is not None and hasattr(pr, "gas_total")
                           for pr, _ in tracked):
            while time.perf_counter() < end:
                if all(pr.gas_total >= need for pr, need in tracked):
                    for pr, _ in tracked:
                        pr.status = "HALTED"
                    pids.clear()
                    return
                vm.tick_all(100)
        else:
            while time.perf_counter() < end:
                if vm.tick_all(100) == 0:
                    pids.clear()
                    return
        raise TimeoutError("tick_all no drena")

    # Workload A: 30 jobs simples (5 SET locales)
    CODE = "S a=1\nS b=a+1\nS c=b+1\nS d=c+1\nS e=d+1"
    N = 30
    t0 = time.perf_counter()
    for i in range(N):
        spawn(CODE, name=f"b-{i}")
    spawn_t = time.perf_counter() - t0

    t0 = time.perf_counter()
    drain()
    tick_t = time.perf_counter() - t0

    # Workload B: ^GLOBAL writes
    spawn("S ^BENCH('val')=0", name="init")
    drain()
    t0 = time.perf_counter()
    for i in range(50):
        spawn(f"S ^BENCH('v{i}')={i}", name=f"w-{i}")
    drain()
    gl_t = time.perf_counter() - t0

    if hasattr(vm, "close"):
        vm.close()

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


def run_engine(mvm_env, pdb_env):
    tmp = tempfile.mkdtemp(prefix="lumen-bench-")
    ext = ".redb" if pdb_env == "redb" else ".db"
    env = dict(os.environ, MVM_ENGINE=mvm_env, PDB_ENGINE=pdb_env,
               PDB_PATH=os.path.join(tmp, f"bench{ext}"))
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--single"],
            env=env, capture_output=True, text=True, timeout=120,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if proc.returncode != 0:
            return {"engine": f"{mvm_env}+{pdb_env}",
                    "error": (proc.stderr or proc.stdout).strip()[-400:]}
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"engine": f"{mvm_env}+{pdb_env}", "error": "timeout 120s"}
    finally:
        for f in os.listdir(tmp):
            try:
                os.remove(os.path.join(tmp, f))
            except OSError:
                pass
        try:
            os.rmdir(tmp)
        except OSError:
            pass


if __name__ == "__main__":
    if "--single" in sys.argv:
        print(json.dumps(bench_single()))
        sys.exit(0)

    results = [
        run_engine("python", "sqlite"),
        run_engine("python", "redb"),
        run_engine("rust", "sqlite"),
        # Rust+REDB fails with disk I/O error, skip
    ]

    print(json.dumps(results, indent=2))

    print("\n" + "=" * 70)
    print(f"{'Engine':<20} {'Spawn':>8} {'Tick':>8} {'^GLOBAL w':>10}")
    print("-" * 70)
    for r in results:
        if "error" in r:
            print(f"{r['engine']:<20} ERROR: {r['error'][:44]}")
            continue
        print(f"{r['engine']:<20} {r['spawn_jobs_s']:>6.1f}/s {r['tick_jobs_s']:>6.1f}/s {r['global_write_s']:>8.1f}/s")
    print("=" * 70)
