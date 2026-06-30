"""Debug M-Light IF inside FOR loop"""
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

# Test 1: Simple IF with inline command
print("=== Test 1: IF inline simple ===")
m2 = MEvaluator(pdb_tools)
m2.eval('S X=10 I X>5 W "X es mayor que 5",!')
print("---")

# Test 2: FOR loop with IF and inline W
print("=== Test 2: FOR + IF inline ===")
m3 = MEvaluator(pdb_tools)
m3.eval('S p="" F  S p=$O(^P(p)) Q:p=""  I ^(p,"pop")>50000000 W $G(^P(p,"name")),!')
print("---")
print("DONE")
