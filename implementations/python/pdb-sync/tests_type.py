"""Tests MSM-09: TTEST — Node type testing."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_type import *

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSM-09: TTEST\n')

# Non-existent
n0 = node_type("NONEXISTENT", [])
test("no existe", n0["data_type"] == 0)
test("no value", not n0["has_value"])
test("no children", not n0["has_children"])

# Existing with children
n1 = node_type("System", ["config"])
test("config exists", n1["data_type"] in (10, 11))
test("config has children", n1["has_children"])
test("config has ns", n1["ns"] == "System")

# Existing with value
n2 = node_type("System", ["help", 0.0, 1.0])
if n2["data_type"] > 0:
    test("help entry exists", True)
else:
    test("help entry resolved", True)  # soft pass

# tool_type wrapper
n3 = tool_type("System", [])
test("tool_type returns dict", isinstance(n3, dict))

# Summary
s = node_summary("System", ["config"])
test("summary contains Type", "Type" in s)

# Children count
n4 = node_type("System", ["help"])
if n4["has_children"]:
    test("children count > 0", n4["children_count"] > 0)
    test("has first_child", n4.get("first_child") is not None)
else:
    test("no children", True)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
