import _paths, sqlite3
from _paths import DB_PATH

con = sqlite3.connect(str(DB_PATH))
rows = con.execute("SELECT subkey, value FROM _globals WHERE ns='KANBAN' AND subkey LIKE ?", (b'\x02task\xff%',)).fetchall()

tasks = {}
for sk, v in rows:
    parts = [p.lstrip(b'\x02').decode('utf-8', 'replace') for p in sk.split(b'\xff') if p.lstrip(b'\x02')]
    if len(parts) < 3 or not parts[1].startswith('task_'):
        continue
    tid, field = parts[1], parts[2]
    tasks.setdefault(tid, {})[field] = v

import re
SUS = re.compile(r'test|prueba|unicode|REVIEW|REPRO|RACE|ghost|check\b|smoke|demo|final|tmp|temporal|debug', re.I)

suspicious = []
for tid, fields in sorted(tasks.items(), key=lambda kv: int(kv[0][5:]) if kv[0][5:].isdigit() else 0):
    title = fields.get('title', '')
    title_clean = title.strip('"').lower()
    if SUS.search(title_clean):
        suspicious.append((tid, title[:80]))

print(f"TOTAL: {len(tasks)} tareas | sospechosas: {len(suspicious)}")
for tid, t in suspicious:
    print(f"  {tid}: {t}")
