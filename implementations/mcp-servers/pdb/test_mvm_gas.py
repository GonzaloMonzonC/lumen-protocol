"""
Test MVM Gas System v2 — gas_used per-tick, gas_total acumulado
"""
import sys, os, json, time

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)
sys.modules[pdb_tools.__name__] = pdb_tools

from mvm import MVM, MProcess, READY, DEAD

PASS, FAIL = 0, 0

def check(cond, label):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {label}")
    else:
        FAIL += 1
        print(f"  ❌ {label}")

pdb = pdb_tools
# Limpiar
try:
    for ns in ["PROCESSES"]:
        pid = ""
        while True:
            r = pdb.tool_order({"ns": ns, "subs": [pid], "direction": 1})
            if r.get("value") is None:
                break
            pid = r["value"]
            pdb.tool_kill({"ns": ns, "subs": [pid]})
    # Limpiar STATE de tests previos
    for p in ["1","2","3","4","5"]:
        pdb.tool_kill({"ns": "STATE", "subs": [p]})
except Exception:
    pass

# ── Test 1: gas_limit=2, cede y continúa en siguiente tick ──
print("📌 Test 1: gas_limit=2 → ejecuta 2 por tick, continúa en siguiente")
mvm = MVM(pdb, max_gas_global=500)

code = """SET x=1
SET y=2
SET z=3
SET w=4
SET result=5"""
pid = mvm.spawn(code, name="gas_test_1")
proc = mvm.get_process(pid)
proc.gas_limit = 2

print(f"   PID={pid}, gas_limit=2, 5 líneas total")

# Tick 1: debe ejecutar 2 líneas y ceder
mvm.tick_all(max_per_process=10)
proc = mvm.get_process(pid)
check(proc.gas_used == 2, f"Tick1 gas_used=2 → {proc.gas_used}")
check(proc.gas_total == 2, f"Tick1 gas_total=2 → {proc.gas_total}")
check(proc.status == READY, f"Tick1 status=READY → {proc.status}")
check(proc.pc == 2, f"Tick1 pc=2 → {proc.pc}")

# Tick 2: ejecuta 2 más
mvm.tick_all(max_per_process=10)
proc = mvm.get_process(pid)
check(proc.gas_used == 2, f"Tick2 gas_used=2 → {proc.gas_used}")
check(proc.gas_total == 4, f"Tick2 gas_total=4 → {proc.gas_total}")
check(proc.status == READY, f"Tick2 status=READY → {proc.status}")
check(proc.pc == 4, f"Tick2 pc=4 → {proc.pc}")

# Tick 3: ejecuta la última
mvm.tick_all(max_per_process=10)
proc = mvm.get_process(pid)
check(proc.gas_used == 1, f"Tick3 gas_used=1 (última) → {proc.gas_used}")
check(proc.gas_total == 5, f"Tick3 gas_total=5 → {proc.gas_total}")
check(proc.status == DEAD, f"Tick3 status=DEAD → {proc.status}")

# ── Test 2: FOR loop con instrucciones > gas_limit ──
print("\n📌 Test 2: Loop con suficientes líneas para forzar yield")
mvm2 = MVM(pdb, max_gas_global=500)
# Cada línea es 1 instrucción. 6 líneas = 6 instrucciones.
code2 = """SET a=1
SET a=2
SET a=3
SET a=4
SET a=5
SET a=6"""
pid2 = mvm2.spawn(code2, name="gas_test_2")
proc2 = mvm2.get_process(pid2)
proc2.gas_limit = 3

mvm2.tick_all(max_per_process=10)
proc2 = mvm2.get_process(pid2)
check(proc2.gas_used == 3, f"gas_used=3 → {proc2.gas_used}")
check(proc2.status == READY, f"status=READY → {proc2.status}")

mvm2.tick_all(max_per_process=10)
proc2 = mvm2.get_process(pid2)
check(proc2.gas_used == 3, f"gas_used=3 (segundo tick) → {proc2.gas_used}")
check(proc2.gas_total == 6, f"gas_total=6 → {proc2.gas_total}")
check(proc2.status == DEAD, f"status=DEAD → {proc2.status}")

# ── Test 3: max_gas_global=4 aborta ──
print("\n📌 Test 3: max_gas_global=4 aborta proceso tras 4+ instrucciones")
mvm3 = MVM(pdb, max_gas_global=4)
code3 = """SET x=1
SET x=2
SET x=3
SET x=4
SET x=5"""
pid3 = mvm3.spawn(code3, name="gas_test_3")
proc3 = mvm3.get_process(pid3)
proc3.gas_limit = 100  # sin límite por tick

# Ejecutar hasta que muera
for i in range(5):
    mvm3.tick_all(max_per_process=10)
    proc3 = mvm3.get_process(pid3)
    if proc3 and proc3.status == DEAD:
        break

proc3 = mvm3.get_process(pid3)
check(proc3.status == DEAD, f"status=DEAD → {proc3.status}")
check("ABORTED" in (proc3.error or ""), f"error ABORTED → {proc3.error}")
check(proc3.gas_total <= 4 or proc3.gas_total <= 5, f"gas_total limitado → {proc3.gas_total}")

# ── Test 4: Persistencia ──
print("\n📌 Test 4: Persistencia en ^STATE")
mvm4 = MVM(pdb, max_gas_global=500)
code4 = "SET a=1"
pid4 = mvm4.spawn(code4, name="gas_test_4")
proc4 = mvm4.get_process(pid4)
proc4.gas_limit = 10
mvm4.tick_all(max_per_process=10)

r = pdb.tool_get({"ns": "STATE", "subs": [str(pid4), "gas_limit"]})
check(r.get("success") and r.get("value") == "10", f"gas_limit=10 → {r}")
r = pdb.tool_get({"ns": "STATE", "subs": [str(pid4), "gas_total"]})
check(r.get("success") and r.get("value") == "1", f"gas_total=1 → {r}")

# Cleanup
for m in [mvm, mvm2, mvm3, mvm4]:
    for p in [pid, pid2, pid3, pid4]:
        try:
            m.kill(p)
        except:
            pass

total = PASS + FAIL
print(f"\n{'='*50}")
print(f"Resultados: {PASS}/{total} ✅  {FAIL}/{total} ❌")
if FAIL == 0:
    print("🎯 Todos los tests pasaron!")
else:
    print(f"⚠️  {FAIL} tests fallaron")
