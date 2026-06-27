"""Compute IVF for all existing embeddings."""
import os, sys, math, json, sqlite3
from collections import defaultdict

BASE = 'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb'
os.chdir(BASE)
sys.path.insert(0, BASE)
import importlib
spec = importlib.util.spec_from_file_location('pdb_tools', BASE + '/pdb_tools.py')
pdb_tools = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb_tools)

DIMS = 384
N_GROUPS = 24

conn = sqlite3.connect('lumen-pdb.db')
c = conn.cursor()

# Read all EMBED rows
c.execute("SELECT subkey, value FROM _globals WHERE ns='EMBED' AND length(subkey) > 18")
rows = c.fetchall()

# Decode subkeys and group by hash
by_hash = defaultdict(dict)
for sk, val in rows:
    try:
        decoded = pdb_tools.decode_subkey(sk)
    except:
        continue
    if len(decoded) >= 2:
        h = str(decoded[0])
        dim = int(decoded[1]) if isinstance(decoded[1], (int, float)) else 0
        try:
            v = float(json.loads(val.decode() if isinstance(val, bytes) else val))
        except:
            try:
                v = float(val.decode() if isinstance(val, bytes) else val)
            except:
                v = 0.0
        by_hash[h][dim] = v

print(f'Vectors: {len(by_hash)}')

# Compute IVF and insert
import time
t0 = time.time()
inserts = []
for h, vals in by_hash.items():
    if len(vals) != DIMS:
        continue
    for g in range(N_GROUPS):
        start = g * 16
        chunk = [vals.get(d, 0.0) for d in range(start, start+16)]
        avg = sum(chunk) / 16.0
        key = pdb_tools.encode_subkey([h, g])
        inserts.append(('EMBED_IVF', key, json.dumps(round(avg, 6))))

print(f'IVF items: {len(inserts)}')
c.executemany('INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)', inserts)
conn.commit()
print(f'Done in {time.time()-t0:.2f}s')
conn.close()
