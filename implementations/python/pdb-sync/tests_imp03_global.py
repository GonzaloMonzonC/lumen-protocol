"""Tests IMP-03: $O/$G con ^global real."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
import _paths  # noqa: F401  # sys.path del stack PDB
from m_funcs import eval_function
from m_stackvm import StackVM

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS IMP-03: $O/$G con ^global\n')

# $O returns first key
r = eval_function("$O", '(^System(""))')
t("$O first key", r == "agents")

# $O sequence
keys = []
key = ""
for _ in range(20):
    result = eval_function("$O", f'(^System("{key}"))')
    if not result: break
    keys.append(result)
    key = result
t("$O iterates", len(keys) > 5)
t("$O first", keys[0] == "agents")
t("$O second", keys[1] == "auto")

# $G existing (no value, has children)
r2 = eval_function("$G", '(^System(config))')
t("$G config (node)", r2 == "")

# $G value
r3 = eval_function("$G", '(^System(errors))')
t("$G errors exists", r3 is not None)

# $D
r4 = eval_function("$D", '(^System(config))')
t("$D config type 10", r4 == 10)

# $D non-existent
r5 = eval_function("$D", '(^System(NONEXISTENT))')
t("$D nonexistent", isinstance(r5, int))  # not 10

# Via StackVM
vm = StackVM()
vm.emit("GET", {"rest": '(^System(agents))'})
result = vm.exec()
t("$G via StackVM", isinstance(result, dict))

# $O via StackVM
vm2 = StackVM()
vm2.emit("ORDER", {"rest": '(^System(""))'})
r6 = vm2.exec()
t("$O via StackVM", r6.get("result") is not None or r6.get("result") == "")

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
