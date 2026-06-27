"""M-Light standalone test — ejecutar con: python test_m_light_standalone.py"""
import sys, os, tempfile

# Crear DB temporal
tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 'mlight.db')

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdb_tools
from m_light import MEvaluator

passed = 0

def check(desc, condition, detail=""):
    global passed
    if condition:
        passed += 1
        print(f"  ✅ {desc}")
    else:
        print(f"  ❌ {desc} — {detail}")

# ── 1. SET/GET básico ──
pdb_tools.tool_set({'ns': 't1', 'subs': ['x'], 'value': 42})
v = pdb_tools.tool_get({'ns': 't1', 'subs': ['x']})['value']
check("SET/GET básico", v == 42, str(v))

# ── 2. $ORDER traversal ──
for name in ['ana', 'juan', 'pepe', 'zoe']:
    pdb_tools.tool_set({'ns': 'n2', 'subs': [name], 'value': 1})
m = MEvaluator(pdb_tools)
m.eval('S N="" F  S N=$O(^n2(N)) Q:N=""')
check("$ORDER recorre todo", m.scope.get('N') == '', f"N={m.scope.get('N')!r}")

# ── 3. Buscar elemento con Q condicional ──
m2 = MEvaluator(pdb_tools)
m2.eval('S N="" F  S N=$O(^n2(N)) Q:N=""  Q:N="pepe"')
check("Q condicional encuentra pepe", m2.scope.get('N') == 'pepe', f"N={m2.scope.get('N')!r}")

# ── 4. Q:N="" funciona (find non-existent) ──
m3 = MEvaluator(pdb_tools)
m3.eval('S N="" F  S N=$O(^n2(N)) Q:N=""  Q:N="zzz"')
check("Q:N=\"\" sale al final", m3.scope.get('N') == '', f"N={m3.scope.get('N')!r}")

# ── 5. $ORDER con dirección -1 ──
o = pdb_tools.tool_order({'ns': 'n2', 'subs': [''], 'direction': -1})
check("$ORDER dir=-1 (último)", o['value'] == 'zoe', str(o))

# ── 6. Nested $ORDER ──
for i in range(1, 3):
    for j in ['a', 'b']:
        pdb_tools.tool_set({'ns': 'n6', 'subs': [i, j], 'value': f'{i}x{j}'})
m4 = MEvaluator(pdb_tools)
m4.eval('S I="" F  S I=$O(^n6(I)) Q:I=""  S J="" F  S J=$O(^n6(I,J)) Q:J=""  S ^c6(I,J)=$GET(^n6(I,J))')
for i in range(1, 3):
    for j in ['a', 'b']:
        v = pdb_tools.tool_get({'ns': 'c6', 'subs': [i, j]})['value']
        check(f"Nested ORDER ({i},{j})", v == f'{i}x{j}', str(v))

# ── 7. $PIECE ──
m5 = MEvaluator(pdb_tools)
v = m5.eval_expr('$PIECE("a|b|c","|",2)')
check("$PIECE", v == 'b', str(v))

# ── 8. $EXTRACT ──
v = m5.eval_expr('$EXTRACT("Hermes",1,3)')
check("$EXTRACT", v == 'Her', str(v))

# ── 9. $SELECT ──
v = m5.eval_expr('$SELECT(1=1:"yes",1:"no")')
check("$SELECT", v == 'yes', str(v))
v = m5.eval_expr('$SELECT(0=1:"nope",1:"default")')
check("$SELECT default", v == 'default', str(v))

# ── 10. IF ──
m6 = MEvaluator(pdb_tools)
m6.eval('S X=5 IF X=5 { S ^c7("ok")=1 }')
v = pdb_tools.tool_get({'ns': 'c7', 'subs': ['ok']})['value']
check("IF verdadero", v == 1, str(v))
m6b = MEvaluator(pdb_tools)
m6b.eval('S X=3 IF X=5 { S ^c7("fail")=1 }')
r = pdb_tools.tool_get({'ns': 'c7', 'subs': ['fail']})
check("IF falso no ejecuta", r.get('found') == False, str(r))

# ── 11. KILL ──
pdb_tools.tool_set({'ns': 'k', 'subs': [1], 'value': 'a'})
pdb_tools.tool_set({'ns': 'k', 'subs': [2], 'value': 'b'})
m7 = MEvaluator(pdb_tools)
m7.eval('K ^k(1)')
v1 = pdb_tools.tool_get({'ns': 'k', 'subs': [1]}).get('found')
v2 = pdb_tools.tool_get({'ns': 'k', 'subs': [2]})['value']
check("KILL elimina", v1 == False)
check("KILL no daña otros", v2 == 'b')

# ── 12. $DATA ──
pdb_tools.tool_set({'ns': 'd', 'subs': [1], 'value': 'x'})
r = pdb_tools.tool_data({'ns': 'd', 'subs': [1]})
check("$DATA existe", r['value'] in (1, 11), str(r))
r = pdb_tools.tool_data({'ns': 'd', 'subs': [999]})
check("$DATA no existe", r['value'] == 0, str(r))

# ── 13. Combinación clásica M ──
m8 = MEvaluator(pdb_tools)
m8.eval('S N="" F  S N=$O(^n2(N)) Q:N=""  I $E(N,1)="j" S ^c8(N)=N')
v = pdb_tools.tool_get({'ns': 'c8', 'subs': ['juan']})['value']
check("Filtro con \$E (nombres que empiezan con j)", v == 'juan', str(v))

# ── Resultados ──
print(f"\n📊 {passed}/13 tests passed")
if passed == 13:
    print("🎉 M-Light funciona correctamente!")

# Cleanup
pdb_tools._conn.close()
os.unlink(os.environ['PDB_PATH'])
os.rmdir(tmpdir)
