"""Ronda 1: Codigo M de Gonzalo vs Python"""
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

# ── GONZALO: M-Light con naked reference ──
codigo = 'F  S p=$O(^P(p)) Q:p="" I ^(p,"pop")>50000000 W $G(^P(p,"name")),": ",^(p,"pop"),!'
print(f"\n--- GONZALO (M-Light) ---")
print(f"Codigo: {codigo}")
t0 = time.perf_counter()
m2 = MEvaluator(pdb_tools)
m2.eval(codigo)
t_m = (time.perf_counter() - t0) * 1000

# ── HERMES: Python puro ──
print(f"\n--- HERMES (Python) ---")
t0 = time.perf_counter()
for p in paises:
    pop = p.get('population', 0) or 0
    if pop > 50000000:
        print(f"  {p['name']}: {pop:,}")
t_py = (time.perf_counter() - t0) * 1000

print(f"\n{'='*40}")
print(f"RESULTADO:")
print(f"  M-Light: {t_m:.2f} ms")
print(f"  Python:  {t_py:.2f} ms")
ratio = t_m / t_py if t_py > 0 else float('inf')
print(f"  Ratio:   {ratio:.1f}x")
print(f"{'='*40}")
