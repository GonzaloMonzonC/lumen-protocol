"""Tests IMP-01: WRITE con strings."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from m_stackvm import StackVM

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS IMP-01: WRITE\n')

# String
vm = StackVM(); vm.compile('W "hello"').exec()
t("WRITE string", vm.ops[0] == "hello")

# Newline
vm2 = StackVM(); vm2.compile('W "a",!,"b"').exec()
t("WRITE newline", "\n" in str(vm2.ops[0]))

# Concatenación
vm3 = StackVM(); vm3.compile('W "x=",42').exec()
t("WRITE concat", str(vm3.ops[0]).startswith("x="))

# Multiple
vm4 = StackVM(); vm4.compile('W "a",!,"b",!,"c"').exec()
t("WRITE multiple", str(vm4.ops[0]).count("\n") == 2)

# Empty
vm5 = StackVM(); vm5.compile("W").exec()
t("WRITE empty", len(vm5.ops) == 0)

# Con variable
vm6 = StackVM()
vm6.vars["x"] = 42
vm6.compile('W "val=",x').exec()
t("WRITE var", str(vm6.ops[0]) == "val=42")

# Parse args
from m_stackvm import StackVM
svm = StackVM()
t("parse simple", svm._parse_write_args('"a","b","c"') == ['"a"','"b"','"c"'])
t("parse with newline", svm._parse_write_args('"a",!,"b"') == ['"a"', '!', '"b"'])

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
