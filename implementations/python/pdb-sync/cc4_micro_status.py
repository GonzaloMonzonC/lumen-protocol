#!/usr/bin/env python3
"""
cc4_micro_status.py — CC4: Micro-status de agentes.

Cada agente escribe su micro-status actual en ^System("pulse", agent_id, "micro_status").
Angi lo consume para el dashboard 3D.

Formato micro_status:
  {"status": "online|busy|idle", "task": "descripción corta", "load": 0-10}

Autores:
  Hermes — escribe status
  Tom — actualiza load vía Granite
  Angi — consume para dashboard
  Zalo — KB indexado
  Lisa — orquestación en curso

Autor: Hermes + CadencesLab (CC4-integ)
Licencia: MIT (lumen-protocol)
"""

import sys, os, json
from datetime import datetime, timezone

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Escribir micro-status ─────────────────────────────────────────

def micro_status_update(agent_id, status, task=None, load=None):
    """Actualizar micro-status de un agente.
    
    Args:
        agent_id: nombre del agente
        status: online|busy|idle|offline
        task: descripción corta de lo que está haciendo
        load: carga 0-10
    """
    tool_set, tool_get, _ = _get_tools()
    
    # Leer pulse actual
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    pulse = r.get("value") if r.get("success") and r.get("value") else {}
    
    # Actualizar micro_status
    pulse["status"] = status
    pulse["last_activity"] = _now_iso()
    if task: pulse["micro_status"] = task
    if load is not None: pulse["load"] = load
    
    tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
    return pulse

# ── Leer micro-status de todos ─────────────────────────────────────

def micro_status_all():
    """Obtener micro-status de todos los agentes (para Angi)."""
    _, tool_get, tool_order = _get_tools()
    agents = {}
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["pulse", key]})
        if r2.get("success") and r2.get("value"):
            p = r2["value"]
            agents[key] = {
                "status": p.get("status", "unknown"),
                "micro_status": p.get("micro_status", ""),
                "load": p.get("load", 0),
                "last_activity": p.get("last_activity", ""),
            }
    return agents

# ── CLI ─────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "all"
    
    if cmd == "update":
        agent = sys.argv[2]
        status = sys.argv[3]
        task = sys.argv[4] if len(sys.argv) > 4 else None
        load = int(sys.argv[5]) if len(sys.argv) > 5 else None
        micro_status_update(agent, status, task, load)
        print(f"✅ {agent}: {status} — {task or ''}")
    
    elif cmd == "all":
        all_ = micro_status_all()
        for agent, info in sorted(all_.items()):
            icon = {"online": "🟢", "busy": "🟡", "idle": "⏸️", "offline": "🔴"}.get(info["status"], "❓")
            ms = f" — {info['micro_status']}" if info.get('micro_status') else ""
            print(f"  {icon} {agent:10s} {info['status']:8s} load={info['load']}{ms}")
