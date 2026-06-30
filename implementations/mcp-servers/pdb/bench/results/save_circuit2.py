import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

bench = [
    ('step-3.7-flash-free', 2, 'bugs_found', '5'),
    ('step-3.7-flash-free', 2, 'bug_types', 'missing_cp,missing_telefono,missing_lat,bad_lat,empty_nombre'),
    ('step-3.7-flash-free', 2, 'status', 'done'),
    ('step-3.7-flash-free', 2, 'summary', 'Walked ^FARMA_BUGS with $ORDER+GET. Found 500 missing CP, 500 missing telefono, 4 missing lat, 1 bad lat, 3 empty nombre. No duplicate IDs or city/prov mismatches.'),
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
