#!/usr/bin/env python3
"""
pdb-ttl — Olvido programado para PDB (Time-To-Live nativo).

Fase 1 — Sprint 0.2 del sistema de cognición distribuida CadencesLab.
Añade expiración automática a los nodos de la PDB según políticas
de namespace. Sin garbage collector externo. Sin locks adicionales.

Arquitectura:
    - Migración SQLite: añade columna expires_at a _globals
    - Configuración TTL por namespace (jerárquico)
    - Cleanup periódico vía DELETE WHERE expires_at < now

Uso:
    python pdb_ttl.py migrate     # añadir columna expires_at
    python pdb_ttl.py cleanup     # eliminar nodos expirados
    python pdb_ttl.py daemon      # cleanup cada 60s

TTL por namespace (Zalo, Jul 2026):
    ^conversacion/*     → 5 minutos
    ^tareas("temp",*)   → 1 hora
    ^System("pulse",*)  → 24 horas
    ^System("decisions",*) → 30 días
    ^System("events",*) → 1 hora
    ^System(*)          → 7 días (default)
    ^mercado/*          → ∞ (no expira)
    ^Clientes/*         → ∞ (no expira)
    * (default)         → 30 días

Author: Hermes + CadencesLab (debate Zalo-Lisa-Tom)
Date: 2026-07-10
"""

import json
import _paths  # rutas repo-relativas
import os
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────

PDB_PATH = _paths.DB_PATH

# TTL en segundos por namespace (patrón glob)
NAMESPACE_TTL = [
    # (pattern, ttl_seconds)
    # Patrones más específicos primero
    ("conversacion", 300),                       # 5 minutos
    ("tareas/temp", 3600),                       # 1 hora (tareas temporales)
    ("System/pulse", 86400),                     # 24 horas (heartbeat)
    ("System/decisions", 2592000),               # 30 días (criterio)
    ("System/events", 3600),                     # 1 hora (eventos)
    ("System", 604800),                          # 7 días (resto de System)
    ("mercado", None),                           # ∞ (conocimiento)
    ("Clientes", None),                          # ∞ (datos de negocio)
]

DEFAULT_TTL = 2592000  # 30 días por defecto

# ── Migración ────────────────────────────────────────────────────────

def migrate():
    """Añadir columna expires_at a _globals."""
    db = pdb_connect()

    # Verificar si la columna ya existe
    cols = db.execute("PRAGMA table_info(_globals)").fetchall()
    col_names = [c[1] for c in cols]

    if "expires_at" in col_names:
        print("[pdb-ttl] Columna expires_at ya existe.")
        return

    print("[pdb-ttl] Añadiendo columna expires_at a _globals...")
    db.execute("ALTER TABLE _globals ADD COLUMN expires_at TEXT")
    db.commit()

    # Verificar
    cols = db.execute("PRAGMA table_info(_globals)").fetchall()
    col_names = [c[1] for c in cols]
    assert "expires_at" in col_names, "¡Migración falló!"
    print("[pdb-ttl] ✅ Migración completada.")

# ── TTL lookup ───────────────────────────────────────────────────────

def get_ttl(ns, subs=None):
    """Calcular TTL para un namespace + subscripts.

    Los patrones se evalúan como: ns/sub1/sub2/...
    Ejemplo: "System/pulse" → ^System("pulse")
    """
    # Construir path jerárquico
    path = ns
    if subs:
        # Solo primer nivel de subscripts para el patrón
        for s in subs[:1]:
            path += f"/{s}"

    for pattern, ttl in NAMESPACE_TTL:
        if path.startswith(pattern):
            return ttl

    return DEFAULT_TTL

def compute_expires_at(ttl_seconds):
    """Calcular timestamp de expiración ISO 8601."""
    if ttl_seconds is None:
        return None  # Nunca expira
    expires = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    return expires.strftime("%Y-%m-%dT%H:%M:%SZ")

# ── SET con TTL ──────────────────────────────────────────────────────

def set_with_ttl(ns, subs, value, ttl=None):
    """SET ^ns(subs) = value con TTL automático.

    Si ttl es None, se usa la política del namespace.
    Si ttl es 0 o None en namespace ∞, no expira.
    """
    from pdb_tools import encode_subkey, _encode_value, _get_conn

    key = encode_subkey(subs)
    c = _get_conn(ns, subs)

    if ttl is None:
        ttl = get_ttl(ns, subs)

    expires_at = compute_expires_at(ttl)

    c.execute(
        "INSERT OR REPLACE INTO _globals (ns, subkey, value, expires_at) VALUES (?, ?, ?, ?)",
        [ns, key, _encode_value(value), expires_at]
    )
    c.commit()
    return {"success": True, "expires_at": expires_at}

# ── Cleanup ──────────────────────────────────────────────────────────

def cleanup_expired():
    """Eliminar nodos expirados de la PDB."""
    db = pdb_connect()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Contar antes
    count_before = db.execute(
        "SELECT COUNT(*) FROM _globals WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,)
    ).fetchone()[0]

    if count_before == 0:
        print("[pdb-ttl] No hay nodos expirados.")
        return {"deleted": 0}

    # Eliminar
    db.execute(
        "DELETE FROM _globals WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,)
    )
    db.commit()

    print(f"[pdb-ttl] 🧹 {count_before} nodos expirados eliminados.")
    return {"deleted": count_before}

def stats():
    """Estadísticas de TTL en la PDB."""
    db = pdb_connect()

    total = db.execute("SELECT COUNT(*) FROM _globals").fetchone()[0]
    with_ttl = db.execute("SELECT COUNT(*) FROM _globals WHERE expires_at IS NOT NULL").fetchone()[0]
    expired = db.execute(
        "SELECT COUNT(*) FROM _globals WHERE expires_at IS NOT NULL AND expires_at < datetime('now')"
    ).fetchone()[0]
    eternal = db.execute("SELECT COUNT(*) FROM _globals WHERE expires_at IS NULL").fetchone()[0]

    print(f"[pdb-ttl] 📊 Estadísticas:")
    print(f"  Total nodos:       {total}")
    print(f"  Con TTL:           {with_ttl}")
    print(f"  Expirados (pending): {expired}")
    print(f"  Eternos (∞):       {eternal}")

    return {"total": total, "with_ttl": with_ttl, "expired": expired, "eternal": eternal}

# ── Daemon ───────────────────────────────────────────────────────────

def run_daemon(interval=60):
    """Ejecutar cleanup en bucle cada N segundos."""
    print(f"[pdb-ttl] Daemon iniciado — intervalo: {interval}s")
    print(f"[pdb-ttl] PDB: {PDB_PATH}")

    while True:
        try:
            cleanup_expired()
        except Exception as e:
            print(f"[pdb-ttl] ERROR: {e}")
        time.sleep(interval)

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python pdb_ttl.py [migrate|cleanup|stats|daemon]")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == "migrate":
        migrate()
    elif cmd == "cleanup":
        cleanup_expired()
    elif cmd == "stats":
        stats()
    elif cmd == "daemon":
        interval = 60
        for i, arg in enumerate(sys.argv):
            if arg == "--interval" and i + 1 < len(sys.argv):
                interval = int(sys.argv[i + 1])
        run_daemon(interval)
    else:
        print(f"Comando desconocido: {cmd}")
        sys.exit(1)
