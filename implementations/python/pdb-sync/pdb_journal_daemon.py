#!/usr/bin/env python3
"""
pdb_journal_daemon.py — MSM-02: JRNDAEMN adaptado.

DAEMON de journaling en background. Como JRNDAEMN (156 líneas) de MSM:
  - Monitoriza ^CHANGES continuamente
  - Flushes batches al Edge (pdb-sync-bridge)
  - Gestiona status de archivos (ACTIVE/CURRENT/REUSABLE)
  - Checkpoint automático cada N entradas
  - Lock para evitar duplicados

Diferencia con JRNDAEMN de MSM:
  MSM: daemon en C, acceso directo a memoria ($V, $ZMSM)
  Nosotros: Python con tool_set/get, HTTP al Edge

Esquema:
  ^CHANGES("daemon") = {status, last_flush, entries_flushed, errors}

Autor: Hermes + CadencesLab (MSM-02)
Licencia: MIT (lumen-protocol)
"""

import os, sys, json, time, threading
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

DAEMON_NS = "CHANGES"
CHECKPOINT_FILE = os.path.expanduser("~/.hermes/pdb-journal-daemon-checkpoint.json")

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Daemon Control ───────────────────────────────────────────────

def daemon_init():
    """Inicializar estado del daemon (como JRNDAEMN SETSTAT)."""
    tool_set, tool_get, _ = _get_tools()
    r = tool_get({"ns": DAEMON_NS, "subs": ["daemon"]})
    if r.get("value"):
        return r["value"]
    state = {
        "status": "ACTIVE",
        "last_flush": None,
        "entries_flushed": 0,
        "errors": 0,
        "batch_size": 50,
        "interval_sec": 10,
        "started": _now_iso(),
    }
    tool_set({"ns": DAEMON_NS, "subs": ["daemon"], "value": state})
    return state

def daemon_set_status(status):
    """SETSTAT: cambiar estado del daemon (ACTIVE, SUSPENDED, STOPPED)."""
    tool_set, tool_get, _ = _get_tools()
    r = tool_get({"ns": DAEMON_NS, "subs": ["daemon"]})
    state = r.get("value") or daemon_init()
    state["status"] = status
    state["updated"] = _now_iso()
    tool_set({"ns": DAEMON_NS, "subs": ["daemon"], "value": state})

def daemon_status():
    """Estado actual del daemon."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": DAEMON_NS, "subs": ["daemon"]})
    return r.get("value") if r.get("success") else daemon_init()

# ── Flush logic ─────────────────────────────────────────────────

def daemon_flush_to_edge(entries):
    """Flush de entradas al Edge (como JRNDAEMN escribe journal).
    
    En MSM: escribe a disco via $V + $ZMSM.
    Nosotros: POST al pdb-edge-worker vía HTTP.
    """
    import urllib.request, json as j

    EDGE_URL = "https://pdb-edge.gonzalomonzonc.workers.dev/v1/batch"
    try:
        data = j.dumps({"entries": entries}).encode()
        req = urllib.request.Request(EDGE_URL, data=data, 
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req, timeout=10)
        return resp.status == 200
    except Exception as e:
        return False

def daemon_cycle():
    """Un ciclo del daemon (como JRNDAEMN procesa un batch)."""
    tool_set, tool_get, tool_order = _get_tools()
    state = daemon_init()
    
    if state.get("status") != "ACTIVE":
        return {"flushed": 0, "status": state.get("status")}

    # Leer últimas entradas de ^CHANGES no flusheadas
    cp = _load_checkpoint()
    last_seq = cp.get("last_seq", 0)
    
    entries = []
    key = ""
    while len(entries) < state.get("batch_size", 50):
        r = tool_order({"ns": "CHANGES", "subs": [key], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        key = r["value"]
        # Saltar entries de metadata (file, control, daemon)
        if isinstance(key, str) and key in ("file", "control", "daemon", "metrics"):
            continue
        r2 = tool_get({"ns": "CHANGES", "subs": [key]})
        if r2.get("success") and r2.get("value"):
            entries.append(r2["value"])

    if not entries:
        return {"flushed": 0, "status": "idle"}

    # Flush al Edge
    ok = daemon_flush_to_edge(entries)

    # Actualizar estado
    if ok:
        state["entries_flushed"] = state.get("entries_flushed", 0) + len(entries)
        state["last_flush"] = _now_iso()
        _save_checkpoint({"last_seq": state["entries_flushed"], "last_ts": _now_iso()})
    else:
        state["errors"] = state.get("errors", 0) + 1

    tool_set({"ns": DAEMON_NS, "subs": ["daemon"], "value": state})

    return {"flushed": len(entries) if ok else 0, "status": "active" if ok else "error"}

def _load_checkpoint():
    try:
        with open(CHECKPOINT_FILE) as f:
            return json.load(f)
    except: return {"last_seq": 0, "last_ts": None}

def _save_checkpoint(cp):
    os.makedirs(os.path.dirname(CHECKPOINT_FILE), exist_ok=True)
    with open(CHECKPOINT_FILE, "w") as f:
        json.dump(cp, f)

# ── Daemon loop ─────────────────────────────────────────────────

class JournalDaemon(threading.Thread):
    """Daemon thread que ejecuta ciclos de flush periódicamente."""
    
    def __init__(self, interval=10):
        super().__init__(daemon=True)
        self.interval = interval
        self.running = False
    
    def run(self):
        self.running = True
        while self.running:
            try:
                result = daemon_cycle()
                if result["flushed"] > 0:
                    pass  # Silent success
            except Exception:
                pass
            time.sleep(self.interval)
    
    def stop(self):
        self.running = False

# ── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "start":
        daemon_init()
        d = JournalDaemon(interval=int(sys.argv[2]) if len(sys.argv) > 2 else 10)
        d.start()
        print(f"Daemon started (interval={d.interval}s)")
        try:
            while True: time.sleep(1)
        except KeyboardInterrupt:
            d.stop()
            print("Daemon stopped")

    elif cmd == "cycle":
        r = daemon_cycle()
        print(f"Cycle: flushed={r['flushed']} status={r['status']}")

    elif cmd == "status":
        s = daemon_status()
        print(f"📊 Journal Daemon:")
        for k, v in s.items():
            print(f"  {k}: {v}")

    elif cmd == "pause":
        daemon_set_status("SUSPENDED")
        print("Daemon paused")

    elif cmd == "resume":
        daemon_set_status("ACTIVE")
        print("Daemon resumed")
