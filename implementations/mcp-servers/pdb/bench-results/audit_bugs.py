import os, sys, json

workdir = os.path.abspath('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb')
sys.path.insert(0, workdir)

import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', os.path.join(workdir, 'pdb_tools.py'))
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

I = ''
records = {}
while True:
    rid = pdb_tools.tool_order({'ns': 'FARMA_BUGS', 'subs': [I]}).get('value')
    if not rid:
        break
    rec = {'id': rid}
    for campo in ['nombre','direccion','cp','ciudad','municipio','provincia','comunidad','latitud','longitud','telefono']:
        v = pdb_tools.tool_get({'ns': 'FARMA_BUGS', 'subs': [rid, campo]}).get('value')
        rec[campo] = v if v is not None else ''
    records[rid] = rec
    I = rid

print('TOTAL_RECORDS', len(records))

missing_cp = 0
missing_tel = 0
missing_lat = 0
missing_lon = 0
bad_lat = 0
bad_lon = 0
mismatch_city_prov = 0
duplicate_ids = 0
null_id = 0
empty_nombre = 0

seen = {}
for rid, rec in records.items():
    if not rec['id'] or rec['id'] == 'NULL':
        null_id += 1
    if not rec['nombre']:
        empty_nombre += 1
    if not rec['cp'] or rec['cp'] == 'NULL' or rec['cp'] == '':
        missing_cp += 1
    if not rec['telefono'] or rec['telefono'] == 'NULL' or rec['telefono'] == '':
        missing_tel += 1
    lat = rec.get('latitud')
    lon = rec.get('longitud')
    if lat == '' or lat is None:
        missing_lat += 1
    else:
        try:
            lat_f = float(lat)
            if lat_f < -90 or lat_f > 90:
                bad_lat += 1
        except Exception:
            bad_lat += 1
    if lon == '' or lon is None:
        missing_lon += 1
    else:
        try:
            lon_f = float(lon)
            if lon_f < -180 or lon_f > 180:
                bad_lon += 1
        except Exception:
            bad_lon += 1
    if rec.get('ciudad') and rec.get('provincia') and rec['ciudad'] != rec['provincia']:
        mismatch_city_prov += 1
    seen.setdefault(rec['id'], 0)
    seen[rec['id']] += 1

for k, v in seen.items():
    if v > 1:
        duplicate_ids += 1

out = {
    'missing_cp': missing_cp,
    'missing_telefono': missing_tel,
    'missing_lat': missing_lat,
    'missing_lon': missing_lon,
    'bad_lat': bad_lat,
    'bad_lon': bad_lon,
    'mismatch_city_prov': mismatch_city_prov,
    'duplicate_ids': duplicate_ids,
    'null_id': null_id,
    'empty_nombre': empty_nombre,
}
print(json.dumps(out, ensure_ascii=False))
