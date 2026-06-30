"""Generate corrupted seed for debugging circuit."""
import json, copy, random

with open('bench-results/seed_farmacias_madrid.json', encoding='utf-8') as f:
    clean = json.load(f)

random.seed(42)
corrupt = copy.deepcopy(clean)

# Error 1: 5 registros con latitud None
for i in range(5):
    corrupt[i]['latitud'] = None

# Error 2: 3 registros con nombre vacío
for i in range(5, 8):
    corrupt[i]['nombre'] = ''

# Error 3: 2 registros con ciudad incoherente (fuera de Madrid)
corrupt[10]['ciudad'] = 'Barcelona'
corrupt[10]['provincia'] = 'Barcelona'
corrupt[11]['ciudad'] = 'Valencia'
corrupt[11]['provincia'] = 'Valencia'

# Error 4: 1 registro con latitud string en vez de número
corrupt[15]['latitud'] = 'cuarenta grados'

# Error 5: 1 registro con telefono = None
corrupt[20]['telefono'] = None

# Error 6: 2 IDs duplicados
corrupt[25]['id'] = corrupt[0]['id']

# Also save as batch-ready format for PDB
# Each record becomes: pdb_set ^FARMA(id, campo) = valor
batch_items = []
for f in corrupt:
    for k, v in f.items():
        batch_items.append({
            'ns': 'FARMA_BUGS',
            'subs': [f['id'], k],
            'value': str(v) if v is not None else ''
        })

with open('bench-results/seed_farmacias_clean.json', 'w', encoding='utf-8') as f:
    json.dump(clean, f, ensure_ascii=False, indent=2)

with open('bench-results/seed_farmacias_bugs.json', 'w', encoding='utf-8') as f:
    # Save just the corrupted records for judge
    bug_report = {
        'total': len(corrupt),
        'errors_planted': {
            'lat_null': {'indices': [0,1,2,3,4], 'desc': '5 registros con latitud=None'},
            'nombre_vacio': {'indices': [5,6,7], 'desc': '3 registros con nombre=""'},
            'ciudad_out': {'indices': [10,11], 'desc': '2 registros con ciudad fuera de Madrid'},
            'lat_string': {'indices': [15], 'desc': '1 registro con latitud string'},
            'telefono_null': {'indices': [20], 'desc': '1 registro con telefono=None'},
            'id_duplicado': {'indices': [25], 'desc': '1 registro con ID duplicado'},
        }
    }
    json.dump(bug_report, f, ensure_ascii=False, indent=2)

# Also create the batch_set for loading into PDB
with open('bench-results/seed_farmacias_batch_clean.json', 'w', encoding='utf-8') as f:
    clean_items = []
    for f_item in clean[:50]:  # C1 uses 50
        for k, v in f_item.items():
            clean_items.append({
                'ns': 'FARMA',
                'subs': [f_item['id'], k],
                'value': str(v) if v is not None else ''
            })
    json.dump(clean_items, f, ensure_ascii=False, indent=2)

with open('bench-results/seed_farmacias_batch_500.json', 'w', encoding='utf-8') as f:
    clean_items_500 = []
    for f_item in clean:  # C3 uses 500
        for k, v in f_item.items():
            clean_items_500.append({
                'ns': 'FARMA',
                'subs': [f_item['id'], k],
                'value': str(v) if v is not None else ''
            })
    json.dump(clean_items_500, f, ensure_ascii=False, indent=2)

print(f'Clean seed: {len(clean)} farmacias')
print(f'Errors planted: 6 tipos, ~14 registros afectados')
print(f'Batch files created for C1 (50) and C3 (500)')
