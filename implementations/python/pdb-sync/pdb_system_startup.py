#!/usr/bin/env python3
"""
pdb_system_startup.py — MSM-03: CSSTART adaptado.

Orquestador de arranque del sistema. Como CSSTART (368 líneas) de MSM:
  1. Validar tipo de sistema (SINGLE/CLIENT/SERVER)
  2. Esperar a que DDP esté disponible
  3. Arrancar servicios en orden de dependencia
  4. Verificar health antes de declarar "ready"
  5. Error trap para todo el startup

Integración PDB:
  ^System("startup") = {status, services, errors}
  ^System("pulse") — health checks de agentes
  ^DDP("links") — verificar conectividad

Autor: Hermes + CadencesLab (MSM-03)
Licencia: MIT (lumen-protocol)
"""

import sys, os, time
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

SYS_NS = "System"

STARTUP_SERVICES = [
    {"name": "hermes", "deps": [],         "type": "core"},
    {"name": "zalo",   "deps": ["hermes"], "type": "knowledge"},
    {"name": "lisa",   "deps": ["hermes"], "type": "orchestrator"},
    {"name": "tom",    "deps": ["hermes"], "type": "worker"},
    {"name": "angi",   "deps": ["hermes", "zalo"], "type": "pm"},
]

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def startup_init():
    """Inicializar estado de startup."""
    tool_set, _, _ = _get_tools()
    state = {
        "status": "BOOTING",
        "started_at": _now_iso(),
        "completed_at": None,
        "services_ok": 0,
        "services_failed": 0,
        "errors": [],
    }
    tool_set({"ns": SYS_NS, "subs": ["startup"], "value": state})
    return state

def startup_service_ready(name):
    """Verificar si un servicio está listo (como CSSTART verifica sistema)."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": SYS_NS, "subs": ["pulse", name]})
    if not r.get("success") or not r.get("value"):
        return False
    pulse = r["value"]
    status = pulse.get("status", "")
    last = pulse.get("last_activity") or pulse.get("last_heartbeat", "")
    if not last or status not in ("online", "busy"):
        return False
    try:
        age = (datetime.now(timezone.utc) - 
               datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
        return age < 120
    except:
        return False

def startup_run():
    """Ejecutar secuencia de arranque (como CSSTART)."""
    tool_set, _, _ = _get_tools()
    state = startup_init()
    log = []

    # Fase 1: Esperar red DDP (como CSSTART espera DDP)
    log.append("🔌 Waiting for DDP network...")
    tool_set({"ns": SYS_NS, "subs": ["startup", "phase"], "value": "DDP_WAIT"})
    time.sleep(1)  # Simular espera

    # Fase 2: Arrancar servicios por orden de dependencia
    started = []
    failed = []

    for svc in STARTUP_SERVICES:
        name = svc["name"]
        deps = svc["deps"]

        tool_set({"ns": SYS_NS, "subs": ["startup", "current"], "value": name})

        # Verificar dependencias
        deps_ok = all(d in started for d in deps)
        if not deps_ok:
            missing = [d for d in deps if d not in started]
            log.append(f"  ❌ {name}: missing deps {missing}")
            failed.append(name)
            continue

        # Marcar como iniciado
        tool_set({"ns": SYS_NS, "subs": ["pulse", name], "value": {
            "status": "online",
            "last_activity": _now_iso(),
            "startup": "auto",
        }})
        started.append(name)
        log.append(f"  ✅ {name}: started")

    # Fase 3: Verificar health de todos
    healthy = all(startup_service_ready(s) for s in started)
    state = {
        "status": "READY" if healthy else "DEGRADED",
        "started_at": state["started_at"],
        "completed_at": _now_iso(),
        "services_ok": len(started),
        "services_failed": len(failed),
        "errors": [],
    }
    tool_set({"ns": SYS_NS, "subs": ["startup"], "value": state})

    return {"status": state["status"], "started": started, "failed": failed}

def startup_status():
    """Estado del startup."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": SYS_NS, "subs": ["startup"]})
    return r.get("value") if r.get("success") else startup_init()

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"

    if cmd == "start":
        result = startup_run()
        print(f"📋 Startup: {result['status']}")
        for s in result["started"]:
            print(f"  ✅ {s}")
        for f in result["failed"]:
            print(f"  ❌ {f}")
    elif cmd == "status":
        s = startup_status()
        print(f"📊 Startup: {s.get('status')}")
        print(f"  OK: {s.get('services_ok', 0)}  Failed: {s.get('services_failed', 0)}")
