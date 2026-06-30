"""Extract 500 Madrid pharmacies from farmamap seed SQL to JSON."""
import re, json

farmacias = []
with open('C:/Users/gonzalo/Documents/GitHub/ProjectOS/farmamap-seed-data.sql', 'r', encoding='utf-8') as f:
    for line in f:
        if 'INSERT OR REPLACE INTO farmamap_pharmacies' not in line:
            continue
        m = re.search(r"VALUES\s*\((.+)\);", line)
        if not m:
            continue
        vals_str = m.group(1)

        # Parse CSV-style values handling quoted strings
        parts = []
        cur = ''
        in_sq = False
        for ch in vals_str:
            if ch == "'":
                in_sq = not in_sq
                cur += ch
            elif ch == ',' and not in_sq:
                parts.append(cur.strip())
                cur = ''
            else:
                cur += ch
        if cur.strip():
            parts.append(cur.strip())

        # Clean quotes
        clean = []
        for p in parts:
            p = p.strip()
            if p.startswith("'") and p.endswith("'"):
                p = p[1:-1]
            clean.append(p)

        if len(clean) < 15:
            continue

        try:
            lat = float(clean[11]) if clean[11] != 'NULL' else None
            lon = float(clean[12]) if clean[12] != 'NULL' else None
        except:
            lat, lon = None, None

        farmacias.append({
            'id': clean[0],
            'nombre': clean[1],
            'direccion': clean[2],
            'cp': clean[3],
            'ciudad': clean[4],
            'municipio': clean[5],
            'provincia': clean[7],
            'comunidad': clean[9],
            'latitud': lat,
            'longitud': lon,
            'telefono': clean[14],
        })

print(f'Total farmacias: {len(farmacias)}')

madrid = [f for f in farmacias if f['ciudad'] == 'Madrid']
print(f'Madrid capital: {len(madrid)}')

seed = madrid[:500]
print(f'Seed: {len(seed)} farmacias')
print(f'Rango: {seed[0]["id"]} - {seed[-1]["id"]}')

with open('C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/bench-results/seed_farmacias_madrid.json', 'w', encoding='utf-8') as f:
    json.dump(seed, f, ensure_ascii=False, indent=2)

print('Saved seed_farmacias_madrid.json')
