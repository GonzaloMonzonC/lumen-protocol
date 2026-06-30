"""Progressive test to find hanging code"""
import sys
sys.path.insert(0, '.')
from pdb_tools import HANDLERS
from m_light import MEvaluator

print("1. SET...")
r = HANDLERS["pdb_set"]({"ns": "T1", "subs": [1], "value": "ok"})
print(f"   {r}")

print("2. GET...")
r = HANDLERS["pdb_get"]({"ns": "T1", "subs": [1]})
print(f"   {r}")

print("3. PIECE...")
m = MEvaluator(HANDLERS)
v = m.eval_expr('$P("a|b|c","|",2)')
print(f"   {v}")

print("4. Populate...")
for name in ["ana","juan","pepe"]:
    r = HANDLERS["pdb_set"]({"ns": "N2", "subs": [name], "value": 1})
    print(f"   SET {name}: {r}")

print("5. ORDER test...")
r = HANDLERS["pdb_order"]({"ns": "N2", "subs": [""]})
print(f"   ORDER first: {r}")

print("6. F loop START...")
m2 = MEvaluator(HANDLERS)
m2.eval('S N="" F  S N=$O(^N2(N)) Q:N=""  Q:N="pepe"')
print("   F loop END")
print(f"   N={m2.scope.get('N')} quit={m2._quit_flag}")

print("7. Done!")
