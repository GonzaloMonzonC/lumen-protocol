#!/usr/bin/env python3
"""
pdb_session_audit.py — Auditoría de sesiones de agentes (%LOGON adaptado).

Registro de sesiones de agentes en ^LOGON("session", agent_id, ts).
Basado en %LOGON (206 líneas) de MSM pero solo la capa de auditoría.

Propuesta Zalo:
  ^LOGON("session", agent_id, timestamp) = {inicio, fin, origen, estado}
  ^LOGON("fail", agent_id, timestamp) = {reason, circuit, count}

Sin locks, sin polling, sin verificación de licencias.
Auditoría limpia y ligera para forense y depuración.

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

LOGON_NS = "LOGON"

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Session lifecycle ─────────────────────────────────────────────

def session_start(agent_id, origin=None):
    """Registrar inicio de sesión de un agente.
    
    Args:
        agent_id: nombre del agente
        origin: circuito DDP o IP de origen (opcional)
    """
    tool_set, tool_get, _ = _get_tools()
    ts = _now_iso()
    ts_key = ts.replace(":", "-").replace(".", "-")
    
    session = {
        "agent": agent_id,
        "started_at": ts,
        "ended_at": None,
        "origin": origin or "unknown",
        "status": "active",
        "duration_sec": None,
    }
    tool_set({"ns": LOGON_NS, "subs": ["session", agent_id, ts_key], "value": session})
    
    # Actualizar pulse con sesión activa
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    pulse = r.get("value") if r.get("success") and r.get("value") else {}
    pulse["session_ts"] = ts
    pulse["status"] = "online"
    tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
    
    return session

def session_end(agent_id):
    """Registrar fin de sesión de un agente."""
    _, tool_get, tool_order = _get_tools()
    tool_set_func, _, _ = _get_tools()
    
    # Encontrar la última sesión activa
    key = ""
    last_session = None
    last_key = None
    while True:
        r = tool_order({"ns": LOGON_NS, "subs": ["session", agent_id, key], "direction": -1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": LOGON_NS, "subs": ["session", agent_id, key]})
        if r2.get("success") and r2.get("value"):
            s = r2["value"]
            if s.get("status") == "active":
                last_session = s
                last_key = key
                break
    
    if last_session and last_key:
        ts_end = _now_iso()
        started = last_session.get("started_at", ts_end)
        try:
            start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(ts_end.replace("Z", "+00:00"))
            duration = int((end_dt - start_dt).total_seconds())
        except:
            duration = 0
        
        last_session["ended_at"] = ts_end
        last_session["status"] = "closed"
        last_session["duration_sec"] = duration
        tool_set_func({"ns": LOGON_NS, "subs": ["session", agent_id, last_key], "value": last_session})
        
        # Actualizar pulse
        r3 = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
        pulse = r3.get("value") if r3.get("success") and r3.get("value") else {}
        pulse["last_session_end"] = ts_end
        pulse["last_session_duration"] = duration
        pulse["status"] = "offline"
        tool_set_func({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
        
        return duration
    return 0

def session_fail(agent_id, reason="unknown"):
    """Registrar intento fallido de sesión."""
    tool_set, tool_get, _ = _get_tools()
    ts = _now_iso()
    ts_key = ts.replace(":", "-").replace(".", "-")
    
    tool_set({"ns": LOGON_NS, "subs": ["fail", agent_id, ts_key], "value": {
        "agent": agent_id,
        "reason": reason,
        "timestamp": ts,
    }})
    
    # Contador de fallos
    r = tool_get({"ns": LOGON_NS, "subs": ["fail", agent_id, "_count"]})
    count = r.get("value") if r.get("success") and r.get("value") else {}
    fail_count = count.get("count", 0) + 1
    tool_set({"ns": LOGON_NS, "subs": ["fail", agent_id, "_count"], "value": {"count": fail_count}})
    
    return fail_count

# ── Reports ─────────────────────────────────────────────────────────

def session_report(agent_id=None, limit=10):
    """Reporte de sesiones recientes."""
    _, tool_get, tool_order = _get_tools()
    sessions = []
    
    agents = [agent_id] if agent_id else []
    if not agents:
        key = ""
        while True:
            r = tool_order({"ns": LOGON_NS, "subs": ["session", key], "direction": 1})
            if not r.get("success") or r.get("value") is None: break
            key = r["value"]
            agents.append(key)
    
    for agent in agents:
        sk = ""
        while True:
            r = tool_order({"ns": LOGON_NS, "subs": ["session", agent, sk], "direction": -1})
            if not r.get("success") or r.get("value") is None: break
            sk = r["value"]
            r2 = tool_get({"ns": LOGON_NS, "subs": ["session", agent, sk]})
            if r2.get("success") and r2.get("value"):
                sessions.append(r2["value"])
                if len(sessions) >= limit: return sessions
    return sessions

def session_active():
    """Listar sesiones activas actualmente."""
    sessions = session_report(limit=50)
    return [s for s in sessions if s.get("status") == "active"]

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "report"
    
    if cmd == "start":
        agent = sys.argv[2]
        origin = sys.argv[3] if len(sys.argv) > 3 else None
        s = session_start(agent, origin)
        print(f"✅ {agent}: sesión iniciada @ {s['started_at']}")
    
    elif cmd == "end":
        agent = sys.argv[2]
        d = session_end(agent)
        print(f"✅ {agent}: sesión cerrada ({d}s de duración)")
    
    elif cmd == "fail":
        agent = sys.argv[2]
        reason = sys.argv[3] if len(sys.argv) > 3 else "auth"
        c = session_fail(agent, reason)
        print(f"⚠️  {agent}: fallo #{c} — {reason}")
    
    elif cmd == "report":
        for s in session_report():
            icon = {"active":"🟢","closed":"⏸️"}.get(s.get("status",""),"❓")
            d = s.get("duration_sec", 0)
            dur = f"({d}s)" if d else ""
            print(f"  {icon} {s['agent']:10s} {s['status']:8s} {s.get('started_at','')[:19]} {dur}")
    
    elif cmd == "active":
        for s in session_active():
            print(f"  🟢 {s['agent']:10s} desde {s.get('started_at','')[:19]}")
