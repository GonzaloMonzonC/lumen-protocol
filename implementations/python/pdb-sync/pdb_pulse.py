#!/usr/bin/env python3
"""
pdb-pulse — Heartbeat del ecosistema.

Sprint 0.3 del sistema de cognición distribuida CadencesLab.
Escribe ^System("pulse",<agente>) en la PDB local cada N segundos.
El pdb-sync-bridge lo replica al Edge para que la fachada externa
sepa qué agentes están disponibles.

Schema:
    ^System("pulse","<agente>")
        status: "online" | "offline" | "busy"
        last_activity: ISO8601
        started_at: ISO8601
        load: 0-10
        version: string
        capabilities: [string]

TTL: 24 horas (se regenera en cada heartbeat)

Uso:
    python pdb_pulse.py --agent hermes
    python pdb_pulse.py --agent hermes --daemon --interval 60

Author: Hermes + CadencesLab
Date: 2026-07-10
"""

import json
import os
import sys
import time
from datetime import datetime, timezone

# ── Helpers ──────────────────────────────────────────────────────────

def get_pdb_tools():
    """Importar pdb_tools desde el path correcto."""
    pdb_path = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    sys.path.insert(0, pdb_path)
    from pdb_tools import tool_set
    return tool_set

# ── Pulse ────────────────────────────────────────────────────────────

def emit_pulse(agent_id, status="online", load=0):
    """Emitir heartbeat del agente."""
    tool_set = get_pdb_tools()

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    pulse = {
        "status": status,
        "last_activity": now,
        "load": load,
    }

    # Escribir en PDB local → pdb-sync-bridge lo replicará al Edge
    result = tool_set({
        "ns": "System",
        "subs": ["pulse", agent_id],
        "value": pulse
    })

    if result.get("success"):
        print(f"[pulse] 💓 {agent_id} → {status} ({now})")
    else:
        print(f"[pulse] ❌ {agent_id}: {result.get('error')}")

    return result

# ── Daemon ───────────────────────────────────────────────────────────

def run_daemon(agent_id, interval=60):
    """Emitir heartbeat cada N segundos."""
    print(f"[pulse] Daemon iniciado — agente: {agent_id}, intervalo: {interval}s")

    started = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    while True:
        try:
            emit_pulse(agent_id)
        except Exception as e:
            print(f"[pulse] ❌ ERROR: {e}")
        time.sleep(interval)

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    agent = None
    daemon = False
    interval = 60

    for i, arg in enumerate(sys.argv):
        if arg == "--agent" and i + 1 < len(sys.argv):
            agent = sys.argv[i + 1]
        elif arg == "--daemon":
            daemon = True
        elif arg == "--interval" and i + 1 < len(sys.argv):
            interval = int(sys.argv[i + 1])

    if not agent:
        print("Uso: python pdb_pulse.py --agent <nombre> [--daemon] [--interval N]")
        sys.exit(1)

    if daemon:
        run_daemon(agent, interval)
    else:
        emit_pulse(agent)
