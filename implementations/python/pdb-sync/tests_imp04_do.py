"""Tests IMP-04: DO subrutina con labels."""
import sys, os
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from m_stackvm import StackVM
from m_routines import RoutineExecutor, register

p = fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

print('🧪 TESTS IMP-04: DO subrutina\n')

# DO label simple
vm = StackVM()
vm.compile("D SETIT\nQ\nSETIT\nS x=42\nQ").exec()
t("DO label sets x", vm.vars.get("x") == 42)

# DO label con código antes
vm2 = StackVM()
vm2.compile("S a=1\nD ADD\nW a\nQ\nADD\nS a=a+1\nQ").exec()
t("DO incrementa a", vm2.vars.get("a") == 2)

# Múltiples DO
vm3 = StackVM()
vm3.compile("S cnt=0\nD INC\nD INC\nD INC\nQ\nINC\nS cnt=cnt+1\nQ").exec()
t("DO 3 veces", vm3.vars.get("cnt") == 3)

# GOTO
vm4 = StackVM()
vm4.compile("G END\nS x=1\nQ\nEND\nS x=99\nQ").exec()
t("GOTO salta x=99", vm4.vars.get("x") == 99)

# GOTO salta código intermedio
vm5 = StackVM()
vm5.compile("S y=1\nG SKIP\nS y=99\nQ\nSKIP\nS y=42\nQ").exec()
t("GOTO skips code", vm5.vars.get("y") == 42)

# Label detection
vm6 = StackVM()
vm6.compile("LABEL\nS a=1\nQ")
t("label detected", "LABEL" in vm6.labels)

# Label no es comando MUMPS
vm7 = StackVM()
vm7.compile("START\nS x=1\nQ")
t("START is label", "START" in vm7.labels)

# Labels en script con RoutineExecutor
register("DOTEST", "D SUB\nQ\nSUB\nS val=99\nQ")
executor = RoutineExecutor()
r = executor.exec("DOTEST")
t("DO via RoutineExecutor", r.get("vars", {}).get("val") == 99)

# DO sin label existente
vm8 = StackVM()
vm8.compile("D NONEXISTENT\nQ")
r8 = vm8.exec()
t("DO nonexistent", r8 is not None)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
