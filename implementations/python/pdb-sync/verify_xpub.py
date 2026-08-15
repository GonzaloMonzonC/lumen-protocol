import _paths, json, sqlite3
from _paths import DB_PATH

con = sqlite3.connect(str(DB_PATH))
rows = con.execute("SELECT subkey, value FROM _globals WHERE ns='X_PUB'").fetchall()

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
    print("X_PUB VACÍO")
else:
    for k, fields in sorted(items.items()):
        print(k, "->", fields)
