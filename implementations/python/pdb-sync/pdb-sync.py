#!/usr/bin/env python3
"""
pdb-sync-bridge — Sincronización unidireccional PDB local → PDB Edge (Cloudflare D1).

Fase 1 del sistema de cognición distribuida CadencesLab.
Lee el journal ^CHANGES de la PDB local y empuja cada operación
al PRIVATE_REPO vía REST API.

Uso:
    python pdb-sync.py                          # sync único
    python pdb-sync.py --daemon --interval 30   # sync continuo cada 30s

Checkpoint:
    Guardado en ~/.hermes/pdb-sync-checkpoint.json
    Contiene el último timestamp_ns procesado.

Protocolo DDP mínimo:
    Cada operación lleva change_id único para idempotencia en Edge.

Author: Hermes + CadencesLab
Date: 2026-07-10
"""

import json
import os
import sqlite3
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# ── Config ──────────────────────────────────────────────────────────

# PDB local
PDB_PATH = os.path.expanduser(
    "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/lumen-pdb.db"
)

# PDB Edge Worker (Cloudflare)
EDGE_URL = os.environ.get("PDB_EDGE_URL", "https://pdb-edge.EDGE_INTERNAL_URL")
EDGE_API_KEY = os.environ.get("PDB_EDGE_KEY", "pdb_hermes_2026")

# Namespaces que se replican (Fase 1)
REPLICATE_NS = {"System", "PROCESSES", "TRUST", "DMs", "Clientes", "Hermes"}

# Checkpoint file
CHECKPOINT_FILE = os.path.expanduser("~/.hermes/pdb-sync-checkpoint.json")

# ── SQLite helpers ───────────────────────────────────────────────────

def get_db():
    """Conectar a PDB local (read-only para sync)."""
    db = sqlite3.connect(f"file:{PDB_PATH}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db

def decode_subs_from_subkey(subkey_blob):
    """Decodificar subkey MUMPS → lista de subscripts."""
    subs = []
    i = 0
    while i < len(subkey_blob):
        if subkey_blob[i] != 0x02:
            i += 1
            continue
        i += 1  # skip \x02
        start = i
        while i < len(subkey_blob) and subkey_blob[i] != 0xff:
            i += 1
        s = subkey_blob[start:i].decode('utf-8', errors='replace')
        if i < len(subkey_blob):
            i += 1  # skip \xff
        # Intentar número
        try:
            subs.append(int(s))
        except ValueError:
            subs.append(s)
    return subs

# ── Checkpoint ───────────────────────────────────────────────────────

def load_checkpoint():
    """Cargar último timestamp_ns procesado."""
    try:
        with open(CHECKPOINT_FILE) as f:
            data = json.load(f)
            return data.get("last_ts_ns", 0)
    except (FileNotFoundError, json.JSONDecodeError):
        return 0

def save_checkpoint(ts_ns):
    """Guardar checkpoint ANTES del sync (no después — ver L2 del debate)."""
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump({
            "last_ts_ns": ts_ns,
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "sync_bridge": "pdb-sync v0.1.0"
        }, f)

# ── Sync ─────────────────────────────────────────────────────────────

def fetch_changes(db, since_ns, limit=500):
    """Leer cambios de ^CHANGES desde since_ns.

    Estrategia MVP: leer con prefijo vacío, filtrar en Python por timestamp.
    El checkpoint evita reprocesar cambios antiguos en syncs posteriores.
    """
    rows = db.execute(
        """SELECT subkey, value FROM _globals
           WHERE ns = 'CHANGES'
           ORDER BY subkey ASC LIMIT ?""",
        (limit,)
    ).fetchall()
    return rows

def parse_change_value(raw_value):
    """Parsear valor de ^CHANGES (puede tener doble encoding JSON)."""
    if isinstance(raw_value, dict):
        return raw_value
    try:
        v = json.loads(raw_value)
        if isinstance(v, str):
            v = json.loads(v)
        return v
    except (json.JSONDecodeError, TypeError):
        return {}

def push_change(change_val, change_id):
    """Enviar un cambio al PRIVATE_REPO."""
    ns = change_val["ns"]
    subs = change_val.get("subs", [])
    op = change_val["op"]
    value = change_val.get("new_value")

    if op == "KILL":
        # KILL → POST /v1/kill/:ns
        url = f"{EDGE_URL}/v1/kill/{ns}"
        body = json.dumps({"subs": subs}).encode()
    elif op in ("SET", "MERGE"):
        # SET/MERGE → POST /v1/set/:ns
        url = f"{EDGE_URL}/v1/set/{ns}"
        body = json.dumps({
            "subs": subs,
            "value": value
        }).encode()
    else:
        return {"ok": False, "error": f"unknown op: {op}"}

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": EDGE_API_KEY,
            "X-Change-Id": change_id,       # idempotencia
            "X-Source": "hermes-local",     # evitar loops
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            return result
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except urllib.error.URLError as e:
        return {"ok": False, "error": f"Network: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}

def sync_once(dry_run=False):
    """Ejecutar un ciclo de sync."""
    db = get_db()
    checkpoint = load_checkpoint()
    print(f"[pdb-sync] Checkpoint: {checkpoint}")

    changes = fetch_changes(db, checkpoint)
    if not changes:
        print("[pdb-sync] No hay cambios pendientes.")
        return {"synced": 0, "errors": 0, "checkpoint": checkpoint}

    synced = 0
    errors = 0
    last_ts_ns = checkpoint

    for row in changes:
        try:
            change_val = parse_change_value(row["value"])
            ns = change_val.get("ns", "")

            # Filtrar solo namespaces replicables
            if ns not in REPLICATE_NS:
                continue

            # Extraer timestamp_ns del valor
            ts_str = change_val.get("timestamp", "")
            ts_ns = hash(ts_str) if ts_str else 0  # fallback: hash del timestamp ISO

            # Saltar cambios ya procesados (anteriores al checkpoint)
            if ts_ns <= checkpoint:
                continue

            # Generar change_id único
            change_id = f"local-{ts_str}-{ns}-{'-'.join(str(s) for s in change_val.get('subs', []))}"

            if dry_run:
                print(f"  [DRY-RUN] [{change_val.get('op')}] {ns} subs={change_val.get('subs')}")
                synced += 1
                last_ts_ns = max(last_ts_ns, ts_ns)
                continue

            result = push_change(change_val, change_id)

            if result.get("ok"):
                synced += 1
                last_ts_ns = max(last_ts_ns, ts_ns)
            else:
                errors += 1
                print(f"[pdb-sync] ERROR: {result.get('error')} — ns={ns}, subs={change_val.get('subs')}")

        except Exception as e:
            errors += 1
            print(f"[pdb-sync] ERROR procesando cambio: {e}")

    # Guardar checkpoint
    if synced > 0:
        save_checkpoint(last_ts_ns)

    print(f"[pdb-sync] Synced: {synced}, Errors: {errors}, Checkpoint: {last_ts_ns}")
    return {"synced": synced, "errors": errors, "checkpoint": last_ts_ns}

# ── Daemon ───────────────────────────────────────────────────────────

def run_daemon(interval=30):
    """Ejecutar sync en bucle cada N segundos."""
    print(f"[pdb-sync] Daemon iniciado — intervalo: {interval}s")
    print(f"[pdb-sync] PDB: {PDB_PATH}")
    print(f"[pdb-sync] Edge: {EDGE_URL}")
    print(f"[pdb-sync] Namespaces: {REPLICATE_NS}")

    while True:
        try:
            sync_once()
        except Exception as e:
            print(f"[pdb-sync] ERROR en ciclo: {e}")
        time.sleep(interval)

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if "--daemon" in sys.argv:
        interval = 30
        for i, arg in enumerate(sys.argv):
            if arg == "--interval" and i + 1 < len(sys.argv):
                interval = int(sys.argv[i + 1])
        run_daemon(interval)
    elif "--dry-run" in sys.argv:
        result = sync_once(dry_run=True)
        sys.exit(0 if result["errors"] == 0 else 1)
    else:
        result = sync_once()
        sys.exit(0 if result["errors"] == 0 else 1)
