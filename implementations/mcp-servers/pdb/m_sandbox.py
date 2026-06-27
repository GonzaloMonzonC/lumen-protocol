"""M-Light Sandbox — Pruebas con sintaxis M real."""
import sys, os, tempfile

def test(name, m_code, check_fn):
    try:
        encoder = MEvaluator(pdb_tools)
        if m_code:
            encoder.eval(m_code)
        result = check_fn(encoder, pdb_tools)
        if isinstance(result, tuple):
            ok, detail = result
        else:
            ok, detail = result, ""
        if ok:
            passed.append(1)
            print(f"  ✅ {name}")
        else:
            failed.append(1)
            print(f"  ❌ {name} — {detail}")
    except Exception as e:
        failed.append(1)
        print(f"  ❌ {name} — EXCEPTION: {e}")

tmpdir = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(tmpdir, 'sandbox.db')
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pdb_tools
from m_light import MEvaluator

passed, failed = [], []

# 1
test("SET global", 'S ^P(1,"n")="Juan"',
     lambda e,p: (p.tool_get({"ns":"P","subs":[1,"n"]})["value"]=="Juan", ""))
# 2
test("$G abreviatura", 'S ^P2(1)="ok" S X=$G(^P2(1))',
     lambda e,p: (e.scope.get("X")=="ok", ""))
# 3
test("$O traversal", 'S ^T("a")=1 S ^T("b")=1 S ^T("c")=1 S N="" F  S N=$O(^T(N)) Q:N=""  S ^R(N)=N',
     lambda e,p: (p.tool_get({"ns":"R","subs":["c"]})["value"]=="c", ""))
# 4
test("FOR rango", 'F I=1:1:5 S ^Q(I)=I*10',
     lambda e,p: (all(p.tool_get({"ns":"Q","subs":[i]})["value"]==i*10 for i in range(1,6)), ""))
# 5
test("$DATA", 'S ^D(1)="x" S A=$D(^D(1)) S B=$D(^D(999))',
     lambda e,p: (e.scope.get("A") in (1,11) and e.scope.get("B")==0, ""))
# 6
test("$PIECE", 'S X=$P("a|b|c","|",2)',
     lambda e,p: (e.scope.get("X")=="b", ""))
# 7
test("$EXTRACT \$E", 'S X=$E("MUMPS",1,3)',
     lambda e,p: (e.scope.get("X")=="MUM", f"got {e.scope.get('X')}"))
# 8
test("$SELECT \$S", 'S X=$S(0=1:"a",1=1:"b",1:"c")',
     lambda e,p: (e.scope.get("X")=="b", f"got {e.scope.get('X')}"))
# 9
test("KILL", 'S ^K(1)="a" S ^K(2)="b" K ^K(1)',
     lambda e,p: (p.tool_get({"ns":"K","subs":[2]})["value"]=="b", ""))
# 10
test("IF bloque", 'S X=5 IF X=5 { S ^IF1("ok")=1 }',
     lambda e,p: (p.tool_get({"ns":"IF1","subs":["ok"]})["value"]==1, ""))
# 11
test("IF falso", 'S X=3 IF X=5 { S ^IF2("f")=1 }',
     lambda e,p: (not p.tool_get({"ns":"IF2","subs":["f"]}).get("found"), ""))
# 12
test("Q condicional", 'S ^N("ana")=1 S ^N("pepe")=1 S ^N("zoe")=1 S N="" F  S N=$O(^N(N)) Q:N=""  Q:N="pepe"',
     lambda e,p: (e.scope.get("N")=="pepe", f"N={e.scope.get('N')!r}"))
# 13
test("Multiples comandos", 'S A=1 S B=2 S C=3',
     lambda e,p: (e.scope.get("A")==1 and e.scope.get("B")==2 and e.scope.get("C")==3, ""))
# 14
test("Patron hospital", 'S ^HC("PAT",42,"name")="Gonzalo"',
     lambda e,p: (p.tool_get({"ns":"HC","subs":["PAT",42,"name"]})["value"]=="Gonzalo", ""))
# 15
test("$O anidado", 'S ^M(1,"a")="x" S ^M(1,"b")="y" S I="" F  S I=$O(^M(I)) Q:I=""  S J="" F  S J=$O(^M(I,J)) Q:J=""  S ^CP(I,J)=$G(^M(I,J))',
     lambda e,p: (p.tool_get({"ns":"CP","subs":[1,"a"]})["value"]=="x", ""))
# 16
test("Q:var directo", 'S ^Z(1)="ok" S N="" F  S N=$O(^Z(N)) Q:N=""  S X=N',
     lambda e,p: (e.scope.get("X")==1, f"X={e.scope.get('X')}"))
# 17
test("\$GET default", 'S X=$G(^NOEXISTE("x"))',
     lambda e,p: (e.scope.get("X") is None, ""))
# 18
test("REPL multilinea", '',
     lambda e,p: (p.tool_m_repl({"code": "S ^RL(1)=42\nS ^RL(2)=84"})["success"], ""))
# 19
test("DBFIX", '',
     lambda e,p: (p.tool_dbfix({})["report"]["integrity"]["ok"], ""))
# 20
test("FOR infinito Q", 'S ^INF("a")=1 S N="" F  S N=$O(^INF(N)) Q:N=""',
     lambda e,p: (e.scope.get("N")=="", ""))

print(f"\n📊 {len(passed)}/{len(passed)+len(failed)} tests passed")
if not failed:
    print("🎯 ¡M-Light entiende MUMPS real!")

pdb_tools._conn.close()
try: os.unlink(os.environ['PDB_PATH']); os.rmdir(tmpdir)
except: pass
