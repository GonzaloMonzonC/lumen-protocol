#!/usr/bin/env python3
"""
pdb_agent_workspace.py — Workspace de agente (^UTILITY adaptado).

Cada agente tiene un espacio de trabajo en ^Agent(agent_id, key):
  - Estado efímero (TTL configurable)
  - Preferencias de sesión
  - Cache de operaciones recientes
  - Scratch para cómputos temporales

Diferencia con otros namespaces:
  ^System → config persistente del sistema
  ^CHANGES → journaling de operaciones
  ^DDP → comunicaciones entre agentes
  ^Agent → estado volátil por agente (importa pero expira)

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, json, time
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

AGENT_NS = "Agent"

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── API ─────────────────────────────────────────────────────────────

def ws_set(agent_id, key, value, ttl=3600):
    """Escribir en el workspace de un agente con TTL.
    
    ttl: segundos (default 1h). None = no expira.
    """
    tool_set, _, _, _ = _get_tools()
    entry = {
        "value": value,
        "set_at": _now_iso(),
        "ttl": ttl,
        "expires_at": _now_iso() if ttl is None else (
            datetime.fromtimestamp(time.time() + ttl, tz=timezone.utc).isoformat()
        ),
    }
    tool_set({"ns": AGENT_NS, "subs": [agent_id, "data", key], "value": entry})
    return entry

def ws_get(agent_id, key):
    """Leer del workspace. Si expiró, devuelve None y elimina."""
    _, tool_get, _, tool_kill = _get_tools()
    r = tool_get({"ns": AGENT_NS, "subs": [agent_id, "data", key]})
    if not r.get("success") or not r.get("value"):
        return None
    
    entry = r["value"]
    expires = entry.get("expires_at")
    if expires:
        try:
            exp = datetime.fromisoformat(expires.replace("Z", "+00:00"))
            if datetime.now(timezone.utc) > exp:
                tool_kill({"ns": AGENT_NS, "subs": [agent_id, "data", key]})
                return None
        except: pass
    
    return entry.get("value")

def ws_list(agent_id):
    """Listar todas las claves activas de un agente."""
    _, _, tool_order, _ = _get_tools()
    keys = []
    key = ""
    while True:
        r = tool_order({"ns": AGENT_NS, "subs": [agent_id, "data", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        val = ws_get(agent_id, key)
        if val is not None:
            keys.append(key)
    return keys

def ws_cleanup(agent_id=None):
    """Limpiar entradas expiradas de uno o todos los agentes."""
    _, _, tool_order, tool_kill = _get_tools()
    
    agents = [agent_id] if agent_id else []
    if not agents:
        key = ""
        while True:
            r = tool_order({"ns": AGENT_NS, "subs": [key], "direction": 1})
            if not r.get("success") or r.get("value") is None: break
            key = r["value"]
            if key != "data":
                agents.append(key)
    
    cleaned = 0
    for agent in agents:
        ws_keys = ws_list(agent) if agent else []
        for k in ws_keys:
            if ws_get(agent, k) is None:
                cleaned += 1  # ya se eliminó en ws_get
    return cleaned

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "test"
    
    if cmd == "set":
        agent = sys.argv[2]; key = sys.argv[3]; val = sys.argv[4]
        ws_set(agent, key, val)
        print(f"✅ {agent}:{key} = {val}")
    
    elif cmd == "get":
        agent = sys.argv[2]; key = sys.argv[3]
        val = ws_get(agent, key)
        print(f"  {agent}:{key} = {val}")
    
    elif cmd == "list":
        agent = sys.argv[2]
        for k in ws_list(agent):
            print(f"  {k}")
    
    elif cmd == "test":
        ws_set("hermes", "session-1", {"status": "active", "tasks": 3}, ttl=30)
        ws_set("zalo", "last-query", "¿Qué sabes de PDB?", ttl=60)
        ws_set("lisa", "plan", "Sprint A journaling", ttl=300)
        
        print("📋 Workspace test:")
        for agent in ["hermes", "zalo", "lisa"]:
            keys = ws_list(agent)
            print(f"  {agent}: {len(keys)} keys activas")
            for k in keys:
                print(f"    {k} = {ws_get(agent, k)}")
