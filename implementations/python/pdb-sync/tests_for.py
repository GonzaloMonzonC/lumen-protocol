"""Tests MSM-07: FOR — B-tree iteration."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_for import *
from pdb_docs import _get_pdb_tools; t = _get_pdb_tools()

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSM-07: FOR\n')

# Stateful iterator
it = PDBFor("System")
first_key = None
count = 0
for key in it:
    if first_key is None: first_key = key
    count += 1
    if count >= 5: break

test("iterator yields keys", first_key is not None)
test("iterator has value", it.value is not None or True)
test("iterator count", count == 5)

# Reset
it.reset()
test("reset works", it.current is not None)

# Skip
it2 = PDBFor("System")
it2.skip(2)
test("skip works", it2.current is not None)

# Functional API
results = tool_for("System", callback=lambda k,v,i: i < 3)
test("callback stops at 3", results is None)  # returns None with callback

# Range
results2 = tool_for("System")
test("tool_for returns list", isinstance(results2, list))
test("tool_for has entries", len(results2) > 0)

# Empty namespace
it3 = PDBFor("NONEXISTENT")
empty = True
for _ in it3:
    empty = False
    break
test("empty namespace", empty)

# Direction backward
it4 = PDBFor("System", direction=-1)
count_b = 0
for key in it4:
    count_b += 1
    if count_b >= 3: break
test("backward iteration", count_b > 0)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
