import _paths, sqlite3, json
from _paths import DB_PATH

con = sqlite3.connect(str(DB_PATH))
rows = con.execute("SELECT subkey, value FROM _globals WHERE ns='KANBAN' AND subkey LIKE ?", (b'\x02task\xff%',)).fetchall()

tasks = {}
for sk, v in rows:
    p = [x.lstrip(b'\x02').decode('utf-8', 'replace') for x in sk.split(b'\xff') if x.lstrip(b'\x02')]
    if len(p) >= 3 and p[1].startswith('task_') and p[2] == 'title':
        tasks[p[1]] = v.strip('"')

# Niche: la subkey es \x02task\xff<id>\xff<field> — el NICHE no está en la subkey,
# está en el campo 'niche' de la tarea: \x02task\xff<id>\xff\x02niche\xff?? No —
# la estructura real: task_<id> tiene fields via \x02task\xff<id>\xff<field>... el
# niche es un campo. Reconstruyo: agrupo por el PREFIJO del titulo (proyecto).
from collections import Counter
c = Counter()
for tid, t in tasks.items():
    # Detectar proyecto por patrones en el titulo
    low = t.lower()
    proj = 'LUMEN/protocolo'
    for kw, name in [
        ('[angie]', 'FICHAYA/Angie'), ('fichaya', 'FICHAYA/Angie'), ('angie-twitter', 'FICHAYA/Angie'),
        ('radia vet', 'RadiaVet'), ('radia', 'RadiaVet'), ('harbee', 'Harbee'),
        ('quantlab', 'QuantLab'), ('quantum', 'Quantum'), ('qubit', 'Quantum'),
        ('msm-', 'MSM'), ('ml-vm', 'ML-VM'), ('ddp-', 'DDP'), ('jrn-', 'Journal'),
        ('[s1]', 'Device/S1'), ('[s3]', 'Device/S3'), ('[s4]', 'Device/S4'),
        ('smith', 'Smith'), ('zalo', 'Zalo'), ('a2a', 'A2A'), ('[f0]', 'F0-A2A'),
        ('[f1]', 'F1'), ('[f2]', 'F2'), ('[f3]', 'F3'), ('[f4]', 'F4'), ('[f5]', 'F5'), ('[f6]', 'F6'),
    ]:
        if kw in low:
            proj = name
            break
    c[proj] += 1

print(f"TOTAL tareas: {len(tasks)}")
print("\nPor proyecto (heurístico por título):")
for proj, n in c.most_common():
    print(f"  {proj:<18} {n}")
