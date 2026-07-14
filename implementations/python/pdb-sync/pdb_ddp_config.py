#!/usr/bin/env python3
"""
pdb_ddp_config.py — B2: SGDDP configuración de sistema DDP.

Basado en SGDDP (197 líneas), SGDDP2 (301 líneas), STUDDP (155) de MSM.

Configuración de enlaces DDP: direcciones, tipos, puertos, timeouts.
Usa ^System("ddp",...) como raíz de configuración.
Cada nodo define sus conexiones en ^System("ddp","links",nombre).

Autor: Hermes + CadencesLab (B2 — Sprint B MSM→Lumen)
Licencia: MIT (lumen-protocol)
"""

import sys, os
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

LINK_TYPES = {
    "service-binding": 0,
    "http": 1,
    "shared-memory": 3,
    "internal": 4,
}

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── DDP Config (SGDDP) ─────────────────────────────────────────────

def ddp_config_get():
    """Leer configuración DDP actual."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": "System", "subs": ["ddp"]})
    return r.get("value") if r.get("success") else None

def ddp_config_set(config):
    """Escribir configuración DDP."""
    tool_set, _, _ = _get_tools()
    tool_set({"ns": "System", "subs": ["ddp"], "value": config})

def ddp_config_init():
    """Inicializar configuración DDP por defecto."""
    tool_set, _, _ = _get_tools()
    default = {
        "max_links": 16,
        "buffer_size": 1500,
        "circuit_buffers": 5,
        "max_messages": 4,
        "timeout": 30,
        "created": _now(),
        "updated": _now(),
    }
    tool_set({"ns": "System", "subs": ["ddp"], "value": default})
    return default

# ── Link config (SGDDP2) ───────────────────────────────────────────

def ddp_link_config(name, target_url=None, link_type="service-binding", port=None, ip_addr=None, timeout=None):
    """Configurar un enlace DDP (como SGDDP2 LNKUNIX)."""
    tool_set, tool_get, _ = _get_tools()
    
    config = tool_get({"ns": "System", "subs": ["ddp", "links", name]})
    link = config.get("value") if config.get("success") else {
        "name": name,
        "created": _now(),
    }
    
    if target_url: link["target"] = target_url
    if link_type: link["type"] = LINK_TYPES.get(link_type, 0)
    if port: link["port"] = port
    if ip_addr: link["ip"] = ip_addr
    if timeout is not None: link["timeout"] = timeout
    
    link["updated"] = _now()
    tool_set({"ns": "System", "subs": ["ddp", "links", name], "value": link})
    return link

def ddp_link_get(name):
    """Leer configuración de un enlace."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": "System", "subs": ["ddp", "links", name]})
    return r.get("value") if r.get("success") else None

def ddp_link_list():
    """Listar todos los enlaces configurados."""
    _, _, tool_order = _get_tools()
    links = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["ddp", "links", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        link = ddp_link_get(key)
        if link: links.append(link)
    return links

# ── Node config (indentidad SGDDP) ─────────────────────────────────

def ddp_node_config(agent_id, hostname=None, port=None, capabilities=None):
    """Configurar nodo DDP (como SGDDPNT)."""
    tool_set, tool_get, _ = _get_tools()
    r = tool_get({"ns": "System", "subs": ["identidad", agent_id]})
    agent = r.get("value") if r.get("success") else {}
    
    if hostname: agent["hostname"] = hostname
    if port: agent["port"] = port
    if capabilities: agent["capabilities"] = capabilities
    agent["updated"] = _now()
    agent.setdefault("registered", _now())
    
    tool_set({"ns": "System", "subs": ["identidad", agent_id], "value": agent})
    return agent

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "init":
        cfg = ddp_config_init()
        print(f"Config: {cfg}")
    elif cmd == "link":
        name = sys.argv[2]
        target = sys.argv[3] if len(sys.argv) > 3 else None
        link = ddp_link_config(name, target)
        print(f"Link {name}: {target or ''}")
    elif cmd == "links":
        for l in ddp_link_list():
            t = {0: "SB", 1: "HTTP", 3: "SHM", 4: "INT"}.get(l.get("type", 0), "?")
            print(f"  🔗 {l['name']:20s} → {l.get('target','?')} ({t})")
    elif cmd == "node":
        agent = sys.argv[2]
        host = sys.argv[3] if len(sys.argv) > 3 else None
        cfg = ddp_node_config(agent, host)
        print(f"Node {agent}: {cfg.get('hostname','?')}")
    else:
        cfg = ddp_config_get()
        if not cfg:
            print("No config. Use 'init' first.")
        else:
            print(f"Config: max_links={cfg.get('max_links')} buf_size={cfg.get('buffer_size')}")
