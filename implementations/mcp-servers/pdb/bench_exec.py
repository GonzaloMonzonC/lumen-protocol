"""Benchmark de EJECUCIÓN M pura: Python StackVM vs Rust M-Light.

Cada motor corre en un SUBPROCESO limpio: MVM_ENGINE/PDB_ENGINE/PDB_PATH
se leen al importar los módulos, así que cambiarlos en el mismo proceso
no hace nada (los módulos ya están cacheados). Las BDs temporales van a
tempfile, no al repo.

Uso:
    python3 bench_exec.py            # orquesta los 3 motores
    python3 bench_exec.py --single   # (interno) corre 1 motor con el env actual
"""
import os, sys, time, json, tempfile, subprocess

DEADLINE_S = 60  # techo por motor: si no acaba, se reporta timeout


def bench_single(iterations=100):
    import pdb_tools
    from mvm import MVM
    vm = MVM(pdb_tools)
    vm_engine = os.environ.get("MVM_ENGINE", "python")

    results = {}
    deadline = time.perf_counter() + DEADLINE_S

    def timed(key, code, per_unit=None):
        pid = vm.spawn(code, name=key)
        # El scheduler Python reinicia los procesos al terminar (pc=0,
        # READY — estilo daemon): "terminado" = una pasada completa, o sea
        # gas_total >= líneas del código. Luego se aparca (HALTED) para
        # que no siga girando en el round-robin. El motor Rust sí termina
        # sus jobs: ahí basta con drenar hasta 0 vivos.
        proc = getattr(vm, "processes", {}).get(str(pid))
        need = len([l for l in code.split("\n") if l.strip()])
        t0 = time.perf_counter()
        if proc is not None and hasattr(proc, "gas_total"):
            while proc.gas_total < need and time.perf_counter() < deadline:
                vm.tick_all(200)
            done = proc.gas_total >= need
            proc.status = "HALTED"
        else:
            done = False
            while time.perf_counter() < deadline:
                if vm.tick_all(200) == 0:
                    done = True
                    break
        t1 = time.perf_counter()
        results[f"{key}_ms"] = round((t1 - t0) * 1000, 1)
        if not done:
            results[f"{key}_timeout"] = True
        if per_unit:
            results[f"{key}_{per_unit[0]}"] = round(per_unit[1] / (t1 - t0), 0)

    # 1. LOOP aritmético puro
    timed("loop", f"S x=0 F i=1:1:{iterations} S x=x+i",
          ("iters_s", iterations))

    # 2. STRING ops ($P, $E, concat)
    timed("string", f'S s="abcdefghij" F i=1:1:{iterations} S x=$E(s,1,5)_$P("a,b,c",",",2)',
          ("ops_s", iterations))

    # 3. ^GLOBAL SET / GET
    n = min(iterations, 1000)
    timed("set", f'F i=1:1:{n} S ^BM("k",i)=i')
    timed("get", f'F i=1:1:{n} S x=$G(^BM("k",i))')

    # 4. $ORDER iteration
    timed("order_prep", f'F i=1:1:{n} S ^BO("k",i)=i')
    timed("order", 'S k="" F  S k=$O(^BO("k",k)) Q:k=""  S x=$G(^BO("k",k))')

    # 5. Mixed: dashboard sim (table generation)
    n2 = min(iterations, 500)
    timed("dash_prep", f'F i=1:1:{n2} S ^BD("r",i,"name")="item"_i,^BD("r",i,"val")=i*10')
    timed("dashboard",
          f'S h="<table>" F i=1:1:{n2} S h=h_"<tr><td>"_$G(^BD("r",i,"name"))_"</td><td>"_$G(^BD("r",i,"val"))_"</td></tr>"',
          ("rows_s", n2))

    results["vm"] = vm_engine
    results["storage"] = os.environ.get("PDB_ENGINE", "sqlite")

    if hasattr(vm, "close"):
        vm.close()
    return results


def run_engine(name, engine_flag, pdb_engine, iterations=100):
    """Lanza bench_single en un subproceso con env limpio."""
    tmp = tempfile.mkdtemp(prefix="lumen-bench-")
    ext = ".redb" if pdb_engine == "redb" else ".db"
    db_path = os.path.join(tmp, f"bench{ext}")
    env = dict(os.environ,
               MVM_ENGINE=engine_flag,
               PDB_ENGINE=pdb_engine,
               PDB_PATH=db_path)
    try:
        proc = subprocess.run(
            [sys.executable, os.path.abspath(__file__), "--single",
             str(iterations)],
            env=env, capture_output=True, text=True,
            timeout=DEADLINE_S * 2,
            cwd=os.path.dirname(os.path.abspath(__file__)),
        )
        if proc.returncode != 0:
            return {"error": (proc.stderr or proc.stdout).strip()[-400:]}
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except subprocess.TimeoutExpired:
        return {"error": f"timeout tras {DEADLINE_S * 2}s"}
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


def main():
    engines = [
        ("Python StackVM + SQLite", "python", "sqlite"),
        ("Python StackVM + REDB",   "python", "redb"),
        ("Rust M-Light + SQLite",   "rust",   "sqlite"),
    ]
    benchmarks = [(name, run_engine(name, flag, storage))
                  for name, flag, storage in engines]

    print(json.dumps([{"name": n, **r} for n, r in benchmarks], indent=2))

    print("\n" + "=" * 96)
    print(f"{'VM Engine':<26} {'Loop':>10} {'String':>10} {'SET':>8} {'GET':>8} {'$ORDER':>8} {'Dashboard':>11}")
    print("-" * 96)
    for name, r in benchmarks:
        if "error" in r:
            print(f"{name:<26} ERROR: {r['error'][:64]}")
            continue
        print(f"{name:<26} {r.get('loop_iters_s', 0):>8.0f}/s {r.get('string_ops_s', 0):>8.0f}/s "
              f"{r.get('set_ms', '-'):>6}ms {r.get('get_ms', '-'):>6}ms "
              f"{r.get('order_ms', '-'):>6}ms {r.get('dashboard_rows_s', 0):>9.0f}/s")
    print("=" * 96)


if __name__ == "__main__":
    if "--single" in sys.argv:
        idx = sys.argv.index("--single")
        iters = int(sys.argv[idx + 1]) if len(sys.argv) > idx + 1 else 100
        print(json.dumps(bench_single(iters)))
    else:
        main()
