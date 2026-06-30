#!/usr/bin/env python3
"""Index ALL ProjectOS .md files — direct pdb_tools import."""
import os, sys, json, time

DB = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb\lumen-pdb.db'
os.environ['PDB_PATH'] = DB
sys.path.insert(0, r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\pdb')
import pdb_tools as PDB

BASE = r'C:\Users\gonzalo\Documents\GitHub\ProjectOS'

# Find files
files = []
for root, dirs, fnames in os.walk(BASE):
    if any(d.startswith('.') or d == 'node_modules' for d in root.split(os.sep)):
        continue
    for fn in fnames:
        if fn.endswith('.md'):
            fp = os.path.join(root, fn)
            sz = os.path.getsize(fp)
            if sz > 100:
                files.append((fp, sz))

print(f'{len(files)} .md files, {sum(s[1] for s in files):,} bytes')

# Import in batches of 200
t0 = time.time()
total = 0
batch = []
for fp, sz in files:
    rel = os.path.relpath(fp, BASE)
    try:
        with open(fp, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
    except:
        content = ''
    batch.append({'ns': 'RAG', 'subs': ['doc', rel], 'value': content[:10000]})
    if len(batch) >= 200:
        PDB.tool_batch_set({'items': batch})
        total += len(batch)
        batch = []
    if total % 600 == 0 and total > 0:
        print(f'  {total}...')
if batch:
    PDB.tool_batch_set({'items': batch})
    total += len(batch)

t1 = time.time()
print(f'{total} docs in {(t1-t0)*1000:.0f}ms ({total/(t1-t0):.0f} docs/s)')

# FTS test
print('FTS tests:')
for q in ['arquitectura', 'API', 'despliegue', 'autenticacion', 'base de datos']:
    t0 = time.time()
    r = PDB.tool_fts_search({'query': q, 'limit': 3})
    print(f'  "{q}": {r.get("count",0)} hits in {(time.time()-t0)*1000:.0f}ms')

sz = os.path.getsize(DB)
print(f'DB: {sz:,} bytes ({sz/1024/1024:.1f} MB)')
print('DONE')
