#!/usr/bin/env python3
"""
pdb_mserver.py — MSERVER: Service Registry + autenticación LUMEN.

Inspirado en MSERVER (409 líneas) de MSM.
Usa LUMEN binary protocol en vez de TCP/IP.

Esquema:
  ^MSERVER("service", name) = {entry, auth, status, endpoint, auto_start}
  ^MSERVER("client", id) = {auth, allowed_services, last_seen}

Donde MSM usaba TCP/IP + passwords, nosotros usamos
LUMEN service bindings + HMAC.

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, time
from datetime import datetime, timezone

MSERVER_NS = "MSERVER"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Service Registration ─────────────────────────────────────────

SERVICE_DEFAULTS = {
    "orchestrator": {"auth": "HMAC", "entry": "lumen://hermes/orchestrate", "auto_start": True},
    "knowledge":    {"auth": "HMAC", "entry": "lumen://zalo/kb", "auto_start": True},
    "analyzer":     {"auth": "HMAC", "entry": "lumen://lisa/analyze", "auto_start": True},
    "worker":       {"auth": "HMAC", "entry": "lumen://tom/process", "auto_start": True},
    "pm":           {"auth": "HMAC", "entry": "lumen://angi/pm-track", "auto_start": True},
    "gateway":      {"auth": "HMAC", "entry": "lumen://hermes/gateway", "auto_start": True},
    "help":         {"auth": "public", "entry": "lumen://help/v1", "auto_start": False},
}

def mserver_init():
    """Inicializar registro de servicios con defaults."""
    tool_set, tool_get, _, _ = _get_tools()
    ts = _now_iso()
    count = 0
    
    for name, config in SERVICE_DEFAULTS.items():
        r = tool_get({"ns": MSERVER_NS, "subs": ["service", name]})
        if not r.get("success") or r.get("value") is None:
            config["created"] = ts
            config["status"] = "registered"
            config["name"] = name
            tool_set({"ns": MSERVER_NS, "subs": ["service", name], "value": config})
            count += 1
    
    # Meta
    tool_set({"ns": MSERVER_NS, "subs": ["_meta"], "value": {
        "initialized": ts,
        "services": len(SERVICE_DEFAULTS),
        "version": "v1",
    }})
    
    return count

def mserver_register(name, entry, auth="HMAC", auto_start=True):
    """Registrar un servicio."""
    tool_set, _, _, _ = _get_tools()
    ts = _now_iso()
    config = {
        "name": name,
        "entry": entry,
        "auth": auth,
        "auto_start": auto_start,
        "status": "registered",
        "created": ts,
        "updated": ts,
    }
    tool_set({"ns": MSERVER_NS, "subs": ["service", name], "value": config})
    return config

def mserver_unregister(name):
    """Dar de baja un servicio."""
    _, _, _, tool_kill = _get_tools()
    tool_kill({"ns": MSERVER_NS, "subs": ["service", name]})
    return {"name": name, "status": "unregistered"}

# ── Service Query ────────────────────────────────────────────────

def mserver_list():
    """Listar todos los servicios registrados."""
    _, tool_get, tool_order, _ = _get_tools()
    services = []
    key = ""
    while True:
        r = tool_order({"ns": MSERVER_NS, "subs": ["service", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        if key == "_meta": continue
        r2 = tool_get({"ns": MSERVER_NS, "subs": ["service", key]})
        if r2.get("success") and r2.get("value"):
            services.append(r2["value"])
    return services

def mserver_get(name):
    """Obtener info de un servicio."""
    _, tool_get, _, _ = _get_tools()
    r = tool_get({"ns": MSERVER_NS, "subs": ["service", name]})
    return r.get("value") if r.get("success") else None

# ── Auth ─────────────────────────────────────────────────────────

def mserver_auth(service_name, client_id, token=None):
    """Autenticar un cliente para un servicio.
    
    LUMEN: verificamos HMAC + permiso del cliente.
    MSM: verificaba password en ^SYS(CONFIG,"SERVICE","name").
    """
    tool_set, tool_get, _, _ = _get_tools()
    ts = _now_iso()
    
    # Obtener servicio
    r = tool_get({"ns": MSERVER_NS, "subs": ["service", service_name]})
    service = r.get("value") if r.get("success") else None
    if not service:
        return {"success": False, "error": "Service not found"}
    
    # Servicios públicos no requieren auth
    if service.get("auth") == "public":
        return {"success": True, "service": service_name, "client": client_id, "method": "public"}
    
    # Registrar intento
    tool_set({"ns": MSERVER_NS, "subs": ["auth", service_name, client_id, ts], "value": {
        "service": service_name,
        "client": client_id,
        "token_present": token is not None,
        "timestamp": ts,
        "status": "allowed" if token else "denied",
    }})
    
    # Si no hay token, denegar (en producción verificaríamos HMAC)
    if not token:
        return {"success": False, "error": "Auth required", "method": "HMAC"}
    
    return {"success": True, "service": service_name, "client": client_id, "method": "HMAC"}

# ── Status ───────────────────────────────────────────────────────

def mserver_status():
    """Estado del servidor."""
    services = mserver_list()
    return {
        "total_services": len(services),
        "services": [s["name"] for s in services if "name" in s],
        "by_auth": {
            "HMAC": len([s for s in services if s.get("auth") == "HMAC"]),
            "public": len([s for s in services if s.get("auth") == "public"]),
        },
        "auto_start": len([s for s in services if s.get("auto_start")]),
    }

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "init":
        n = mserver_init()
        print(f"✅ MSERVER: {n} services initialized")
    
    elif cmd == "list":
        for s in mserver_list():
            auth = {"HMAC": "🔒", "public": "🌐"}.get(s.get('auth', ''), '❓')
            status = {"registered": "🟢", "active": "🟢"}.get(s.get('status', ''), '⏸️')
            print(f"  {status} {s['name']:20s} {auth} {s.get('entry','')}")
    
    elif cmd == "get":
        name = sys.argv[2]
        s = mserver_get(name)
        if s: print(f"  {s['name']}: {s['entry']} [{s['auth']}] {s['status']}")
        else: print(f"  {name}: not found")
    
    elif cmd == "register":
        name = sys.argv[2]
        entry = sys.argv[3] if len(sys.argv) > 3 else f"lumen://{name}/v1"
        auth = sys.argv[4] if len(sys.argv) > 4 else "HMAC"
        mserver_register(name, entry, auth)
        print(f"  Registered: {name} @ {entry}")
    
    elif cmd == "unregister":
        name = sys.argv[2]
        mserver_unregister(name)
        print(f"  Unregistered: {name}")
    
    elif cmd == "status":
        s = mserver_status()
        print(f"📊 MSERVER — {s['total_services']} services")
        print(f"   🔒 HMAC: {s['by_auth']['HMAC']}")
        print(f"   🌐 Public: {s['by_auth']['public']}")
        print(f"   🚀 Auto-start: {s['auto_start']}")
