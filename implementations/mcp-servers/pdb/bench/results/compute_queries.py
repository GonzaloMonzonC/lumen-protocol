import os, sys, json
from collections import Counter

workdir = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb'
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

# Walk FARMA and collect all data
records = {}
key = ''
while True:
    r = pdb_tools.tool_order({'ns': 'FARMA', 'subs': [key]})
    if not r.get('value'):
        break
    key = r['value']
    rec = {}
    for field in ['id', 'nombre', 'direccion', 'cp', 'ciudad', 'municipio', 'provincia', 'comunidad', 'latitud', 'longitud', 'telefono']:
        r2 = pdb_tools.tool_get({'ns': 'FARMA', 'subs': [key, field]})
        rec[field] = r2.get('value', '') if r2.get('found', False) else ''
    records[key] = rec

print(f"Records loaded: {len(records)}")

# Query 1: Count pharmacies by postal code
cp_counts = Counter()
for rec in records.values():
    cp = rec.get('cp', 'NULL')
    if cp == 'NULL' or cp == '':
        cp = 'NULL'
    cp_counts[cp] += 1

print("\n=== Query 1: Pharmacies by Postal Code ===")
for cp, count in sorted(cp_counts.items()):
    print(f"  CP {cp}: {count}")

# Query 2: Average latitude
lats = []
for rec in records.values():
    lat = rec.get('latitud', '')
    if lat and lat != 'NULL' and lat != '':
        try:
            lats.append(float(lat))
        except (ValueError, TypeError):
            pass

avg_lat = sum(lats) / len(lats) if lats else 0
print(f"\n=== Query 2: Average Latitude ===")
print(f"  Valid latitudes: {len(lats)}")
print(f"  Average: {avg_lat:.4f}")

# Query 3: Top 3 most common street types
# Parse the direccion field: first word is the street type
street_types = Counter()
for rec in records.values():
    direccion = rec.get('direccion', '')
    if direccion:
        # Get first word (street type)
        first_word = direccion.split()[0] if direccion.split() else ''
        # Normalize common variants
        first_word = first_word.upper().rstrip(',.')
        if first_word in ('CALLE', 'AVDA', 'AVENIDA', 'AV.'):
            street_types['CALLE'] += 1
        elif first_word in ('PLAZA', 'PZA', 'PZ'):
            street_types['PLAZA'] += 1
        elif first_word in ('PASEO', 'Pº', 'P.'):
            street_types['PASEO'] += 1
        elif first_word in ('CARRETERA', 'CTRA', 'CRTA'):
            street_types['CARRETERA'] += 1
        elif first_word in ('RONDA', 'RDA'):
            street_types['RONDA'] += 1
        elif first_word in ('TRAVESÍA', 'TRAVESIA', 'TRV'):
            street_types['TRAVESIA'] += 1
        elif first_word in ('GLORIETA', 'GTA'):
            street_types['GLORIETA'] += 1
        elif first_word in ('CAMINO', 'CMNO'):
            street_types['CAMINO'] += 1
        elif first_word in ('COSTANILLA',):
            street_types['COSTANILLA'] += 1
        else:
            street_types[first_word] += 1

print(f"\n=== Query 3: Top Street Types ===")
for stype, count in street_types.most_common(10):
    print(f"  {stype}: {count}")

# Query 4: Pharmacy with highest ID number
# Parse numeric suffix from MAD-XXX
max_num = 0
max_id = ''
for rid in records:
    parts = rid.split('-')
    if len(parts) == 2:
        try:
            num = int(parts[1])
            if num > max_num:
                max_num = num
                max_id = rid
        except ValueError:
            pass

print(f"\n=== Query 4: Highest ID Number ===")
print(f"  Max ID: {max_id} (numeric: {max_num})")

# Final summary
print(f"\n=== CIRCUIT 3 SUMMARY ===")
print(f"CP count (unique): {len(cp_counts)}")
print(f"Avg latitude: {avg_lat:.4f}")
top3 = street_types.most_common(3)
print(f"Top street: {top3[0][0]} ({top3[0][1]})")
print(f"2nd: {top3[1][0]} ({top3[1][1]})" if len(top3) > 1 else "2nd: N/A")
print(f"3rd: {top3[2][0]} ({top3[2][1]})" if len(top3) > 2 else "3rd: N/A")
print(f"Max ID: {max_id}")
