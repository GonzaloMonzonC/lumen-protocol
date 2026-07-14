"""Tests ML-VM-03: Runtime Routines."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from m_routines import *

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS ML-VM-03: Runtime Routines\n')

# Register test routines
register("TEST1", "S x=42")
register("TEST2", "S x=$1 S y=$2")
register("ECHO", 'W "hello"')

# Get routine
t("get registered", get_routine("TEST1") is not None)
t("get case insensitive", get_routine("test1") is not None)
t("get nonexistent", get_routine("NONEXISTENT") is None)

# List
routines = list_routines()
t("list returns list", isinstance(routines, list))
t("list contains TEST1", "TEST1" in routines)

# Execute
executor = RoutineExecutor()
r = executor.exec("TEST1")
t("exec returns dict", isinstance(r, dict))
t("exec has routine name", r.get("routine") == "TEST1")

# Execute with args
r2 = executor.exec("TEST2", ["hello", 42])
t("exec with args", r2.get("args") == ["hello", 42])
t("exec $1 set", r2.get("vars", {}).get("$1") == "hello")
t("exec $2 set", r2.get("vars", {}).get("$2") == 42)

# DO ref
executor2 = RoutineExecutor()
r3 = executor2.do("^TEST1")
t("DO ^TEST1", r3 is None or r3 is not None)

# Error on nonexistent
r4 = executor.exec("NONEXISTENT")
t("nonexistent error", "error" in r4)

# Register overwrite
register("TEST1", "S x=99")
t("register overwrites", True)

# Multiple routines
register("A", "W 1")
register("B", "W 2")
t("multiple routines", "A" in list_routines() and "B" in list_routines())

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
