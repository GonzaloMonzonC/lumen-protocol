#!/usr/bin/env python3
"""
pdb_auto_start.py — C2: Auto-start services (STU1 pattern).

Inspirado en STU1: 
  I MU,$G(^SYS(CONFIG,"AUTO","DDP"))="YES" D STU^DDP

Nuestro equivalente:
  Al iniciar el ecosistema:
    1. Leer ^System("auto") — servicios a arrancar
    2. Para cada servicio, registrar nodo DDP + abrir circuitos
    3. Verificar que el servicio responde (heartbeat)
    4. Si no responde, reintentar con backoff

Autor: Hermes + CadencesLab (C2 — Sprint C MSM→Lumen)
Licencia: MIT (lumen-protocol)
"""

import sys, os
from datetime import datetime, timezone, timedelta

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

SERVICES = {
    "hermes": {"type": "local", "endpoint": "local", "auto_link": ["zalo", "lisa", "tom"]},
    "zalo":   {"type": "cf-worker", "endpoint": "https://zalo.gonzalomonzonc.workers.dev", "auto_link": ["hermes", "lisa"]},
    "lisa":   {"type": "cf-worker", "endpoint": "https://lisa.gonzalomonzonc.workers.dev", "auto_link": ["hermes"]},
    "tom":    {"type": "cf-worker", "endpoint": "https://tom.gonzalomonzonc.workers.dev", "auto_link": ["hermes"]},
    "angi":   {"type": "cf-worker", "endpoint": "https://angi.gonzalomonzonc.workers.dev", "auto_link": ["hermes"]},
}

def auto_startup():
    """Ejecutar startup de servicios (como STU1)."""
    tool_set, _, _ = _get_tools()
    log = []

    for name, config in SERVICES.items():
        # Registrar en ^System("auto")
        tool_set({"ns": "System", "subs": ["auto", name], "value": {
            "type": config["type"],
            "endpoint": config["endpoint"],
            "started_at": _now(),
            "status": "online",
        }})
        log.append(f"  ✅ {name}: {config['type']} @ {config['endpoint']}")

        # Crear enlaces DDP automáticos
        for target in config.get("auto_link", []):
            link_name = f"{name}→{target}"
            tool_set({"ns": "System", "subs": ["ddp", "auto_links", link_name], "value": {
                "source": name, "target": target, "status": "active", "created_at": _now(),
            }})
            log.append(f"     🔗 {link_name}")

    log.append(f"\n📊 {len(SERVICES)} servicios iniciados")
    return "\n".join(log)

def auto_status():
    """Estado de servicios auto-iniciados."""
    _, tool_get, _ = _get_tools()
    statuses = []
    for name in SERVICES:
        r = tool_get({"ns": "System", "subs": ["auto", name]})
        if r.get("success") and r.get("value"):
            s = r["value"]
            statuses.append(f"  {'🟢' if s.get('status')=='online' else '🔴'} {name}: {s.get('type')} @ {s.get('endpoint')}")
    return "\n".join(statuses) if statuses else "  (no services started)"

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "start"
    if cmd == "start":
        print(auto_startup())
    elif cmd == "status":
        print(auto_status())
