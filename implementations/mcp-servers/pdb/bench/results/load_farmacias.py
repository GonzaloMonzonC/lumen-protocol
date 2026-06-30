import json, sys
sys.path.insert(0, r'Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb')
from pdb_bridge import PDBBridge

bridge = PDBBridge()
seed_path = r'Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb\bench-results\seed_farmacias_madrid.json'
with open(seed_path, encoding='utf-8') as f:
    records = json.load(f)

items = []
for r in records:
    valor = '|'.join([
        r.get('nombre',''),
        r.get('direccion',''),
        str(r.get('latitud','')),
        str(r.get('longitud','')),
        r.get('telefono','')
    ])
    items.append({
        'ns': 'FARMACIAS',
        'subs': [
            r.get('provincia',''),
            r.get('ciudad',''),
            r.get('cp',''),
            r.get('id',''),
            'campo'
        ],
        'value': valor
    })

# batch in chunks of 100
for i in range(0, len(items), 100):
    res = bridge.batch_set(items[i:i+100])
    print('chunk', i, '->', res.get('success'))

print('loaded', len(items))
