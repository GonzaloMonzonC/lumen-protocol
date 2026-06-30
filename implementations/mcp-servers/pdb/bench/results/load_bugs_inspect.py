import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

seed_path = os.path.join(workdir, 'bench-results', 'seed_farmacias_batch_bugs.json')
with open(seed_path, encoding='utf-8') as f:
    records = json.load(f)

# Format is the same flat batch as FARMA_BUGS(id, campo)=valor
# but we need to confirm structure. Let's inspect first record.
print('RECORDS', len(records))
print('FIRST', json.dumps(records[0], ensure_ascii=False)[:500])
