import sqlite3, json
conn = sqlite3.connect('Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/lumen-pdb.db')
c = conn.cursor()
c.execute("SELECT substr(subkey, 2, 16) as h FROM _globals WHERE ns='EMBED' LIMIT 1")
h = c.fetchone()[0]
print('Hash:', repr(h))
c.execute("SELECT value FROM _globals WHERE ns='EMBED_META' AND substr(subkey, 2, 16)=?", [h])
for row in c.fetchall():
    val = row[0]
    raw = val.decode('utf-8') if isinstance(val, bytes) else str(val)
    print('  raw:', raw[:60])
    decoded = json.loads(raw)
    print('  decoded:', repr(decoded)[:60])
    print('  type:', type(decoded).__name__)
    is_petmap = decoded == 'petmap'
    has_en = 'en ' in decoded[:20] if isinstance(decoded, str) else False
    print('  petmap:', is_petmap, 'en:', has_en)
    print()
conn.close()
