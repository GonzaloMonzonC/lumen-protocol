"""Debug M-Light F loop"""
import os, sys, json, tempfile, time

paises = json.load(open('paises.json'))
d = tempfile.mkdtemp()
os.environ['PDB_PATH'] = os.path.join(d, 'g.db')
sys.path.insert(0, '.')
import pdb_tools
from m_light import MEvaluator

m = MEvaluator(pdb_tools)
for p in paises:
    pid = int(p['id'])
    name = str(p.get('name','')).replace('"','')
    cap = str(p.get('capital','')).replace('"','')
    pop = int(p.get('population',0) or 0)
    m.eval(f'S ^P({pid},"name")="{name}" S ^P({pid},"cap")="{cap}" S ^P({pid},"pop")={pop}')
print(f"Cargados {len(paises)} paises")

# Test ORDER
r = pdb_tools.tool_order({"ns": "P", "subs": [""]})
print(f"ORDER first: {r}")

# Test F loop prints
m2 = MEvaluator(pdb_tools)
t0 = time.perf_counter()
m2.eval('S p="" F  S p=$O(^P(p)) Q:p=""  W $G(^P(p,"name")),!')
t = time.perf_counter() - t0
print(f"---")
print(f"Tiempo F loop: {t*1000:.2f} ms")
print("DONE")
