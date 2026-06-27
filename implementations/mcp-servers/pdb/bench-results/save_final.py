import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

bench = [
    ('step-3.7-flash-free', 'total', '3'),
    ('step-3.7-flash-free', 'complete', '1'),
]

items = []
for model, key, value in bench:
    items.append({
        'ns': 'BENCH_MODEL_V2',
        'subs': [model, key],
        'value': str(value)
    })

res = pdb_tools.tool_batch_set({'items': items})
print('FINAL_SAVE', res.get('count', 0))
