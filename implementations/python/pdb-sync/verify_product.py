import _paths, json, sqlite3
from _paths import DB_PATH

con = sqlite3.connect(str(DB_PATH))
rows = con.execute("SELECT subkey, value FROM _globals WHERE ns='PRODUCT'").fetchall()

def dec(k):
    raw = k if isinstance(k, bytes) else k.encode()
    parts = raw.split(b'\xff')
    return [p.lstrip(b'\x02').decode('utf-8', 'replace') for p in parts if p]

items = {}
for sk, v in rows:
    p = dec(sk)
    if len(p) >= 3:
        items.setdefault(f"{p[0]}/{p[1]}", {})[p[2]] = v

if not items:
    print("PRODUCT VACÍO")
else:
    for k, fields in sorted(items.items()):
        out = {}
        for f, v in fields.items():
            try:
                out[f] = json.loads(v)
            except Exception:
                out[f] = v
        print(k, "->", out)
