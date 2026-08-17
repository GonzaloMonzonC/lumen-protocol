#!/usr/bin/env python3
"""Backup rotativo del PDB local (fuente canónica SSOT).

Copia lumen-pdb.db a pdb-data/backups/lumen-pdb-YYYYMMDD-HHMMSS.db.gz
conservando las últimas N copias (default 14). Uso:
    python backup_pdb.py [--keep N]

Para automatizarlo: cron diario con wrapper .py (sin bash, ver skill).
"""
import gzip, os, shutil, sys, glob
from datetime import datetime
import _paths  # DB_PATH canónico (cero hardcode)

DB_PATH = _paths.DB_PATH
BACKUP_DIR = os.path.join(os.path.dirname(os.path.abspath(DB_PATH)), "backups")
KEEP = int(sys.argv[sys.argv.index("--keep") + 1]) if "--keep" in sys.argv else 14
QUIET = "--quiet" in sys.argv

if not os.path.isfile(DB_PATH):
    print(f"ERROR: no existe {DB_PATH}")
    sys.exit(1)

os.makedirs(BACKUP_DIR, exist_ok=True)
stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
tmp = os.path.join(BACKUP_DIR, f".lumen-pdb-{stamp}.tmp")
out = os.path.join(BACKUP_DIR, f"lumen-pdb-{stamp}.db.gz")

# ⚠️ El DB está en journal_mode=WAL: copiar el fichero .db crudo puede dar un
# snapshot atrasado/inconsistente (cambios vivos en el -wal). VACUUM INTO hace
# un snapshot consistente del estado transaccional actual.
import sqlite3
con = sqlite3.connect(DB_PATH)
try:
    con.execute("VACUUM INTO ?", (tmp,))
finally:
    con.close()

with open(tmp, "rb") as f_in, gzip.open(out, "wb") as f_out:
    shutil.copyfileobj(f_in, f_out, 1024 * 1024)
os.remove(tmp)

size_mb = round(os.path.getsize(out) / 1e6, 2)

# Rotación: borrar los más antiguos que sobren
backs = sorted(glob.glob(os.path.join(BACKUP_DIR, "lumen-pdb-*.db.gz")))
removed = 0
while len(backs) > KEEP:
    os.remove(backs.pop(0))
    removed += 1

if QUIET:
    # Silencioso en éxito (la rotación es normal); los fallos ya salen con
    # traceback y exit != 0 (el cron alerta automáticamente).
    sys.exit(0)

print(f"✅ Backup: {out} ({size_mb} MB) | total: {len(backs)} | eliminados: {removed}")
