import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

bench = [
    ('step-3.7-flash-free', 3, 'cp_count', '1'),
    ('step-3.7-flash-free', 3, 'avg_lat', '40.425706'),
    ('step-3.7-flash-free', 3, 'top_street', 'CALLE'),
    ('step-3.7-flash-free', 3, 'max_id', 'MAD-98'),
    ('step-3.7-flash-free', 3, 'status', 'done'),
    ('step-3.7-flash-free', 3, 'summary', 'Optimization circuit used $ORDER traversal via Python bridge over ^FARMACIAS. Computed CP count (1 unique due NULL seed), avg lat 40.425706, top street CALLE (399), max ID MAD-98.'),
]

items = []
for model, circuit, key, value in bench:
    items.append({
        'ns': 'BENCH_MODEL_V2',
        'subs': [model, str(circuit), key],
        'value': str(value)
    })

res = pdb_tools.tool_batch_set({'items': items})
print('BENCH_SAVE', res.get('count', 0))
