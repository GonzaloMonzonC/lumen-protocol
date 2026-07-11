#!/usr/bin/env python3
"""
pdb_msajob.py — MSAJOB: Control de agentes (3 niveles de kill).

Inspirado en MSAJOB (264 líneas) de MSM.

Extiende nuestro Job Monitor (C3) con capacidad de gestionar agentes.

Propuesta Zalo:
  | Nivel | Nombre  | Comportamiento                          |
  |-------|---------|------------------------------------------|
  | 1     | Suave   | Notificación + cierre ordenado + log     |
  | 2     | Error   | Log de error + kill forzado              |
  | 3     | Seco    | Kill inmediato + emergency cleanup       |

Casos de uso:
  - Hermes detecta que Tom no responde heartbeats → nivel 1, si falla → nivel 2
  - Lisa detecta tarea huérfana → nivel 2
  - Agente en bucle infinito → nivel 3

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, time
from datetime import datetime, timezone

MSAJOB_NS = "MSAJOB"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Kill levels ───────────────────────────────────────────────────

def agent_kill(agent_id, level=1):
    """Terminar un agente con el nivel especificado.
    
    Args:
        agent_id: nombre del agente
        level: 1 (suave), 2 (error), 3 (seco)
    
    Returns:
        dict con resultado de la operación
    """
    tool_set, tool_get, _, tool_kill = _get_tools()
    ts = _now_iso()
    
    # Obtener estado actual
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    pulse = r.get("value") if r.get("success") and r.get("value") else {}
    
    if not pulse:
        return {"success": False, "error": "Agent not found", "agent": agent_id}
    
    # Nivel 1: Suave
    if level == 1:
        pulse["status"] = "stopping"
        pulse["kill_level"] = 1
        pulse["kill_reason"] = "soft_kill"
        pulse["kill_timestamp"] = ts
        tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
        
        # Registrar en historial
        tool_set({"ns": MSAJOB_NS, "subs": ["history", agent_id, ts], "value": {
            "level": 1,
            "action": "soft_kill",
            "reason": "Solicitud de cierre ordenado",
            "result": "pending",
            "timestamp": ts,
        }})
        
        # Cerrar sesión si existe
        from pdb_session_audit import session_end
        try: session_end(agent_id)
        except: pass
        
        return {"success": True, "level": 1, "agent": agent_id, "action": "soft_kill"}
    
    # Nivel 2: Error
    elif level == 2:
        pulse["status"] = "error"
        pulse["kill_level"] = 2
        pulse["kill_reason"] = "error_kill"
        pulse["kill_timestamp"] = ts
        tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
        
        # Registrar error en catálogo
        from pdb_agent_error_trap import capture_agent_error
        try:
            capture_agent_error(agent_id, f"Nivel 2 kill: {agent_id} no responde")
        except: pass
        
        # Registrar en historial
        tool_set({"ns": MSAJOB_NS, "subs": ["history", agent_id, ts], "value": {
            "level": 2,
            "action": "error_kill",
            "reason": "Agente no responde a nivel 1",
            "result": "killed",
            "timestamp": ts,
        }})
        
        # Limpiar datos del agente
        tool_kill({"ns": "Agent", "subs": [agent_id, "data"]})
        
        return {"success": True, "level": 2, "agent": agent_id, "action": "error_kill"}
    
    # Nivel 3: Seco (emergencia)
    elif level == 3:
        pulse["status"] = "offline"
        pulse["kill_level"] = 3
        pulse["kill_reason"] = "hard_kill"
        pulse["kill_timestamp"] = ts
        tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
        
        # Eliminar todos los datos del agente
        tool_kill({"ns": "Agent", "subs": [agent_id]})
        tool_kill({"ns": "DDP", "subs": ["circuits", agent_id]})
        tool_kill({"ns": "LOGON", "subs": ["session", agent_id]})
        
        # Registrar en historial
        tool_set({"ns": MSAJOB_NS, "subs": ["history", agent_id, ts], "value": {
            "level": 3,
            "action": "hard_kill",
            "reason": "Kill de emergencia",
            "result": "killed_and_cleaned",
            "timestamp": ts,
        }})
        
        return {"success": True, "level": 3, "agent": agent_id, "action": "hard_kill"}
    
    else:
        return {"success": False, "error": f"Invalid level: {level}", "agent": agent_id}

# ── History ───────────────────────────────────────────────────────

def agent_history(agent_id=None, limit=10):
    """Historial de kills de un agente (o todos)."""
    _, tool_get, tool_order, _ = _get_tools()
    history = []
    
    agents = [agent_id] if agent_id else []
    if not agents:
        key = ""
        while True:
            r = tool_order({"ns": MSAJOB_NS, "subs": ["history", key], "direction": 1})
            if not r.get("success") or r.get("value") is None: break
            key = r["value"]
            agents.append(key)
    
    for agent in agents:
        sk = ""
        while True:
            r = tool_order({"ns": MSAJOB_NS, "subs": ["history", agent, sk], "direction": -1})
            if not r.get("success") or r.get("value") is None: break
            sk = r["value"]
            r2 = tool_get({"ns": MSAJOB_NS, "subs": ["history", agent, sk]})
            if r2.get("success") and r2.get("value"):
                history.append(r2["value"])
                if len(history) >= limit: return history
    return history

# ── Status ────────────────────────────────────────────────────────

def agent_status(agent_id):
    """Estado actual de un agente."""
    _, tool_get, _, _ = _get_tools()
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    return r.get("value") if r.get("success") and r.get("value") else {"status": "unknown"}

# ── Agent introspection (MSSJEX) ─────────────────────────────────

def agent_info(agent_id):
    """Información detallada de un agente (MSSJEX GETJOB).
    
    Retorna: estado pulse + micro_status + sesión activa + operación actual.
    """
    _, tool_get, _, _ = _get_tools()
    
    # Pulse
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    pulse = r.get("value") if r.get("success") and r.get("value") else {}
    
    # Estado de sesión
    r2 = tool_get({"ns": "LOGON", "subs": ["session", agent_id]})
    session = r2.get("value") if r2.get("success") and r2.get("value") else {}
    
    # Workspace activo
    r3 = tool_get({"ns": "Agent", "subs": [agent_id, "data"]})
    workspace = r3.get("value") if r3.get("success") and r3.get("value") else {}
    
    # Errores recientes
    errors = []
    from pdb_tools import tool_order
    key = ""
    while True:
        r4 = tool_order({"ns": "System", "subs": ["errors", key], "direction": -1})
        if not r4.get("success") or r4.get("value") is None: break
        key = r4["value"]
        r5 = tool_get({"ns": "System", "subs": ["errors", key]})
        if r5.get("success") and r5.get("value"):
            e = r5["value"]
            if e.get("agent") == agent_id:
                errors.append(e.get("error", "")[:60])
            if len(errors) >= 3: break
    
    return {
        "agent": agent_id,
        "status": pulse.get("status", "unknown"),
        "load": pulse.get("load", 0),
        "micro_status": pulse.get("micro_status", ""),
        "last_activity": pulse.get("last_activity", ""),
        "session": session.get("status", "none") if isinstance(session, dict) else "none",
        "workspace_keys": list(workspace.keys()) if isinstance(workspace, dict) else [],
        "recent_errors": errors,
    }

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "kill":
        agent = sys.argv[2]
        level = int(sys.argv[3]) if len(sys.argv) > 3 else 1
        r = agent_kill(agent, level)
        niveles = {1: "suave", 2: "error", 3: "seco"}
        if r['success']:
            print(f"✅ {agent}: kill nivel {level} ({niveles[level]})")
        else:
            print(f"❌ {agent}: {r.get('error', 'falló')}")
    
    elif cmd == "history":
        agent = sys.argv[2] if len(sys.argv) > 2 else None
        for h in agent_history(agent):
            icon = {1: "🟢", 2: "🟡", 3: "🔴"}.get(h['level'], "❓")
            print(f"  {icon} {h.get('agent', h.get('action',''))[:20]:20s} L{h['level']} {h['action']}")
    
    elif cmd == "status":
        agent = sys.argv[2]
        s = agent_status(agent)
        print(f"  {agent}: {s.get('status', '?')}")
