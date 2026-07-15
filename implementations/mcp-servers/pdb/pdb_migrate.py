#!/usr/bin/env python3
"""
pdb_migrate.py — migrador one-shot SQLite → redb (Fase 4).

Copia raw: mismas subkeys (la codificación es idéntica entre motores,
golden verificado) y mismos values (JSON UTF-8). Bulk por transacciones
de N filas vía FFI lp_set_many.

Uso:
    python3 pdb_migrate.py                        # PDB_PATH → <PDB_PATH>.redb
    python3 pdb_migrate.py --src a.db --dst b.redb
    python3 pdb_migrate.py --verify               # migra y verifica todo
    python3 pdb_migrate.py --force --verify       # reemplaza destino existente
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from pdb_tools import pdb_connect, _get_db_path  # noqa: E402
from lumen_pdb import RedbPDB, ensure_built  # noqa: E402

CHUNK = 2000


def _as_bytes(value):
    if value is None:
        return b""
    if isinstance(value, str):
        return value.encode()
    return bytes(value)


def migrate(src=None, dst=None, verify=False, force=False):
    src = Path(src or _get_db_path()).expanduser()
    dst = Path(dst or src.with_suffix(".redb")).expanduser()
    if not src.exists():
        print(f"❌ origen no existe: {src}")
        return 1
    if src.resolve() == dst.resolve():
        print("❌ origen y destino no pueden ser el mismo fichero")
        return 1
    if dst.exists():
        if not force:
            print(f"❌ destino ya existe: {dst} (usa --force para reemplazarlo)")
            return 1
        dst.unlink()
    if not dst.parent.exists():
        print(f"❌ directorio destino no existe: {dst.parent}")
        return 1
    if not ensure_built():
        print("❌ dylib redb no disponible (¿cargo?)")
        return 1

    t0 = time.perf_counter()
    con = redb = None
    try:
        con = pdb_connect(readonly=True, path=str(src))
        redb = RedbPDB(str(dst))
        namespaces = [r[0] for r in con.execute(
            "SELECT DISTINCT ns FROM _globals ORDER BY ns").fetchall()]
        total = 0
        for ns in namespaces:
            cursor = con.execute(
                "SELECT subkey, value FROM _globals WHERE ns=? ORDER BY subkey",
                (ns,))
            ns_total = 0
            while True:
                rows = cursor.fetchmany(CHUNK)
                if not rows:
                    break
                pairs = [(bytes(r[0]), _as_bytes(r[1])) for r in rows]
                copied = redb.set_raw(ns, pairs)
                total += copied
                ns_total += copied
            print(f"  {ns}: {ns_total} filas")
        redb.flush()
        dt = time.perf_counter() - t0
        rate = total / dt if dt else 0
        print(f"✅ {total} filas → {dst} en {dt:.2f}s ({rate:.0f} filas/s)")

        if verify:
            errors = 0
            for ns in namespaces:
                n_sql = con.execute(
                    "SELECT COUNT(*) FROM _globals WHERE ns=?", (ns,)
                ).fetchone()[0]
                n_redb = redb.count(ns)
                if n_sql != n_redb:
                    print(f"  ❌ {ns}: sqlite={n_sql} redb={n_redb}")
                    errors += abs(n_sql - n_redb) or 1
                cursor = con.execute(
                    "SELECT subkey, value FROM _globals WHERE ns=? ORDER BY subkey",
                    (ns,))
                for row in cursor:
                    key = bytes(row[0])
                    if redb.get_raw(ns, key) != _as_bytes(row[1]):
                        errors += 1
            if errors:
                print(f"❌ verificación completa: {errors} discrepancias")
                return 2
            print(f"✅ verificación completa: {total}/{total} claves y valores idénticos")
        return 0
    except Exception as exc:
        print(f"❌ migración fallida: {exc}")
        return 1
    finally:
        if con is not None:
            con.close()
        if redb is not None:
            redb.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Migrador SQLite → redb")
    p.add_argument("--src", default=None, help="BD SQLite origen (default: PDB_PATH)")
    p.add_argument("--dst", default=None, help="fichero redb destino (default: <src>.redb)")
    p.add_argument("--verify", action="store_true", help="verificar tras migrar")
    p.add_argument("--force", action="store_true", help="reemplazar destino existente")
    a = p.parse_args()
    sys.exit(migrate(a.src, a.dst, a.verify, a.force))
