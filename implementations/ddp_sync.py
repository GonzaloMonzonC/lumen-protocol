#!/usr/bin/env python3
"""
ddp_sync.py — DDP Local Consumer v0.2

Sincronización bidireccional de ^ROUTINE entre edge worker y PDB local.

El encoding de subkeys es compatible (ambos usan \x02 + string + \xff).
Los hex keys del edge se escriben directamente en el local.

Uso:
  python ddp_sync.py                   # sync único (pull + push)
  python ddp_sync.py --watch           # loop cada N segundos
  python ddp_sync.py --pull-only       # solo pull
  python ddp_sync.py --push-only       # solo push
"""

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error
import sqlite3
import hmac
import hashlib
from datetime import datetime, timezone

# ── Config ──
EDGE_URL = os.environ.get("EDGE_URL", "https://pdb-edge.WORKER_INTERNAL_URL")
DDP_HMAC_KEY = os.environ.get("DDP_HMAC_KEY", "")
PEDGE_API_KEY = os.environ.get("PEDGE_API_KEY", "pdb_dev_2026")
DEFAULT_NS = "ROUTINE"
SYNC_INTERVAL = 30  # segundos

# PDB local (env PDB_PATH/PDB_DB > ruta dentro del repo)
PDB_DB = (
    os.environ.get("PDB_PATH")
    or os.environ.get("PDB_DB")
    or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "mcp-servers", "pdb", "lumen-pdb.db")
)


# ── Helpers ──

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sign_hmac(body: str, key: str, timestamp: str) -> str:
    """HMAC-SHA256 signature for DDP auth."""
    data = (timestamp + body + key).encode("utf-8")
    sig = hmac.new(key.encode("utf-8"), data, hashlib.sha256).hexdigest()
    return sig


# ── Edge API ──

def edge_sync(ns: str, since: str, batch_size: int = 200) -> dict:
    """Pull changes from edge worker."""
    body = json.dumps({"ns": ns, "since": since, "batch_size": batch_size}).encode("utf-8")
    ts = _now_iso()
    sig = sign_hmac(body.decode(), DDP_HMAC_KEY, ts) if DDP_HMAC_KEY else ""

    req = urllib.request.Request(
        f"{EDGE_URL}/ddp/sync",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": PEDGE_API_KEY,
            "User-Agent": "Hermes-DDP/1.0",
        }
    )
    if sig:
        req.add_header("X-DDP-HMAC", sig)
        req.add_header("X-DDP-Timestamp", ts)

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def edge_push(ns: str, entries: list) -> dict:
    """Push changes to edge worker."""
    body = json.dumps({"ns": ns, "entries": entries}).encode("utf-8")
    ts = _now_iso()
    sig = sign_hmac(body.decode(), DDP_HMAC_KEY, ts) if DDP_HMAC_KEY else ""

    req = urllib.request.Request(
        f"{EDGE_URL}/ddp/push",
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-API-Key": PEDGE_API_KEY,
            "User-Agent": "Hermes-DDP/1.0",
        }
    )
    if sig:
        req.add_header("X-DDP-HMAC", sig)
        req.add_header("X-DDP-Timestamp", ts)

    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


# ── Local PDB ──

def pdb_conn():
    """Open connection to local PDB."""
    return sqlite3.connect(PDB_DB)


def pdb_apply_entry(ns: str, key_hex: str, value: str, updated_at: str) -> dict:
    """Apply an entry from DDP sync to local PDB.
    
    Uses subkey bytes directly (compatible encoding).
    No conflict resolution on local side (relies on edge timestamp check).
    """
    conn = pdb_conn()
    cursor = conn.cursor()
    subkey = bytes.fromhex(key_hex)
    cursor.execute(
        "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
        (ns, subkey, value)
    )
    conn.commit()
    conn.close()
    return {"status": "applied"}


def pdb_get_pending_local(ns: str, since_ts: str) -> list:
    """Get entries from local PDB that changed after since_ts.
    
    Note: local _globals has no updated_at column. We track this via 
    a sync state table (DDP namespace in _globals).
    For now, return empty list (push from local is future work).
    """
    # TODO: implement local change tracking via trigger or WAL
    return []


# ── Sync state (stored in DDP namespace) ──

def _sync_state_key(ns: str, kind: str = "last_pull_ts") -> bytes:
    return f"DDP:sync:{ns}:{kind}".encode("utf-8")


def get_sync_ts(ns: str) -> str:
    """Get last pull timestamp."""
    conn = pdb_conn()
    cursor = conn.cursor()
    key = _sync_state_key(ns)
    cursor.execute(
        "SELECT value FROM _globals WHERE ns='DDP' AND subkey=?",
        (key,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        return json.loads(row[0])
    return "1970-01-01T00:00:00Z"


def set_sync_ts(ns: str, ts: str):
    """Save last pull timestamp."""
    conn = pdb_conn()
    cursor = conn.cursor()
    key = _sync_state_key(ns)
    cursor.execute(
        "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
        ("DDP", key, json.dumps(ts))
    )
    conn.commit()
    conn.close()


# ── Sync operations ──

def sync_pull(ns: str = DEFAULT_NS) -> dict:
    """Pull changes from edge and apply to local."""
    since = get_sync_ts(ns)
    print(f"[ddp] Pull {ns} desde {since}...")

    result = edge_sync(ns, since)
    entries = result.get("entries", [])

    if not entries:
        print(f"[ddp] 0 cambios nuevos")
        return {"pulled": 0}

    applied = 0
    for entry in entries:
        res = pdb_apply_entry(ns, entry["key"], entry["value"], entry["updated_at"])
        if res["status"] == "applied":
            applied += 1

    new_since = result.get("since", since)
    set_sync_ts(ns, new_since)

    print(f"[ddp] Pull: {applied} applied (since -> {new_since})")
    return {"pulled": applied}


def sync_push(ns: str = DEFAULT_NS) -> dict:
    """Push local changes to edge.
    
    Actualmente es placeholder — requiere change tracking en local PDB.
    """
    # Por ahora, el push local→edge se hace explícitamente cuando Hermes
    # escribe resultados en ^ROUTINE. El DDP consumer solo hace pull.
    print(f"[ddp] Push: no-op (local change tracking pendiente)")
    return {"pushed": 0}


def sync_all(ns: str = DEFAULT_NS):
    """Full sync cycle."""
    print(f"=== DDP Sync: {ns} @ {_now_iso()} ===")
    print(f"  Edge: {EDGE_URL}")
    print(f"  Local: {PDB_DB}")
    pull = sync_pull(ns)
    push = sync_push(ns)
    print(f"=== Sync: {pull['pulled']} pulled, {push['pushed']} pushed ===")
    return pull, push


# ── Main ──

def main():
    parser = argparse.ArgumentParser(description="DDP Local Consumer")
    parser.add_argument("--watch", action="store_true", help="Loop mode")
    parser.add_argument("--interval", type=int, default=SYNC_INTERVAL)
    parser.add_argument("--ns", default=DEFAULT_NS)
    parser.add_argument("--pull-only", action="store_true")
    parser.add_argument("--push-only", action="store_true")
    args = parser.parse_args()

    if args.watch:
        print(f"[ddp] Watch mode: polling each {args.interval}s")
        while True:
            try:
                sync_all(args.ns)
            except Exception as e:
                print(f"[ddp] Error: {e}")
            time.sleep(args.interval)
    elif args.pull_only:
        sync_pull(args.ns)
    elif args.push_only:
        sync_push(args.ns)
    else:
        sync_all(args.ns)


if __name__ == "__main__":
    main()
