#!/usr/bin/env python3
"""lente_indexes.py — Índices idempotentes de El Lente (feature 5 del libro).

Crea los índices que El Lente recomienda sobre la PDB (86K filas en _globals).
Idempotente: CREATE INDEX IF NOT EXISTS — se puede correr cuando se quiera.
"""
import sqlite3
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _paths  # noqa: E402

DB = _paths.DB_PATH
INDEXES = [
    # El más lento detectado: GROUP BY ns del dashboard (14.4ms → 6.4ms)
    "CREATE INDEX IF NOT EXISTS idx_globals_ns ON _globals(ns)",
    # $ORDER sin prefijo / búsquedas por subkey
    "CREATE INDEX IF NOT EXISTS idx_globals_subkey ON _globals(subkey)",
]

conn = sqlite3.connect(DB)
for sql in INDEXES:
    conn.execute(sql)
conn.commit()
rows = conn.execute("SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'").fetchall()
print("Índices del Lente:", [r[0] for r in rows])
conn.close()
