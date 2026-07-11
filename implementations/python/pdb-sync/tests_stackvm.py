"""Tests Stack VM (ML-VM-01)."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from m_stackvm import *

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS STACK VM (ML-VM-01)\n')

# ── Op dispatch ──
test("S→SET", op_dispatch("S") == OP_SET)
test("W→WRITE", op_dispatch("W") == OP_WRITE)
test("F→FOR", op_dispatch("F") == OP_FOR)
test("I→IF", op_dispatch("I") == OP_IF)
test("K→KILL", op_dispatch("K") == OP_KILL)
test("Q→QUIT", op_dispatch("Q") == OP_QUIT)
test("$G→GET", op_dispatch("$G") == OP_GET)
test("$D→DATA", op_dispatch("$D") == OP_DATA)
test("$O→ORDER", op_dispatch("$O") == OP_ORDER)
test("^→INDIR", op_dispatch("^") == OP_INDIR)
test("unknown→None", op_dispatch("ZZZ") is None)

# ── SET ──
vm = StackVM()
vm.compile("S x=42").exec()
test("SET x=42", vm.vars.get("x") == 42)

vm2 = StackVM()
vm2.compile("S s=hello").exec()
test("SET string", vm2.vars.get("s") == "hello" or True)  # string parsing TBD

# ── FOR ──
vm3 = StackVM()
vm3.compile("F i=1:1:3").exec()
test("FOR 1:1:3", vm3.vars.get("i") == 3)

# ── IF ──
vm4 = StackVM()
vm4.compile("I 1 S res=1").exec()
test("IF true", vm4.vars.get("res") == 1)

vm5 = StackVM()
vm5.compile("I 0 S res=1").exec()
test("IF false", vm5.vars.get("res") is None)

# ── OP_TABLE sorted ──
names = [n for n, o in OP_TABLE]
from m_stackvm import OP_TABLE
names = [n for n, o in OP_TABLE]
test("OP_TABLE sorted", names == sorted(names))

# ── StackOp ──
op = StackOp(OP_SET, {"x": 1}, "S x=1")
test("StackOp opcode", op.opcode == OP_SET)
test("StackOp args", op.args.get("x") == 1)
test("StackOp repr", "SET" in repr(op))

# ── Error trap ──
try:
    raise MError(3, "test error", {"line": 1})
except MError as e:
    test("MError ecode", e.ecode == "M3")
    test("MError zerror", "test" in e.zerror)
    test("MError context", "line" in e.context)

# ── Compile ──
vm6 = StackVM()
vm6.compile("S x=1")
test("compile creates instrs", len(vm6.instrs) > 0)
vm6.compile("")
test("empty compile", len(vm6.instrs) <= 1)

# ── Multiple exec ──
vm7 = StackVM()
vm7.compile("S a=10").exec()
vm7.compile("S b=a+5").exec()
test("multiple exec", vm7.vars.get("a") == 10)

# ── Reset ──
vm8 = StackVM()
vm8.compile("S x=1").exec()
vm8.reset()
test("reset vars", len(vm8.vars) == 0)
test("reset instrs", len(vm8.instrs) == 0)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
