#!/usr/bin/env python3
"""
pdb_rthist.py — RTHIST: Histórico de rendimiento PDB.

Inspirado en RTHIST (334 líneas) de MSM pero con 3 métricas clave:
  1. Operaciones PDB (SETs/KILLs/errores) por hora
  2. Tiempo de respuesta por agente
  3. Namespaces más accedidos

Zalo: "%SS = tiempo real, RTHIST = tendencia"
Sin polling. Agregación cada hora desde job ligero.

Esquema:
  ^RTHIST("ops", YYYY-MM-DD, HH) = sets:kills:errors
  ^RTHIST("agents", YYYY-MM-DD, HH, agent) = avg_ms:calls
  ^RTHIST("namespaces", YYYY-MM-DD, HH, ns) = accesses

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
from datetime import datetime, timezone, timedelta

RTHIST_NS = "RTHIST"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _hour_key():
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%d"), str(now.hour)

# ── Record metrics ───────────────────────────────────────────────

def rthist_record_ops(sets=0, kills=0, errors=0):
    """Registrar operaciones de la hora actual."""
    tool_set, tool_get, _ = _get_tools()
    date, hour = _hour_key()
    
    r = tool_get({"ns": RTHIST_NS, "subs": ["ops", date, hour]})
    prev = r.get("value") if r.get("success") and r.get("value") else {"sets": 0, "kills": 0, "errors": 0}
    
    tool_set({"ns": RTHIST_NS, "subs": ["ops", date, hour], "value": {
        "sets": prev.get("sets", 0) + sets,
        "kills": prev.get("kills", 0) + kills,
        "errors": prev.get("errors", 0) + errors,
        "updated": _now_iso(),
    }})

def rthist_record_agent(agent_id, response_ms=0, calls=1):
    """Registrar tiempo de respuesta de un agente."""
    tool_set, tool_get, _ = _get_tools()
    date, hour = _hour_key()
    
    r = tool_get({"ns": RTHIST_NS, "subs": ["agents", date, hour, agent_id]})
    prev = r.get("value") if r.get("success") and r.get("value") else {"avg_ms": 0, "calls": 0, "total_ms": 0}
    
    total_ms = prev.get("total_ms", 0) + response_ms
    total_calls = prev.get("calls", 0) + calls
    
    tool_set({"ns": RTHIST_NS, "subs": ["agents", date, hour, agent_id], "value": {
        "avg_ms": round(total_ms / max(total_calls, 1), 1),
        "calls": total_calls,
        "total_ms": total_ms,
        "updated": _now_iso(),
    }})

def rthist_record_namespace(ns, accesses=1):
    """Registrar acceso a un namespace."""
    tool_set, tool_get, _ = _get_tools()
    date, hour = _hour_key()
    
    r = tool_get({"ns": RTHIST_NS, "subs": ["namespaces", date, hour, ns]})
    prev = r.get("value") if r.get("success") and r.get("value") else {"accesses": 0}
    
    tool_set({"ns": RTHIST_NS, "subs": ["namespaces", date, hour, ns], "value": {
        "accesses": prev.get("accesses", 0) + accesses,
        "updated": _now_iso(),
    }})

# ── Aggregation job ──────────────────────────────────────────────

def rthist_snapshot():
    """Tomar snapshot de métricas actuales para la hora.
    Llámese cada hora (cron o job ligero)."""
    _, tool_get, _ = _get_tools()
    
    # Métricas del journal
    r = tool_get({"ns": "CHANGES", "subs": ["control"]})
    ctrl = r.get("value") if r.get("success") else {}
    sets = ctrl.get("sets", 0)
    kills = ctrl.get("kills", 0)
    
    # Métricas de errores
    _, _, tool_order = _get_tools()
    errors = 0
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["errors", key], "direction": -1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        errors += 1
        if errors > 10: break
    
    # Registrar
    rthist_record_ops(sets, kills, errors)
    
    # Registrar pulse de agentes
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["pulse", key]})
        if r2.get("success") and r2.get("value"):
            p = r2["value"]
            load = p.get("load", 0)
            rthist_record_agent(key, load * 10, 1)
    
    return {"ops": {"sets": sets, "kills": kills, "errors": errors}}

# ── Queries ──────────────────────────────────────────────────────

def rthist_ops_last_24h():
    """Obtener operaciones de las últimas 24h."""
    _, tool_get, tool_order = _get_tools()
    now = datetime.now(timezone.utc)
    data = []
    
    for h in range(24):
        dt = now - timedelta(hours=h)
        date = dt.strftime("%Y-%m-%d")
        hour = str(dt.hour)
        
        r = tool_get({"ns": RTHIST_NS, "subs": ["ops", date, hour]})
        if r.get("success") and r.get("value"):
            v = r["value"]
            data.append({"hour": f"{date} {hour}:00", **v})
    
    return data

def rthist_agents_last_24h():
    """Obtener métricas de agentes últimas 24h."""
    _, tool_get, tool_order = _get_tools()
    now = datetime.now(timezone.utc)
    data = {}
    
    for h in range(24):
        dt = now - timedelta(hours=h)
        date = dt.strftime("%Y-%m-%d")
        hour = str(dt.hour)
        
        key = ""
        while True:
            r = tool_order({"ns": RTHIST_NS, "subs": ["agents", date, hour, key], "direction": 1})
            if not r.get("success") or r.get("value") is None: break
            key = r["value"]
            r2 = tool_get({"ns": RTHIST_NS, "subs": ["agents", date, hour, key]})
            if r2.get("success") and r2.get("value"):
                if key not in data: data[key] = {"calls": 0, "total_ms": 0, "hours": 0}
                v = r2["value"]
                data[key]["calls"] += v.get("calls", 0)
                data[key]["total_ms"] += v.get("total_ms", 0)
                data[key]["hours"] += 1
    
    for a in data:
        data[a]["avg_ms"] = round(data[a]["total_ms"] / max(data[a]["calls"], 1), 1)
    return data

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    
    if cmd == "snapshot":
        r = rthist_snapshot()
        print(f"📊 Snapshot: {r['ops']['sets']} SETs, {r['ops']['kills']} KILLs, {r['ops']['errors']} errors")
    
    elif cmd == "ops":
        for d in sorted(rthist_ops_last_24h(), key=lambda x: x['hour']):
            print(f"  {d['hour']}: SETs={d['sets']} KILLs={d['kills']} errors={d['errors']}")
    
    elif cmd == "agents":
        for a, d in sorted(rthist_agents_last_24h().items()):
            print(f"  {a:10s} avg={d['avg_ms']}ms calls={d['calls']} ({d['hours']}h)")
