import os, sys, json
from collections import Counter

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

I = ''
records = {}
while True:
    rid = pdb_tools.tool_order({'ns': 'FARMACIAS', 'subs': [I]}).get('value')
    if not rid:
        break
    rec = {
        'id': rid,
        'cp': pdb_tools.tool_get({'ns': 'FARMACIAS', 'subs': [rid, 'cp']}).get('value', ''),
        'latitud': pdb_tools.tool_get({'ns': 'FARMACIAS', 'subs': [rid, 'latitud']}).get('value', ''),
        'direccion': pdb_tools.tool_get({'ns': 'FARMACIAS', 'subs': [rid, 'direccion']}).get('value', ''),
    }
    records[rid] = rec
    I = rid

print('RECORDS', len(records))

# 1) Count by CP
cp_counts = Counter(rec['cp'] for rec in records.values() if rec['cp'])
print('UNIQUE_CP', len(cp_counts))
print('TOP_CP', cp_counts.most_common(5))

# 2) Average lat
lats = []
for rec in records.values():
    try:
        lats.append(float(rec['latitud']))
    except Exception:
        pass
avg_lat = round(sum(lats)/len(lats), 6) if lats else ''
print('AVG_LAT', avg_lat)

# 3) Top 3 street types parse first token before space/comma
street_types = []
for rec in records.values():
    addr = rec['direccion'] or ''
    token = addr.split()[0] if addr.split() else ''
    if token:
        street_types.append(token.upper())
street_counts = Counter(street_types)
print('TOP_STREET', street_counts.most_common(3))

# 4) Max ID
ids = [rid for rid in records.keys()]
max_id = max(ids) if ids else ''
print('MAX_ID', max_id)
