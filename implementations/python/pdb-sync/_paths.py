#!/usr/bin/env python3
"""_paths.py — rutas del repo calculadas desde __file__ (cero hardcode).

Sustituye a los sys.path.insert con rutas absolutas que quedaron
rotos al mover el repo. Prioridad para la BD: env PDB_PATH > env PDB_DB >
ruta por defecto dentro del repo.

Uso:
    import _paths            # ya deja PDB_DIR y SYNC_DIR en sys.path
    from pdb_tools import tool_set
    db = _paths.DB_PATH
"""
import os, sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]  # .../lumen-protocol
PDB_DIR = REPO / "implementations" / "mcp-servers" / "pdb"
SYNC_DIR = REPO / "implementations" / "python" / "pdb-sync"

PDB_DIR_S = str(PDB_DIR)
SYNC_DIR_S = str(SYNC_DIR)
AUTO_MEMORY_DIR_S = str(SYNC_DIR / "auto-memory")
REPORT_M = str(SYNC_DIR / "routines" / "REPORT.m")

# MSM connection module (pdb-msm-importer repo)
MSM_SCRIPTS_DIR_S = os.environ.get("MSM_IMPORTER_DIR", "")

DB_PATH = (
    os.environ.get("PDB_PATH")
    or os.environ.get("PDB_DB")
    or str(PDB_DIR / "lumen-pdb.db")
)


def add():
    """Inserta los dirs del stack PDB en sys.path (idempotente)."""
    for p in (PDB_DIR_S, SYNC_DIR_S, MSM_SCRIPTS_DIR_S):
        if p not in sys.path:
            sys.path.insert(0, p)


add()
