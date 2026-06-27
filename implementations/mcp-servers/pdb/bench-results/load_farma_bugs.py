import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

seed_path = os.path.join(workdir, 'bench-results', 'seed_farmacias_batch_bugs.json')
with open(seed_path, encoding='utf-8') as f:
    items = json.load(f)

loaded = 0
for i in range(0, len(items), 500):
    chunk = items[i:i+500]
    for it in chunk:
        it['ns'] = 'FARMA_BUGS'
    res = pdb_tools.tool_batch_set({'items': chunk})
    loaded += res.get('count', 0)
    print(f'chunk {i//500 + 1}: {res.get("count", 0)}')

print('TOTAL_LOADED_BUGS', loaded)

I = ''
count = 0
while True:
    r = pdb_tools.tool_order({'ns': 'FARMA_BUGS', 'subs': [I]})
    if not r.get('value'):
        break
    I = r['value']
    count += 1
print('TOTAL_IDS_BUGS', count)
