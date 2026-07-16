"""Benchmark de EJECUCIÓN M pura: Python StackVM vs Rust M-Light."""
import os, sys, time, json
sys.path.insert(0, ".")

def bench_vm(name, engine_flag, pdb_engine, db_path, iterations=5000):
    os.environ["MVM_ENGINE"] = engine_flag
    os.environ["PDB_ENGINE"] = pdb_engine
    os.environ["PDB_PATH"] = db_path
    for f in [db_path, db_path+"-wal", db_path+"-shm"]:
        try: os.remove(f)
        except: pass

    import pdb_tools
    from mvm import MVM
    vm = MVM(pdb_tools)
    vm_engine = getattr(MVM, "engine", "python")

    results = {}

    # 1. LOOP aritmético puro
    code_loop = f"S x=0 F i=1:1:{iterations} S x=x+i"
    pid = vm.spawn(code_loop, name="loop")
    t0 = time.perf_counter()
    vm.tick_all(200)  # enough gas for 5000 iterations
    t1 = time.perf_counter()
    results["loop_ms"] = round((t1-t0)*1000, 1)
    results["loop_iters_s"] = round(iterations / (t1-t0), 0)

    # 2. STRING ops ($P, $E, $F, concat)
    code_str = f'S s="abcdefghij" F i=1:1:{iterations} S x=$E(s,1,5)_$P("a,b,c",",",2)'
    pid = vm.spawn(code_str, name="str")
    t0 = time.perf_counter()
    vm.tick_all(50)
    t1 = time.perf_counter()
    results["string_ms"] = round((t1-t0)*1000, 1)
    results["string_ops_s"] = round(iterations / (t1-t0), 0)

    # 3. ^GLOBAL SET/GET (1000 writes + 1000 reads)
    N = min(iterations, 1000)
    code_set = f'F i=1:1:{N} S ^BM("k",i)=i'
    pid = vm.spawn(code_set, name="set")
    t0 = time.perf_counter()
    vm.tick_all(50)
    t1 = time.perf_counter()
    results["set_ms"] = round((t1-t0)*1000, 1)

    code_get = f'F i=1:1:{N} S x=$G(^BM("k",i))'
    pid = vm.spawn(code_get, name="get")
    t0 = time.perf_counter()
    vm.tick_all(50)
    t1 = time.perf_counter()
    results["get_ms"] = round((t1-t0)*1000, 1)

    # 4. $ORDER iteration (1000 keys)
    code_order = f'F i=1:1:{N} S ^BO("k",i)=i'
    vm.spawn(code_order, name="prep")
    vm.tick_all(200)
    code_order2 = 'S k="" F  S k=$O(^BO("k",k)) Q:k=""  S x=$G(^BO("k",k))'
    pid = vm.spawn(code_order2, name="order")
    t0 = time.perf_counter()
    vm.tick_all(50)
    t1 = time.perf_counter()
    results["order_ms"] = round((t1-t0)*1000, 1)

    # 5. Mixed: dashboard sim (table generation)
    N2 = min(iterations, 500)
    code_prep = f'F i=1:1:{N2} S ^BD("r",i,"name")="item-"_i,^BD("r",i,"val")=i*10'
    vm.spawn(code_prep, name="prep2")
    vm.tick_all(200)
    code_mix = f'S h="<table>" F i=1:1:{N2} S h=h_"<tr><td>"_$G(^BD("r",i,"name"))_"</td><td>"_$G(^BD("r",i,"val"))_"</td></tr>" S h=h_"</table>"'
    pid = vm.spawn(code_mix, name="mix")
    t0 = time.perf_counter()
    vm.tick_all(50)
    t1 = time.perf_counter()
    results["dashboard_ms"] = round((t1-t0)*1000, 1)
    results["dashboard_rows_s"] = round(N2 / (t1-t0), 0)

    results["vm"] = vm_engine
    results["storage"] = pdb_engine

    if hasattr(vm, "close"):
        vm.close()
    for f in [db_path, db_path+"-wal", db_path+"-shm"]:
        try: os.remove(f)
        except: pass

    return results

benchmarks = []
benchmarks.append(("Python StackVM + SQLite", bench_vm("py+sql", "python", "sqlite", "b1.db", 100)))
benchmarks.append(("Python StackVM + REDB",   bench_vm("py+rdb", "python", "redb", "b2.redb", 100)))
benchmarks.append(("Rust M-Light + SQLite",   bench_vm("rs+sql", "rust", "sqlite", "b3.db", 100)))

print(json.dumps([{"name": n, **r} for n, r in benchmarks], indent=2))

# Table
print("\n" + "=" * 90)
print(f"{'VM Engine':<25} {'Loop':>8} {'String':>8} {'SET':>7} {'GET':>7} {'$ORDER':>8} {'Dashboard':>10}")
print("-" * 90)
for name, r in benchmarks:
    print(f"{name:<25} {r['loop_iters_s']:>6.0f}/s {r['string_ops_s']:>6.0f}/s {r['set_ms']:>5}ms {r['get_ms']:>5}ms {r['order_ms']:>6}ms {r['dashboard_rows_s']:>8.0f}/s")
print("=" * 90)
