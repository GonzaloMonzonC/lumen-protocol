"""Tests IMP-02: Aritmética con variables."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from m_stackvm import StackVM
from m_routines import RoutineExecutor, register

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS IMP-02: Aritmética\n')

# x=x+1 con undefined (MUMPS: 0)
vm = StackVM(); vm.compile("S x=x+1").exec()
t("x+1 undefined", vm.vars.get("x") == 1)

# x=x+1 con valor previo
vm2 = StackVM(); vm2.vars["x"] = 10; vm2.compile("S x=x+1").exec()
t("x+1 initialized", vm2.vars.get("x") == 11)

# Múltiples operaciones
vm3 = StackVM()
vm3.compile("S a=0").exec()
vm3.compile("S a=a+5").exec()
vm3.compile("S a=a*2").exec()
t("a: 0+5*2", vm3.vars.get("a") == 10)

# Resta
vm4 = StackVM(); vm4.vars["x"] = 10; vm4.compile("S x=x-3").exec()
t("x-3", vm4.vars.get("x") == 7)

# Multiplicación
vm5 = StackVM(); vm5.vars["x"] = 3; vm5.compile("S x=x*4").exec()
t("x*4", vm5.vars.get("x") == 12)

# División
vm6 = StackVM(); vm6.vars["x"] = 10; vm6.compile("S x=x/2").exec()
t("x/2", vm6.vars.get("x") == 5.0)

# Script con contador
register("CNT2", "S n=0\nS n=n+1")
executor = RoutineExecutor()
r = executor.exec("CNT2")
t("script contador", r.get("vars", {}).get("n") == 1)

# FOR con contador (multi-line)
register("FORCNT", "S total=0\nF i=1:1:3 S total=total+1")
r2 = executor.exec("FORCNT")
t("FOR contador", r2.get("vars", {}).get("total") == 3)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
