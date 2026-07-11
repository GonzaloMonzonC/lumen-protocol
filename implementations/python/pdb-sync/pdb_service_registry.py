#!/usr/bin/env python3
"""
pdb_service_registry.py — Service Registry (^%MSA adaptado).

Inspirado en ^%MSA (265 líneas) de MSM:
  ^%MSA("ActiveCircuits") = "ActivCir^MSASYS(.P1)"

Nuestro: ^System("services", name) = {handler, agent, description}

Cada agente registra sus capacidades aquí. Service Manager (C1)
consulta el registro para saber qué agente puede hacer qué.

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os
from datetime import datetime, timezone

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

SERVICES = [
    {"name": "query",       "agent": "zalo",   "desc": "Consultas de conocimiento", "handler": "zalo_chat"},
    {"name": "analyze",     "agent": "lisa",   "desc": "Análisis profundo", "handler": "lisa_analyze"},
    {"name": "plan",        "agent": "lisa",   "desc": "Planificación de sprints", "handler": "lisa_plan"},
    {"name": "classify",    "agent": "tom",    "desc": "Clasificación de texto", "handler": "tom_classify"},
    {"name": "process",     "agent": "tom",    "desc": "Procesamiento rápido", "handler": "tom_process"},
    {"name": "summarize",   "agent": "tom",    "desc": "Resumen de contenido", "handler": "tom_summarize"},
    {"name": "extract",     "agent": "tom",    "desc": "Extracción estructurada", "handler": "tom_extract"},
    {"name": "transform",   "agent": "tom",    "desc": "Transformación de formatos", "handler": "tom_transform"},
    {"name": "pm-track",    "agent": "angi",   "desc": "Tracking de sprints", "handler": "angi_dashboard"},
    {"name": "build",       "agent": "hermes", "desc": "Construcción de código", "handler": "hermes_build"},
    {"name": "orchestrate", "agent": "hermes", "desc": "Orquestación multi-agente", "handler": "hermes_delegate"},
    {"name": "ddp-send",    "agent": "hermes", "desc": "Envío DDP entre agentes", "handler": "ddp_send"},
    {"name": "ddp-circuit", "agent": "hermes", "desc": "Gestión de circuitos DDP", "handler": "ddp_circuit"},
    {"name": "journal-set", "agent": "hermes", "desc": "SET con journaling", "handler": "journal_record"},
    {"name": "recovery",    "agent": "hermes", "desc": "VERIFY recovery", "handler": "recovery_apply"},
]

def registry_init():
    """Inicializar service registry en ^System("services")."""
    tool_set, _, _ = _get_tools()
    for svc in SERVICES:
        tool_set({"ns": "System", "subs": ["services", "registry", svc["name"]], "value": svc})
        # Índice por agente
        tool_set({"ns": "System", "subs": ["services", "by-agent", svc["agent"], svc["name"]], "value": ""})
    tool_set({"ns": "System", "subs": ["services", "_meta"], "value": {
        "total": len(SERVICES),
        "agents": len(set(s["agent"] for s in SERVICES)),
        "initialized": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }})
    return len(SERVICES)

def registry_lookup(name):
    """Buscar un servicio por nombre."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": "System", "subs": ["services", "registry", name]})
    return r.get("value") if r.get("success") else None

def registry_by_agent(agent_id):
    """Listar servicios de un agente."""
    _, tool_get, tool_order = _get_tools()
    services = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["services", "by-agent", agent_id, key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        svc = registry_lookup(key)
        if svc: services.append(svc)
    return services

def registry_list():
    """Listar todos los servicios."""
    _, tool_get, tool_order = _get_tools()
    services = []
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["services", "registry", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        if key == "_meta": continue
        svc = registry_lookup(key)
        if svc: services.append(svc)
    return services

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "init"
    if cmd == "init":
        n = registry_init()
        print(f"✅ Registry: {n} services from {len(set(s['agent'] for s in SERVICES))} agents")
    elif cmd == "list":
        for s in registry_list():
            print(f"  {s['name']:20s} → {s['agent']:8s}  {s.get('desc','')}")
    elif cmd == "agent":
        agent = sys.argv[2]
        for s in registry_by_agent(agent):
            print(f"  {s['name']:20s}  {s.get('desc','')}")
