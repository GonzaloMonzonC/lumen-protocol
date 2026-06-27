"""END-TO-END: Countries API → PDB via M-Light"""
import os, sys, json, tempfile

os.environ["PDB_PATH"] = os.path.join(tempfile.mkdtemp(), "paises.db")
if "pdb_tools" in sys.modules: del sys.modules["pdb_tools"]
if "m_light" in sys.modules: del sys.modules["m_light"]
sys.path.insert(0, ".")
import pdb_tools
from m_light import MEvaluator

paises = json.load(open("paises.json"))
print(f"1. {len(paises)} paises cargados")

# ── INSERT via M-Light ──
m = MEvaluator(pdb_tools)
for p in paises:
    pid = p["id"]
    name = str(p.get("name","")).replace('"',"").replace("'","")
    cap = str(p.get("capital","")).replace('"',"").replace("'","")
    pop = p.get("population",0) or 0
    code = f'S ^P({pid},"name")="{name}" S ^P({pid},"cap")="{cap}" S ^P({pid},"pop")={pop}'
    m.eval(code)
print(f"2. Insertados via M-Light ✅")

# ── VERIFY via $GET ──
print(f"3. Verificando...")
for id in [1, 6, 15, 21, 26]:
    n = m.eval_expr(f'$G(^P({id},"name"))')
    c = m.eval_expr(f'$G(^P({id},"cap"))')
    print(f"   {id}: {n} ({c})")

# ── $ORDER traversal ──
print(f"\n4. $ORDER traversal...")
I = ""
names = []
while True:
    r = pdb_tools.tool_order({"ns": "P", "subs": [I]})
    if not r.get("value"): break
    I = r["value"]
    n = pdb_tools.tool_get({"ns": "P", "subs": [I, "name"]}).get("value","?")
    names.append(n)
print(f"   {len(names)} paises en PDB")
print(f"   Primeros: {', '.join(names[:5])}")
print(f"   Ultimos: {', '.join(names[-3:])}")

# ── Population query ──
print(f"\n5. Paises con poblacion > 50M...")
I = ""
count_pop = 0
while True:
    r = pdb_tools.tool_order({"ns": "P", "subs": [I]})
    if not r.get("value"): break
    I = r["value"]
    pop = pdb_tools.tool_get({"ns": "P", "subs": [I, "pop"]}).get("value",0)
    name = pdb_tools.tool_get({"ns": "P", "subs": [I, "name"]}).get("value","?")
    if pop and pop > 50000000:
        print(f"   {name}: {pop:,}")
        count_pop += 1
print(f"   Total >50M: {count_pop}")

# ── M-Light F loop pure ──
print(f"\n6. F loop M-Light recorriendo $ORDER puro...")
m2 = MEvaluator(pdb_tools)
m2.eval('S I="" F  S I=$O(^P(I)) Q:I=""  S N=$G(^P(I,"name"))')
print(f"   Loop completado OK")

total = len(names)
print(f"\n🏁 {total} paises en ^P via M-Light. Todo OK.")
