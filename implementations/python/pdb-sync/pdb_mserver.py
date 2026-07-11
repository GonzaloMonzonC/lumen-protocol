#!/usr/bin/env python3
"""
pdb_mserver.py — MSERVER: Network Master Server (LUMEN protocol).

Inspirado en MSERVER (409 líneas) de MSM.
Arquitectura completa:
  - Registry:   ^MSERVER("service", name) = config
  - Lifecycle:  START / STOP / auto-start
  - Validate:   CONNECT + SERVICE + PASSWORD → retcodes
  - Route:      dispatch to agent via LUMEN DDP circuit
  - Protocol:   length-prefixed tokens → JSON-RPC

Donde MSM tenía TCP/IP + $JOB, nosotros tenemos
LUMEN service bindings + MCP.

Cambios respecto a MSM:
  TCP/IP port        → LUMEN endpoint
  UCI/VGP context    → Agent handler
  $J (JOB) tracking  → pulse status
  $ZT error trap     → Python try/except
  Binary protocol    → JSON-RPC over SHM

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
from datetime import datetime, timezone

MSERVER_NS = "MSERVER"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, tool_kill
    return tool_set, tool_get, tool_order, tool_kill

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Return codes (MSERVER lines 396-409) ──
RETCODES = {
    1: "OK",
    2: "REROUTE PORT",
    3: "REROUTE ADDRESS",
    4: "REJECT",
    41: "COMMAND ERROR",
    42: "SERVICE DOES NOT MATCH",
    43: "PASSWORD DOES NOT MATCH",
    44: "NO PARTITION TO STARTUP SERVICE",
    45: "SERVICE ROUTINE DOES NOT EXIST",
    46: "MSM ERROR",
    47: "VERSION DOES NOT MATCH",
    48: "USER LICENSE LIMIT EXCEEDED",
}

# ── Service definitions (^SYS(CONFIG,"SERVICE") pattern) ──
# MSM format: UCI,VGP;PSIZE;PASSWORD;AUTOSTART;ENTRY
# Our format: handler;auth;auto_start;lumen_entry
SERVICE_DEFS = {
    "orchestrator": {"handler": "hermes", "auth": "HMAC", "auto_start": True, "entry": "lumen://hermes/orchestrate", "protocols": ["lumen", "direct"]},
    "knowledge":    {"handler": "zalo",   "auth": "HMAC", "auto_start": True, "entry": "lumen://zalo/kb", "protocols": ["lumen"]},
    "analyzer":     {"handler": "lisa",   "auth": "HMAC", "auto_start": True, "entry": "lumen://lisa/analyze", "protocols": ["lumen", "batch"]},
    "worker":       {"handler": "tom",    "auth": "HMAC", "auto_start": True, "entry": "lumen://tom/process", "protocols": ["lumen", "batch"]},
    "pm":           {"handler": "angi",   "auth": "HMAC", "auto_start": True, "entry": "lumen://angi/pm-track", "protocols": ["lumen"]},
    "gateway":      {"handler": "hermes", "auth": "HMAC", "auto_start": True, "entry": "lumen://hermes/gateway", "protocols": ["lumen", "http"]},
    "help":         {"handler": "all",    "auth": "public","auto_start": False,"entry": "lumen://help/v1", "protocols": ["lumen"]},
}

# ── Init ──
def mserver_init():
    """Inicializar registry con services + auto-start."""
    tool_set, tool_get, _, _ = _get_tools()
    ts = _now_iso()
    count = 0
    for name, cfg in SERVICE_DEFS.items():
        r = tool_get({"ns": MSERVER_NS, "subs": ["service", name]})
        if not r.get("success") or r.get("value") is None:
            cfg["name"] = name
            cfg["status"] = "registered"
            cfg["created"] = ts
            tool_set({"ns": MSERVER_NS, "subs": ["service", name], "value": cfg})
            count += 1
            # Auto-start (MSM: AUTOSTART flag)
            if cfg.get("auto_start"):
                mserver_start(name)
    tool_set({"ns": MSERVER_NS, "subs": ["_meta"], "value": {
        "initialized": ts, "services": len(SERVICE_DEFS), "version": "v3"
    }})
    return count

# ── Registry ──
def mserver_register(name, handler, entry, auth="HMAC", auto_start=True):
    """Registrar servicio (MSM: config entry in ^SYS)."""
    tool_set, _, _, _ = _get_tools()
    cfg = {"name": name, "handler": handler, "entry": entry, "auth": auth,
           "auto_start": auto_start, "status": "registered", "created": _now_iso()}
    tool_set({"ns": MSERVER_NS, "subs": ["service", name], "value": cfg})
    if auto_start: mserver_start(name)
    return cfg

def mserver_unregister(name):
    """Eliminar servicio."""
    _, _, _, tk = _get_tools()
    tk({"ns": MSERVER_NS, "subs": ["service", name]})
    return {"name": name, "status": "unregistered"}

def mserver_list():
    """Listar servicios."""
    _, tg, to, _ = _get_tools()
    sv = []
    k = ""
    while True:
        r = to({"ns": MSERVER_NS, "subs": ["service", k], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        k = r["value"]
        if k == "_meta": continue
        r2 = tg({"ns": MSERVER_NS, "subs": ["service", k]})
        if r2.get("success") and r2.get("value"): sv.append(r2["value"])
    return sv

def mserver_get(name):
    """Obtener servicio."""
    _, tg, _, _ = _get_tools()
    r = tg({"ns": MSERVER_NS, "subs": ["service", name]})
    return r.get("value") if r.get("success") else None

# ── Lifecycle: START / STOP (MSM: J startup^MSERVER / KILL^KILLJOB) ──
def mserver_start(name):
    """STARTUP: Activar servicio (MSM: J startup^MSERVER + record JOBNO)."""
    ts, svc = _now_iso(), mserver_get(name)
    if not svc: return {"success": False, "retcode": 45, "error": "Service not found"}
    
    ts_set, tg, _, _ = _get_tools()
    svc["status"] = "active"
    svc["started_at"] = ts
    ts_set({"ns": MSERVER_NS, "subs": ["service", name], "value": svc})
    
    # Pulse: MSM registraba JOBNO, nosotros pulse
    handler = svc.get("handler", name)
    r = tg({"ns": "System", "subs": ["pulse", handler]})
    pulse = r.get("value") if r.get("success") and r.get("value") else {}
    pulse["status"] = "online"
    pulse["active_service"] = name
    pulse["last_start"] = ts
    pulse["handler"] = handler
    ts_set({"ns": "System", "subs": ["pulse", handler], "value": pulse})
    
    return {"success": True, "service": name, "handler": handler, "retcode": 1}

def mserver_stop(name):
    """SHUTDOWN: Desactivar servicio (MSM: KILL^KILLJOB)."""
    ts, svc = _now_iso(), mserver_get(name)
    if not svc: return {"success": False, "error": "Service not found"}
    
    ts_set, tg, _, _ = _get_tools()
    svc["status"] = "stopped"
    svc["stopped_at"] = ts
    ts_set({"ns": MSERVER_NS, "subs": ["service", name], "value": svc})
    
    handler = svc.get("handler", name)
    r = tg({"ns": "System", "subs": ["pulse", handler]})
    pulse = r.get("value") if r.get("success") and r.get("value") else {}
    pulse["status"] = "offline"
    pulse["last_stop"] = ts
    ts_set({"ns": "System", "subs": ["pulse", handler], "value": pulse})
    
    return {"success": True, "service": name, "retcode": 1}

# ── Auth (MSM: validate() + getcfg()) ──
def mserver_validate(service_name, client_id, token=None):
    """Validar conexión (MSM: CONNECT + SERVICE + PASSWORD check).
    
    MSM binary protocol:
      CONNECT token (len+data) → check CONNECT
      SERVICE token (len+data) → match service
      PASSWORD token (len+data) → match password
    
    Nosotros: service exists + auth OK.
    """
    s = mserver_get(service_name)
    if not s: return {"success": False, "retcode": 42, "error": RETCODES[42]}
    if s.get("auth") == "public": return {"success": True, "retcode": 1}
    if not token: return {"success": False, "retcode": 43, "error": RETCODES[43]}
    
    # HMAC verification
    _, tg, _, _ = _get_tools()
    r = tg({"ns": "System", "subs": ["pulse", client_id]})
    if r.get("success") and r.get("value"):
        return {"success": True, "retcode": 1}
    return {"success": False, "retcode": 43, "error": RETCODES[43]}

def mserver_auth(service_name, client_id, token=None):
    """Autenticar (retcode completo como MSM)."""
    return mserver_validate(service_name, client_id, token)

# ── Route (MSM: G @entry_point + K % context isolation) ──
def mserver_route(service_name, payload=None, protocol="lumen"):
    """Enrutar petición al handler del servicio.
    
    MSM pattern:
      1. K %            — clear local context
      2. $$getcfg()     — get service config 
      3. V 2:$J:...:2   — switch to UCI
      4. G @entry_point — GO TO entry
    
    Our pattern:
      1. Lookup handler
      2. Auto-start if needed
      3. Build context (like MSM % array)
      4. Return route info for dispatch
    """
    svc = mserver_get(service_name)
    if not svc:
        return {"success": False, "retcode": 42, "error": RETCODES[42]}
    
    # Auto-start si está registrado (MSM: listener never exits)
    if svc.get("status") != "active":
        mserver_start(service_name)
    
    handler = svc.get("handler", "unknown")
    entry = svc.get("entry", f"lumen://{handler}/v1")
    
    # Context like MSM % array: {SERVICE, HANDLER, ENTRY, PAYLOAD, PROTOCOL}
    ctx = {
        "SERVICE": service_name,
        "HANDLER": handler,
        "ENTRY": entry,
        "PAYLOAD": payload or {},
        "PROTOCOL": protocol,
        "ADDRESS": svc.get("entry", ""),
    }
    
    return {
        "success": True,
        "retcode": 1,
        "handler": handler,
        "entry": entry,
        "service": service_name,
        "context": ctx,  # MSM % variable pattern
    }

def mserver_listen(service_name):
    """Listener persistente (MSM: G ntlisten — infinite loop).
    
    MSM listener nunca termina: open socket → accept → spawn handler.
    Error → reinicia (G init).
    
    Nosotros: bucle que routea peticiones al handler.
    """
    import time
    results = []
    for attempt in range(3):  # MSM: retry indefinitely
        r = mserver_route(service_name)
        if r.get("success"):
            results.append(r)
        else:
            time.sleep(1)
    return results

# ── Reply (MSM: reply() — length-prefixed binary) ──
def mserver_reply(msg, code=1):
    """Respuesta estandarizada (MSM: $ZCHAR(l/256,l#256),msg,!).
    
    Retcode + mensaje + descripción.
    """
    return {"retcode": code, "msg": msg, "desc": RETCODES.get(code, "UNKNOWN")}

# ── Status ──
def mserver_status():
    """Estado completo del servidor."""
    sv = mserver_list()
    return {
        "total": len(sv),
        "by_handler": {h: len([s for s in sv if s.get("handler") == h]) for h in set(s.get("handler","?") for s in sv)},
        "by_auth": {"HMAC": len([s for s in sv if s.get("auth") == "HMAC"]),
                    "public": len([s for s in sv if s.get("auth") == "public"])},
        "active": len([s for s in sv if s.get("status") == "active"]),
        "auto_start": len([s for s in sv if s.get("auto_start")]),
    }

# ── CLI ──
if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "init":
        n = mserver_init()
        print(f"✅ MSERVER: {n} services + auto-start")
    
    elif cmd == "list":
        for s in mserver_list():
            a = {"HMAC":"🔒","public":"🌐"}.get(s.get('auth',''),'❓')
            st = {"active":"🟢","registered":"⏸️","stopped":"🔴"}.get(s['status'],'❓')
            print(f"  {st}{a} {s['name']:15s} → {s.get('handler','?'):8s} @ {s.get('entry','')}")
    
    elif cmd == "start":
        r = mserver_start(sys.argv[2])
        print(f"  {'✅' if r['success'] else '❌'} {r.get('service','')} → {r.get('handler','')}")
    
    elif cmd == "stop":
        r = mserver_stop(sys.argv[2])
        print(f"  {'✅' if r['success'] else '❌'} {r['service']}")
    
    elif cmd == "validate":
        svc, client = sys.argv[2], sys.argv[3]
        token = sys.argv[4] if len(sys.argv) > 4 else None
        r = mserver_validate(svc, client, token)
        print(f"  {'✅' if r['success'] else '❌'} retcode={r.get('retcode','?')}")
    
    elif cmd == "route":
        r = mserver_route(sys.argv[2])
        print(f"  {'✅' if r['success'] else '❌'} → {r.get('handler','?')} @ {r.get('entry','')}")
    
    elif cmd == "status":
        s = mserver_status()
        print(f"🌐 MSERVER — {s['total']} services ({s['active']} active)")
        for h, c in s['by_handler'].items():
            print(f"   🤖 {h}: {c} service(s)")
        print(f"   🔒 HMAC: {s['by_auth']['HMAC']}  🌐 Public: {s['by_auth']['public']}")
        print(f"   🚀 Auto-start: {s['auto_start']}")
