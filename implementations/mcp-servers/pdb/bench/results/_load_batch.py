"""Load 500 pharmacies into ^FARMA via pdb_tools direct."""
import os, sys, json
workdir = os.path.abspath('C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)
import importlib
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

with open(os.path.join(workdir, 'bench-results', 'seed_farmacias_batch_500.json'), 'r', encoding='utf-8') as f:
    batch = json.load(f)

# Load in chunks
chunk_size = 500
for i in range(0, len(batch), chunk_size):
    chunk = batch[i:i+chunk_size]
    # Change ns from FARMA to FARMA
    for item in chunk:
        item['ns'] = 'FARMA'
    result = pdb_tools.tool_batch_set({'items': chunk})
    print(f'Chunk {i//chunk_size + 1}: {result.get("count", 0)} items')

# Verify
count = 0
I = ''
while True:
    r = pdb_tools.tool_order({'ns': 'FARMA', 'subs': [I]})
    if not r.get('value'): break
    I = r['value']
    count += 1
    if count <= 3:
        name = pdb_tools.tool_get({'ns': 'FARMA', 'subs': [I, 'nombre']})
        print(f'  {I}: {name.get("value", "?")}')

print(f'\nTotal IDs in ^FARMA: {count}')
