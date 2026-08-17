"""RESTAURACIÓN KANBAN desde backup 18:56 (autorizado por Gonzalo, 15-08-2026)."""
import _paths, sqlite3, gzip, os, shutil
from _paths import DB_PATH

BK = os.path.expanduser("~/pdb-data/backups/lumen-pdb-20260815-185642.db.gz")
TMP = os.path.join(os.path.dirname(DB_PATH), "_bk_kanban_only.db")

# Extraer backup a sqlite temporal
with gzip.open(BK, 'rb') as f:
    open(TMP, 'wb').write(f.read())
bcon = sqlite3.connect(TMP)

# Leer SOLO las entries de KANBAN del backup
rows = bcon.execute("SELECT subkey, value FROM _globals WHERE ns='KANBAN'").fetchall()
bcon.close()
print(f"Backup KANBAN: {len(rows)} entries")

con = sqlite3.connect(str(DB_PATH))
# 1) Backup extra de seguridad del KANBAN actual (por si acaso)
cur = con.execute("SELECT COUNT(*) FROM _globals WHERE ns='KANBAN'").fetchone()[0]
print(f"KANBAN actual (a sustituir): {cur} entries")

# 2) Borrar KANBAN actual y restaurar el del backup
con.execute("DELETE FROM _globals WHERE ns='KANBAN'")
con.executemany("INSERT INTO _globals (ns, subkey, value) VALUES ('KANBAN', ?, ?)", rows)
con.commit()

# 3) Verificación
n = con.execute("SELECT COUNT(*) FROM _globals WHERE ns='KANBAN'").fetchone()[0]
tasks = con.execute("SELECT COUNT(DISTINCT subkey) FROM _globals WHERE ns='KANBAN' AND subkey LIKE ?", (b'\x02task\xff%',)).fetchone()[0]
meta = con.execute("SELECT value FROM _globals WHERE ns='KANBAN' AND subkey=?", (b'\x02meta\xff',)).fetchone()
con.close()
print(f"✅ Restaurado: {n} entries | task_* (distinct subkeys, aprox): {tasks}")
print(f"   meta: {meta[0][:80] if meta else 'SIN META (se reindexará)'}")

os.remove(TMP)
print("tmp limpio")
