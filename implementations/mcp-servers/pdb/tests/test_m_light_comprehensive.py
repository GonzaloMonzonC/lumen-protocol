"""M-Light comprehensive test"""
import sys, json
sys.path.insert(0, '.')
from pdb_tools import HANDLERS
from m_light import MEvaluator

def test(name, ok, detail=""):
    tag = "✅" if ok else "❌"
    print(f"{tag} {name}", end="")
    if detail:
        print(f" — {detail}")
    else:
        print()

print("=== 1. SET/GET básico ===")
r = HANDLERS["pdb_set"]({"ns": "T", "subs": [1], "value": "hola"})
r2 = HANDLERS["pdb_get"]({"ns": "T", "subs": [1]})
test("SET/GET", r2.get("value") == "hola", f"GET={r2.get('value')}")

print()
print("=== 2. M-Light expr eval ===")
m = MEvaluator(HANDLERS)

# $PIECE
v = m.eval_expr('$P("a|b|c","|",2)')
test("$PIECE", v == "b", str(v))

# $EXTRACT
v = m.eval_expr('$E("hello",2,4)')
test("$EXTRACT", v == "ell", str(v))

# $SELECT
v = m.eval_expr('$S(1=2:"no",1:"yes")')
test("$SELECT", v == "yes", str(v))

# $GET via PDB
v = m.eval_expr('$G(^T(1))')
test("$GET PDB", v == "hola", str(v))

print()
print("=== 3. F loop + $O + Q:cond ===")
# Populate
for name in ["ana", "juan", "pepe", "zoe"]:
    HANDLERS["pdb_set"]({"ns": "N", "subs": [name], "value": 1})

m2 = MEvaluator(HANDLERS)
r = m2.eval('S N="" F  S N=$O(^N(N)) Q:N=""  Q:N="pepe"')
test("F loop + Q encuentra pepe", r.get("N") == "pepe", f"N={r.get('N')}")
test("_quit_flag True", m2._quit_flag)

print()
print("=== 4. IF bloque ===")
m3 = MEvaluator(HANDLERS)
m3.eval("S X=5 IF X=5 { S ^IFT(1)=42 }")
r = HANDLERS["pdb_get"]({"ns": "IFT", "subs": [1]})
test("IF verdadero", r.get("value") == 42, str(r))

# IF false shouldn't execute
m3b = MEvaluator(HANDLERS)
m3b.eval("S X=3 IF X=5 { S ^IFT(2)=99 }")
r = HANDLERS["pdb_get"]({"ns": "IFT", "subs": [2]})
test("IF falso no ejecuta", r.get("found") == False, str(r))

print()
print("=== 5. Nested ORDER ===")
HANDLERS["pdb_set"]({"ns": "CAT", "subs": [1, "a"], "value": "1xa"})
HANDLERS["pdb_set"]({"ns": "CAT", "subs": [1, "b"], "value": "1xb"})
m4 = MEvaluator(HANDLERS)
m4.eval('S I="" F  S I=$O(^CAT(I)) Q:I=""  S J="" F  S J=$O(^CAT(I,J)) Q:J=""  S ^RES(I,J)=$G(^CAT(I,J))')
r1 = HANDLERS["pdb_get"]({"ns": "RES", "subs": [1, "a"]})
r2 = HANDLERS["pdb_get"]({"ns": "RES", "subs": [1, "b"]})
test("Nested ORDER (1,a)", r1.get("value") == "1xa", str(r1))
test("Nested ORDER (1,b)", r2.get("value") == "1xb", str(r2))

print()
print("=== 6. pdb_m_eval tool ===")
r = HANDLERS["pdb_m_eval"]({"expression": '$G(^T(1))'})
test("m_eval $GET", r.get("value") == "hola", str(r))

r = HANDLERS["pdb_m_eval"]({"expression": '$P("x|y|z","|",3)'})
test("m_eval $PIECE", r.get("value") == "z", str(r))

print()
print("✅ ALL TESTS DONE")
