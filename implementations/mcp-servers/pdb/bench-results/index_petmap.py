"""Parse petmap SQL, generate texts, embed into PDB in batches."""
import os, sys, re, json, time
from pathlib import Path

# Setup pdb_tools — script runs from pdb/bench-results/
script_dir = Path(__file__).resolve().parent  # bench-results/
pdb_dir = script_dir.parent  # pdb/
sys.path.insert(0, str(pdb_dir))
os.chdir(str(pdb_dir))

import importlib
spec = importlib.util.spec_from_file_location('pdb_tools', str(pdb_dir / 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

# ── Parse SQL ──
sql_path = Path.home() / 'Documents/GitHub/ProjectOS/petmap-seed-osm.sql'
texts = []
places = []

with open(sql_path, 'r', encoding='utf-8') as f:
    for line in f:
        if not line.startswith('INSERT'):
            continue
        idx = line.find('VALUES (')
        if idx < 0:
            continue
        raw = line[idx + 8:]
        # Find matching closing paren
        depth = 0
        end = 0
        for i, ch in enumerate(raw):
            if ch == '(':
                depth += 1
            elif ch == ')':
                if depth == 0:
                    end = i
                    break
                depth -= 1
        
        vals_str = raw[:end]
        # Parse: 'strings' or NULL or numbers (including decimals and negative)
        pattern = r"'((?:[^']|'')*)'|([A-Za-z_][A-Za-z0-9._]*)|(-?\d+\.?\d*)"
        matches = re.findall(pattern, vals_str)
        vals = []
        for q, null_val, num in matches:
            if q is not None:
                vals.append(q)
            elif null_val is not None and null_val.upper() == 'NULL':
                vals.append('')
            elif num is not None and num != '':
                vals.append(num)
            else:
                vals.append('')
        
        if len(vals) < 20:
            continue
        
        pid = vals[0]
        name = vals[1] or 'Sin nombre'
        ptype = vals[3] if len(vals) > 3 else ''
        address = vals[4] if len(vals) > 4 else ''
        municipality = vals[5] if len(vals) > 5 else ''
        province = vals[7] if len(vals) > 7 else ''
        community = vals[9] if len(vals) > 9 else ''
        lat = vals[12] if len(vals) > 12 else ''
        lon = vals[13] if len(vals) > 13 else ''
        phone = vals[15] if len(vals) > 15 else ''
        species_raw = vals[19] if len(vals) > 19 else ''
        
        if ptype != 'veterinary':
            continue
        
        species = species_raw.replace('["','').replace('"]','').replace('"','').replace(',', ', ')
        loc_parts = [p for p in [municipality, province, community] if p]
        location = ', '.join(loc_parts) if loc_parts else 'España'
        extras = []
        if phone: extras.append(f'Tel: {phone}')
        if address: extras.append(address)
        extra_str = ' | ' + ' '.join(extras) if extras else ''
        
        text = f'{name} en {location}. Atiende: {species}.{extra_str}'
        places.append({
            'id': pid, 'name': name, 'type': ptype,
            'municipality': municipality, 'province': province,
            'community': community, 'lat': lat, 'lon': lon,
            'phone': phone, 'species': species, 'text': text
        })
        texts.append(text)

print(f'Total veterinarias: {len(texts)}')
print(f'Ejemplo: {texts[0][:120]}')
print(f'Ejemplo 2: {texts[3][:120]}')

# ── Embed in batches ──
BATCH = 50
total = len(texts)
for i in range(0, total, BATCH):
    batch = texts[i:i+BATCH]
    batch_places = places[i:i+BATCH]
    print(f'Embedding lote {i//BATCH+1}/{(total+BATCH-1)//BATCH} ({len(batch)} textos)...')
    try:
        r = pdb_tools.tool_embed({'texts': batch, 'source': 'petmap'})
        print(f'  → {r.get("count", 0)} embeddings generados')
    except Exception as e:
        print(f'  ✗ Error: {e}')
    time.sleep(0.05)

print('\n✅ Indexación completada.')
print(f'Total embeddings en ^EMBED: {len(texts)}')
