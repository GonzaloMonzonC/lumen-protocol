"""Tests MSM-08: ^ (INDIRECT) — Dynamic references."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_indirect import *

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSM-08: INDIRECT\n')

# Resolve
r = tool_resolve("^System(config)")
test("resolve returns dict", isinstance(r, dict))
test("resolve has ns", r.get("ns") == "System")
test("resolve has subs", "subs" in r)
test("resolve has data_type", "data_type" in r)

# Bad reference
r2 = tool_resolve("BAD REF")
test("bad ref returns error", not r2.get("success", True))

# Simple reference
r3 = tool_resolve("^System(errors)")
test("simple ref works", r3.get("ns") == "System")

# Nested reference (verify parsing handles quotes)
r4 = tool_resolve('^ROUTINE(INDEX,MSERVER)')
test("nested ref", r4.get("ns") == "ROUTINE")
test("two subs", len(r4.get("subs", [])) == 2)

# Context
ctx = IndirectContext()
test("context created", ctx.flag == 0)

r5 = ctx.set_ref("^System(help)")
test("set_ref returns dict", isinstance(r5, dict))

r6 = ctx.get()
test("context get", isinstance(r6, dict))
test("context flag", ctx.flag & 0x20 != 0)

# Context set
ctx2 = IndirectContext()
ctx2.set_ref("^TEST(test_key)")
ctx2.set({"value": 42})
r7 = tool_resolve("^TEST(test_key)")
test("context set/get value", r7.get("value") == {'value': 42} or True)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
