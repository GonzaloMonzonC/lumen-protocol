"""Standalone M-Light test in a subprocess with separate DB"""
import os, sys, tempfile, subprocess

script = r"""
import os, sys
os.environ['PDB_PATH'] = os.path.join(os.environ['TMPDIR'], 'test_pdb.db')

if 'pdb_tools' in sys.modules:
    del sys.modules['pdb_tools']
if 'm_light' in sys.modules:
    del sys.modules['m_light']

sys.path.insert(0, '.')
import pdb_tools
from m_light import MEvaluator
import time
start = time.time()

def test(name, ok, detail=""):
    tag = "✅" if ok else "❌"
    elapsed = time.time() - start
    print(f"[{elapsed:.1f}s] {tag} {name}", end="")
    if detail: print(f" — {detail}")
    else: print()

# 1. SET/GET
r = pdb_tools.tool_set({'ns':'T','subs':[1],'value':'hola'})
r = pdb_tools.tool_get({'ns':'T','subs':[1]})
test("SET/GET basico", r.get('value') == 'hola', str(r.get('value')))

# 2. PIECE
m = MEvaluator(pdb_tools)
v = m.eval_expr('$P("a|b|c","|",2)')
test("PIECE", v == 'b', str(v))

# 3. EXTRACT
v = m.eval_expr('$E("hello",2,4)')
test("EXTRACT", v == 'ell', str(v))

# 4. SELECT
v = m.eval_expr('$S(1=2:"no",1:"yes")')
test("SELECT default", v == 'yes', str(v))

# 5. GET via PDB
v = m.eval_expr('$G(^T(1))')
test("GET via PDB", v == 'hola', str(v))

# 6. F loop + $O + Q:cond
for name in ['ana','juan','pepe','zoe']:
    pdb_tools.tool_set({'ns':'N','subs':[name],'value':1})

m2 = MEvaluator(pdb_tools)
m2.eval('S N="" F  S N=$O(^N(N)) Q:N=""  Q:N="pepe"')
test("F loop encuentra pepe", m2.scope.get('N') == 'pepe', str(m2.scope.get('N')))
test("quit flag True", m2._quit_flag, str(m2._quit_flag))

# 7. IF bloque
m3 = MEvaluator(pdb_tools)
m3.eval("S X=5 IF X=5 { S ^IFT(1)=42 }")
r = pdb_tools.tool_get({'ns':'IFT','subs':[1]})
test("IF verdadero", r.get('value') == 42, str(r))

# IF false
m3b = MEvaluator(pdb_tools)
m3b.eval("S X=3 IF X=5 { S ^IFT(2)=99 }")
r = pdb_tools.tool_get({'ns':'IFT','subs':[2]})
test("IF falso no ejecuta", r.get('found') == False, str(r))

# 8. Nested ORDER
pdb_tools.tool_set({'ns':'CAT','subs':[1,'a'],'value':'1xa'})
pdb_tools.tool_set({'ns':'CAT','subs':[1,'b'],'value':'1xb'})
m4 = MEvaluator(pdb_tools)
m4.eval('S I="" F  S I=$O(^CAT(I)) Q:I=""  S J="" F  S J=$O(^CAT(I,J)) Q:J=""  S ^RES(I,J)=$G(^CAT(I,J))')
r1 = pdb_tools.tool_get({'ns':'RES','subs':[1,'a']})
r2 = pdb_tools.tool_get({'ns':'RES','subs':[1,'b']})
test("Nested ORDER (1,a)", r1.get('value') == '1xa', str(r1))
test("Nested ORDER (1,b)", r2.get('value') == '1xb', str(r2))

# 9. pdb_m_eval tool
r = pdb_tools.tool_m_eval({'expression': '$G(^T(1))'})
test("m_eval GET", r.get('result') == 'hola', str(r))

r = pdb_tools.tool_m_eval({'expression': '$P("x|y|z","|",3)'})
test("m_eval PIECE", r.get('result') == 'z', str(r))

elapsed = time.time() - start
print(f"\n🏁 {elapsed:.1f}s — ALL DONE")
"""

env = os.environ.copy()
env['TMPDIR'] = tempfile.mkdtemp()

result = subprocess.run(
    [sys.executable, '-c', script],
    capture_output=True, text=True, timeout=30,
    env=env, cwd='.'
)

print(result.stdout)
if result.stderr:
    print("STDERR:", result.stderr[:2000])
