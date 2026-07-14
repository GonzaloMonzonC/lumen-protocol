#!/usr/bin/env python3
"""
pdb_service_manager.py — C1: Service Manager / Orquestador.

Inspirado en STU1:55 de MSM:
  S JOB="" F  S JOB=$O(^SYS(CONFIG,"JOB",JOB)) Q:JOB=""  D JOB(^(JOB))

Nuestro equivalente:
  Para cada agente en ^System("pulse"):
    1. Verificar heartbeat (último pulso < 60s)
    2. Revisar tareas pendientes asignadas a ese agente
    3. Despachar tarea si agente está disponible
    4. Registrar micro-status de la operación

Integra con:
  - ^System("pulse") → estado de cada agente
  - ^DDP("messages") → colas de mensajes
  - ^System("decisions") → registro de decisiones
  - pdb_journal.py → control block del journal

Autor: Hermes + CadencesLab (C1 — Sprint C MSM→Lumen)
Licencia: MIT (lumen-protocol)
"""

import sys, os, json
import _paths  # rutas repo-relativas
from datetime import datetime, timezone, timedelta

# ── Config ──────────────────────────────────────────────────────────

PULSE_TIMEOUT = 60  # segundos sin heartbeat = offline
SYS_NS = "System"

# ── Helpers ─────────────────────────────────────────────────────────

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now():
    return datetime.now(timezone.utc)

def _now_iso():
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Service Manager Core ───────────────────────────────────────────

def get_agents():
    """Iterar agentes via $ORDER (patrón STU1:55)."""
    _, _, tool_order = _get_tools()
    agents = []
    key = ""
    while True:
        r = tool_order({"ns": SYS_NS, "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        key = r["value"]
        agents.append(key)
    return agents

def check_agent_health(agent_id):
    """Verificar si un agente está online (heartbeat < 60s)."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": SYS_NS, "subs": ["pulse", agent_id]})
    pulse = r.get("value") if r.get("success") else None
    if not pulse:
        return "unknown"

    last_raw = pulse.get("last_activity") or pulse.get("last_heartbeat")
    if not last_raw:
        return "unknown"

    try:
        last = datetime.fromisoformat(last_raw.replace("Z", "+00:00"))
        age = (_now() - last).total_seconds()
    except (ValueError, TypeError):
        return "unknown"

    if age > PULSE_TIMEOUT * 3:
        return "offline"
    elif age > PULSE_TIMEOUT:
        return "idle"
    else:
        status = pulse.get("status", "online")
        return status

def get_pending_tasks():
    """Buscar tareas pendientes en ^DDP messages y ^System decisions."""
    _, _, tool_order = _get_tools()
    tasks = []

    # Buscar en mensajes DDP pendientes
    key = ""
    while True:
        r = tool_order({"ns": "DDP", "subs": ["messages", key], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        key = r["value"]
        # Cada key es un circuit_id, buscar mensajes dentro
        msg_key = ""
        while True:
            mr = tool_order({"ns": "DDP", "subs": ["messages", key, msg_key], "direction": 1})
            if not mr.get("success") or mr.get("value") is None:
                break
            msg_key = mr["value"]
            tasks.append({"circuit": key, "msg_id": msg_key})

    return tasks

def dispatch_cycle(agent_id):
    """Ciclo de despacho para un agente (como STU1 procesa cada JOB)."""
    tool_set, _, _ = _get_tools()
    health = check_agent_health(agent_id)

    # 1. Solo despachar a agentes activos
    if health not in ("online", "busy"):
        return {"agent": agent_id, "health": health, "action": "skipped"}

    # 2. Buscar mensajes DDP dirigidos a este agente
    tasks = get_pending_tasks()

    # 3. Decisión y registro
    if tasks:
        tool_set({"ns": SYS_NS, "subs": ["decisions", f"dispatch-{agent_id}-{_now().timestamp()}"], "value": {
            "agent": agent_id,
            "tasks_pending": len(tasks),
            "health": health,
            "action": "dispatch",
            "timestamp": _now_iso(),
        }})
        return {"agent": agent_id, "health": health, "action": "dispatch", "tasks": len(tasks)}

    return {"agent": agent_id, "health": health, "action": "idle"}

def manager_run():
    """Ejecutar un ciclo completo del Service Manager (como STU1:55)."""
    agents = get_agents()
    results = []
    for agent in agents:
        result = dispatch_cycle(agent)
        results.append(result)
    return {"agents_scanned": len(agents), "results": results}

# ── Monitor (como %ACTJOB) ────────────────────────────────────────

def monitor_status():
    """Estado del ecosistema (como %ACTJOB LIST)."""
    agents = get_agents()
    statuses = {"online": 0, "busy": 0, "idle": 0, "offline": 0, "unknown": 0}

    for agent in agents:
        health = check_agent_health(agent)
        statuses[health] = statuses.get(health, 0) + 1

    return {
        "total": len(agents),
        "statuses": statuses,
        "agents": agents,
    }

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "run":
        result = manager_run()
        print(f"📋 Ciclo: {result['agents_scanned']} agentes")
        for r in result["results"]:
            emoji = {"online": "🟢", "busy": "🟡", "idle": "⏸️", "offline": "🔴", "unknown": "❓"}.get(r["health"], "❓")
            print(f"  {emoji} {r['agent']:12s} {r['health']:8s} → {r['action']}")

    elif cmd == "status":
        s = monitor_status()
        print(f"📊 Ecosistema: {s['total']} agentes")
        for status, count in s["statuses"].items():
            emoji = {"online": "🟢", "busy": "🟡", "idle": "⏸️", "offline": "🔴", "unknown": "❓"}.get(status, "❓")
            if count > 0:
                print(f"  {emoji} {status}: {count}")

    elif cmd == "check":
        agent = sys.argv[2] if len(sys.argv) > 2 else "hermes"
        health = check_agent_health(agent)
        print(f"  {'🟢' if health == 'online' else '🔴'} {agent}: {health}")
