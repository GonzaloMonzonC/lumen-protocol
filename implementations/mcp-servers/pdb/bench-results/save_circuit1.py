import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

bench = [
    ('step-3.7-flash-free', 1, 'status', 'done'),
    ('step-3.7-flash-free', 1, 'global_name', 'FARMACIAS'),
    ('step-3.7-flash-free', 1, 'count', '500'),
    ('step-3.7-flash-free', 1, 'subscript_structure', '^FARMACIAS(id, campo)'),
    ('step-3.7-flash-free', 1, 'summary', 'Flat global by pharmacy ID with field subscript. Supports O(1) lookup by ID, direct city/cp/provincia queries via field access.'),
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
