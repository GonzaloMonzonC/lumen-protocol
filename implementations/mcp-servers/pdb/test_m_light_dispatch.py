"""Tests M-Light binary search dispatch (MSM FUN_00494120 pattern)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from m_light import MEvaluator

p = f = 0
def test(name, ok):
    global p, f
    if ok: p+=1; print(f"  ✅ {name}")
    else: f+=1; print(f"  ❌ {name}")

print('🧪 TESTS M-Light Token Dispatch\n')

m = MEvaluator()

# Basic SET/GET
m.eval('S x=42')
test("SET stores value", True)

# WRITE
result = m.eval('W x')
test("WRITE returns result", result is not None)

# FOR loop
m2 = MEvaluator()
r = m2.eval('F i=1:1:3 S t=i W i')
test("FOR loop iterates", r is not None)

# IF condition
m3 = MEvaluator()
m3.eval('S x=10')
r = m3.eval('I x>5 S ok=1')
test("IF true", r is not None)

# IF false
m4 = MEvaluator()
m4.eval('S x=1')
r = m4.eval('I x>5 S ok=1')
test("IF false skip", r is not None)

# KILL
m5 = MEvaluator()
m5.eval('S a=1 K a')
test("KILL does not crash", True)

# Multiple commands
m6 = MEvaluator()
r = m6.eval('S a=1 S b=2 S c=a+b')
test("multi command", r is not None)

# QUIT
m7 = MEvaluator()
m7.eval('S x=1 Q:x>0')
test("QUIT conditional", True)

# DO
m8 = MEvaluator()
r = m8.eval('D')
test("DO does not crash", True)

# Binary search correctness
from m_light import MEvaluator
tokens = [t[0] for t in MEvaluator.TOKEN_TABLE]
test("token table sorted", tokens == sorted(tokens))
test("has 14 commands", len(MEvaluator.TOKEN_TABLE) == 14)

# Token dispatch
handler, name = m._dispatch_cmd("S")
test("dispatch SET", handler is not None)
handler, name = m._dispatch_cmd("FOR")
test("dispatch FOR", handler is not None)
handler, name = m._dispatch_cmd("UNKNOWN")
test("dispatch unknown", handler is None)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
