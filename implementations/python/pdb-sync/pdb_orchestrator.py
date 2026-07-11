#!/usr/bin/env python3
"""
pdb_orchestrator.py — Service Manager estilo MSM (Sprint C).

Patrones extraídos de STU1 + %ACTJOB, adaptados a MVM + PDB:
  - STU1:55 → $ORDER loop sobre ^AGENTS para auto-start
  - STU1:70 → $ORDER loop sobre ^PATCHES para auto-update
  - %ACTJOB → monitor de agentes activos vía $ORDER en ^System("pulse")

NO copia MSM — adapta las soluciones a nuestra arquitectura:
  ^System("agents") en vez de ^SYS(CONFIG,"JOB")
  ^System("pulse") en vez de $V(0, JOB, 2)
  M-code ejecutable en vez de J @JOB

Author: Hermes + CadencesLab (Sprint C — MSM→Lumen)
Date: 2026-07-11
"""

import sys, os, json, time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from pdb_tools import tool_set, tool_get, tool_order, tool_data, tool_m_eval

# ── Config ──────────────────────────────────────────────────────────

AGENTS_NS = "System"
PULSE_KEY = "pulse"

# ── Service Manager (STU1:55) ──────────────────────────────────────

def orch_register_agent(agent_id: str, command: str, auto_start: bool = True):
    """Registrar un agente en ^System("agents") como MSM registraba en ^SYS(CONFIG,"JOB").
    command: "START^BACKUP:00:00:5" (formato MSM: tag^routine:time:interval:priority)
    """
    tool_set({"ns": AGENTS_NS, "subs": ["agents", agent_id], "value": {
        "command": command,
        "auto_start": auto_start,
        "registered": datetime.now(timezone.utc).isoformat(),
        "status": "registered"
    }})
    return {"success": True, "agent": agent_id}

def orch_list_agents() -> list:
    """$ORDER loop sobre ^System("agents") — como STU1:55"""
    agents = []
    key = ""
    while True:
        r = tool_order({"ns": AGENTS_NS, "subs": ["agents", key], "direction": 1})
        if not r.get("success") or not r.get("value"):
            break
        key = r["value"]
        data = tool_get({"ns": AGENTS_NS, "subs": ["agents", key]})
        agents.append({"id": key, "config": data.get("value", {})})
    return agents

def orch_mvm_startup():
    """Auto-start: ejecutar el $ORDER loop como STU1:55 pero con M-code.
    
    Equivalente MUMPS:
      S AG="" F  S AG=$O(^System("agents",AG)) Q:AG=""  D
      . S CFG=$G(^(AG)) I CFG["auto_start"] W AG," started "
    """
    code = 'S AG="" F  S AG=$O(^System("agents",AG)) Q:AG=""  S CFG=$G(^(AG)) W AG," "'
    r = tool_m_eval({"expression": code})
    return {"success": r.get("success", False), "output": r.get("result", "")}

# ── Agent Monitor (%ACTJOB) ────────────────────────────────────────

def orch_active_agents() -> list:
    """%ACTJOB adaptado: listar agentes activos vía ^System("pulse").
    MSM usaba $V(0, JOB+base, 2) — nosotros usamos $ORDER en pulse.
    """
    active = []
    key = ""
    while True:
        r = tool_order({"ns": AGENTS_NS, "subs": [PULSE_KEY, key], "direction": 1})
        if not r.get("success") or not r.get("value"):
            break
        key = r["value"]
        data = tool_get({"ns": AGENTS_NS, "subs": [PULSE_KEY, key]})
        agent_data = data.get("value", {})
        if isinstance(agent_data, dict) and agent_data.get("status") == "online":
            active.append({
                "id": key,
                "status": agent_data.get("status"),
                "micro_status": agent_data.get("micro_status", ""),
                "last_activity": agent_data.get("last_activity", "")
            })
    return active

def orch_status():
    """JSTAT-style display para el orquestador."""
    agents = orch_list_agents()
    active = orch_active_agents()
    active_ids = {a["id"] for a in active}

    lines = []
    lines.append("═" * 55)
    lines.append("  🎯 ORQUESTADOR — Service Manager (STU1:55)")
    lines.append("═" * 55)
    lines.append(f"  Agentes registrados: {len(agents)}")
    lines.append(f"  Agentes activos:     {len(active)}")
    lines.append("─" * 55)
    for ag in agents:
        aid = ag["id"]
        cfg = ag.get("config", {})
        is_active = "🟢" if aid in active_ids else "⚫"
        lines.append(f"  {is_active} {aid:15s} → {cfg.get('command', '?')[:40]}")
    lines.append("═" * 55)
    return "\n".join(lines)

# ── M-code executable status (para ^docs) ──────────────────────────

def orch_mcode_status() -> str:
    """M-code para listar agentes — ejecutable desde ^docs.
    $O(^System("agents",""))
    """
    return "$O(^System(\"agents\",\"\"))"

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "register":
        agent = sys.argv[2] if len(sys.argv) > 2 else "test"
        command = sys.argv[3] if len(sys.argv) > 3 else "START"
        print(orch_register_agent(agent, command))
    elif cmd == "list":
        for ag in orch_list_agents():
            print(f"  {ag['id']}: {ag['config'].get('command','?')}")
    elif cmd == "active":
        for ag in orch_active_agents():
            print(f"  🟢 {ag['id']}: {ag.get('micro_status','?')}")
    elif cmd == "startup":
        print(orch_mvm_startup())
    elif cmd == "status":
        print(orch_status())
    elif cmd == "mcode":
        print(orch_mcode_status())
    else:
        print(f"PDB Orquestador (Sprint C)")
        print(f"  register <id> <cmd>   — Registrar agente")
        print(f"  list / active / status — Ver agentes")
        print(f"  startup               — M-code auto-start")
        print(f"  mcode                 — M-code para ^docs")
