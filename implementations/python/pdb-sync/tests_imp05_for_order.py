"""Tests IMP-05: FOR + $O loop."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from m_stackvm import StackVM
from m_routines import RoutineExecutor, register

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS IMP-05: FOR + $O loop\n')

# Scan básico
vm = StackVM()
vm.compile('F S x=$O(^System(x)) Q:x=""').exec()
t("$O loop iterates", len(vm.ops) > 5)
t("first key agents", vm.ops[0] == "agents")
t("second key auto", vm.ops[1] == "auto")
t("last key startup", vm.vars.get("x") == "startup")

# Escaneo con contador
vm2 = StackVM()
vm2.compile('S cnt=0').exec()
vm2.compile('F S x=$O(^System(x)) Q:x=""').exec()
t("$O with counter", len(vm2.ops) >= 10)

# Multi-namespace
vm3 = StackVM()
vm3.compile('F S ns=$O(^ROUTINE(ns)) Q:ns=""').exec()
t("$O over ^ROUTINE", len(vm3.ops) > 10)

# QUIT condition
vm4 = StackVM()
vm4.compile('F S x=$O(^System(x)) Q:x="compare"').exec()
t("$O quit at compare", vm4.vars.get("x") == "compare")

# FOR with $O via RoutineExecutor
register("SCAN_TEST", 'F S k=$O(^System(k)) Q:k=""')
executor = RoutineExecutor()
r = executor.exec("SCAN_TEST")
t("DO ^SCAN_TEST", r.get("result") is not None or len(r.get("vars",{})) > 0)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
