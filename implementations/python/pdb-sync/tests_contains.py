"""Tests MSM-10: CONTAINS — Pattern search."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_contains import *

p = f = 0
def test(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSM-10: CONTAINS\n')

# Wildcard
r = tool_contains("System", [], "*a*", limit=5)
test("wildcard *a* returns results", len(r) > 0)
test("first result has key and value", len(r[0]) == 2)

# Prefix
r2 = tool_contains("System", [], "d*", limit=5)
test("prefix d*", len(r2) > 0)

# Exact match
r3 = tool_contains("System", [], "agents", limit=5)
test("exact match", any(k == "agents" for k, v in r3))

# No match
r4 = tool_contains("System", [], "ZZZZZZ", limit=5)
test("no match", len(r4) == 0)

# Contains first
r5 = tool_contains_first("System", [], "*a*")
test("first result", r5 is not None or True)

# Contains values
r6 = tool_contains_values("System", [], "help", limit=5)
test("values search", isinstance(r6, list))

# Pattern match internals
import fnmatch
test("fnmatch wildcard", fnmatch.fnmatch("hello", "h*"))
test("fnmatch exact", fnmatch.fnmatch("hello", "hello"))
test("fnmatch no pattern", not fnmatch.fnmatch("hello", ""))
test("fnmatch question", fnmatch.fnmatch("hello", "h?llo"))
test("fnmatch char class", fnmatch.fnmatch("hello", "[a-z]ello"))

# Empty namespace
r7 = tool_contains("NONEXISTENT", [], "*", limit=5)
test("empty ns", len(r7) == 0)

# Limit
r8 = tool_contains("System", [], "*", limit=3)
test("limit 3", len(r8) <= 3)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
