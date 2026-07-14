#!/usr/bin/env python3
"""_pdb.py — acceso único al PDB desde el thinking server (contrato Fase 1b).

Todo módulo de thinking/ que necesite la BD del PDB debe pasar por aquí:
    import _pdb
    conn = _pdb.pdb_connect()          # escritura (WAL, PRAGMAs correctos)
    conn = _pdb.pdb_connect(readonly=True)
    path = _pdb.PDB_PATH               # ruta canónica (env-aware)

Prohibido sqlite3.connect() directo — ver docs/PLAN_EVOLUCION.md §2.1.
"""
import sys
from pathlib import Path

_PDB_DIR = str(Path(__file__).resolve().parent.parent / "pdb")
if _PDB_DIR not in sys.path:
    sys.path.insert(0, _PDB_DIR)

from pdb_tools import pdb_connect, _get_db_path  # noqa: E402,F401

PDB_PATH = _get_db_path()
