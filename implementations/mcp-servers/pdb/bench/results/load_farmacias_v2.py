import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

seed_path = os.path.join(workdir, 'bench-results', 'seed_farmacias_madrid.json')
with open(seed_path, encoding='utf-8') as f:
    records = json.load(f)

# Build flat format: ^FARMACIAS(id, campo)=valor
items = []
for r in records:
    base = r.get('id', '')
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'id'], 'value': base})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'nombre'], 'value': r.get('nombre', '')})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'direccion'], 'value': r.get('direccion', '')})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'cp'], 'value': str(r.get('cp', ''))})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'ciudad'], 'value': r.get('ciudad', '')})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'municipio'], 'value': r.get('municipio', '')})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'provincia'], 'value': r.get('provincia', '')})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'comunidad'], 'value': r.get('comunidad', '')})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'latitud'], 'value': str(r.get('latitud', ''))})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'longitud'], 'value': str(r.get('longitud', ''))})
    items.append({'ns': 'FARMACIAS', 'subs': [base, 'telefono'], 'value': str(r.get('telefono', ''))})

# Batch insert in chunks
loaded = 0
for i in range(0, len(items), 500):
    chunk = items[i:i+500]
    res = pdb_tools.tool_batch_set({'items': chunk})
    loaded += res.get('count', 0)
    print(f'chunk {i//500 + 1}: {res.get("count", 0)} items')

# Verify at least 500 IDs
I = ''
count = 0
while True:
    r = pdb_tools.tool_order({'ns': 'FARMACIAS', 'subs': [I]})
    if not r.get('value'):
        break
    I = r['value']
    count += 1

print('TOTAL_IDS', count)
print('TOTAL_ITEMS', loaded)
