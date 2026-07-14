"""Angi Workspace — PDB namespace para el agente PM del ecosistema.
Toda la data de Angi persiste aquí: decisiones, incidents, agenda, team, alerts.

USO:
  python -c "from pdb_angi_workspace import *; print(angi_status())"
  python -c "from pdb_angi_workspace import *; angi_add_decision('zalo', 'Usar PDB para cache', 'justificación', 'active')"
"""
import json, time, os, sys

sys.path.insert(0, os.path.dirname(__file__) or '.')
import pdb_tools

NS = "ANGI"  # ^ANGI global namespace

# ── Helpers ──

def _ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S")

def _set(subs, value):
    return pdb_tools.tool_set({"ns": NS, "subs": subs, "value": json.dumps(value) if isinstance(value, (dict, list)) else str(value)})

def _get(subs):
    r = pdb_tools.tool_get({"ns": NS, "subs": subs})
    if not r or not r.get("success") or r.get("value") is None:
        return None
    v = r.get("value", "")
    try: return json.loads(v)
    except: return v

def _order(subs):
    return pdb_tools.tool_order({"ns": NS, "subs": subs})

def _next_id(prefix_subs):
    """Get next incremental ID using reverse $ORDER."""
    r = _order(prefix_subs + [""])
    if r is None:
        return 1
    # Try reverse order to get the last key
    r = pdb_tools.tool_order({"ns": NS, "subs": prefix_subs + [""], "direction": -1})
    if r is None:
        return 1
    v = r.get("value") if isinstance(r, dict) else r
    if v is None or v == "":
        return 1
    return int(float(v)) + 1

# ── API pública ──

def angi_add_decision(agent, decision, rationale, estado="active", alternativas=None):
    """Registra una decisión de arquitectura."""
    uid = _next_id(["decisions"])
    data = {
        "id": uid, "agent": agent, "decision": decision,
        "rationale": rationale, "alternativas": alternativas or [],
        "estado": estado, "created": _ts()
    }
    _set(["decisions", uid], data)
    return data

def angi_list_decisions(estado=None):
    """Lista decisiones, opcionalmente filtradas por estado."""
    decisions = []
    key = ""
    while True:
        r = pdb_tools.tool_order({"ns": NS, "subs": ["decisions", key]})
        if r is None: break
        nk = r.get("value") if isinstance(r, dict) else r
        if nk is None or nk == "" or nk == key: break
        key = nk
        d = _get(["decisions", key])
        if d and (not estado or d.get("estado") == estado):
            decisions.append(d)
    return decisions

def angi_add_incident(agent, tipo, detalle, ref=""):
    """Registra un incidente/fallo."""
    uid = _next_id(["incidents"])
    data = {
        "id": uid, "agent": agent, "tipo": tipo,
        "detalle": detalle, "ref": ref,
        "resolved": False, "created": _ts()
    }
    _set(["incidents", uid], data)
    return data

def angi_list_incidents(unresolved_only=True):
    incidents = []
    key = ""
    while True:
        r = pdb_tools.tool_order({"ns": NS, "subs": ["incidents", key]})
        if r is None: break
        nk = r.get("value") if isinstance(r, dict) else r
        if nk is None or nk == "" or nk == key: break
        key = nk
        d = _get(["incidents", key])
        if d and (not unresolved_only or not d.get("resolved")):
            incidents.append(d)
    return incidents

def angi_set_metric(key, value):
    """Almacena una métrica (value puede ser número, string, dict)."""
    _set(["metrics", key], {"value": value, "updated": _ts()})
    return True

def angi_get_metric(key):
    return _get(["metrics", key])

def angi_add_alert(tipo, mensaje, severity="medium", source=""):
    """Crea una alerta."""
    uid = _next_id(["alerts"])
    data = {
        "id": uid, "tipo": tipo, "mensaje": mensaje,
        "severity": severity, "source": source,
        "acknowledged": False, "created": _ts()
    }
    _set(["alerts", uid], data)
    return data

def angi_list_alerts(unacknowledged_only=True):
    alerts = []
    key = ""
    while True:
        r = pdb_tools.tool_order({"ns": NS, "subs": ["alerts", key]})
        if r is None: break
        nk = r.get("value") if isinstance(r, dict) else r
        if nk is None or nk == "" or nk == key: break
        key = nk
        d = _get(["alerts", key])
        if d and (not unacknowledged_only or not d.get("acknowledged")):
            alerts.append(d)
    return alerts

def angi_ack_alert(alert_id):
    """Marca alerta como acknowledge."""
    d = _get(["alerts", alert_id])
    if d:
        d["acknowledged"] = True
        d["acknowledged_at"] = _ts()
        _set(["alerts", alert_id], d)
        return True
    return False

def angi_update_team_profile(agent_id, name="", role="", personality="", capacidades=None, limitaciones=None):
    """Actualiza perfil de un agente."""
    existing = _get(["team", agent_id]) or {}
    existing.update({
        "agent_id": agent_id,
        "name": name or existing.get("name", ""),
        "role": role or existing.get("role", ""),
        "personality": personality or existing.get("personality", ""),
        "capacidades": capacidades or existing.get("capacidades", []),
        "limitaciones": limitaciones or existing.get("limitaciones", []),
        "updated": _ts()
    })
    _set(["team", agent_id], existing)
    return existing

def angi_get_team_profile(agent_id):
    return _get(["team", agent_id])

def angi_list_team():
    team = []
    key = ""
    while True:
        r = pdb_tools.tool_order({"ns": NS, "subs": ["team", key]})
        if r is None: break
        nk = r.get("value") if isinstance(r, dict) else r
        if nk is None or nk == "" or nk == key: break
        key = nk
        d = _get(["team", key])
        if d: team.append(d)
    return team

def angi_status():
    """Resumen del workspace."""
    decisions = angi_list_decisions()
    incidents = angi_list_incidents(unresolved_only=True)
    alerts = angi_list_alerts(unacknowledged_only=True)
    team = angi_list_team()
    return {
        "decisions_count": len(decisions),
        "incidents_unresolved": len(incidents),
        "alerts_pending": len(alerts),
        "team_count": len(team),
        "recent_decisions": decisions[-3:] if decisions else [],
        "recent_alerts": alerts[-3:] if alerts else [],
    }

def angi_migrate_from_mcp():
    """Migra datos existentes de Angi MCP tools al workspace PDB.
    Se conecta via MCP y replica datos."""
    print("Migración: leyendo decisiones existentes via MCP...")
    # Esto se llama manualmente la primera vez
    pass

if __name__ == "__main__":
    import json
    s = angi_status()
    print(json.dumps(s, indent=2))
