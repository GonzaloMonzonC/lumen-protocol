#!/usr/bin/env python3
"""
pdb_watchdog.py — CSFMON: Watchdog con auto-failover.

Inspirado en CSFMON (331 líneas) de MSM.

Mecanismo (Zalo):
  1. Hermes escribe heartbeat en ^CSFMON("watchdog") cada N segundos
  2. Lisa verifica last_seen periódicamente
  3. Si timeout → Lisa toma el control como orquestadora suplente
  4. Cuando Hermes vuelve → Lisa cede el control

Esquema:
  ^CSFMON("watchdog") = {active, heartbeat, last_seen, failover_count}
  ^CSFMON("config") = {interval, timeout, max_retries}
  ^CSFMON("history", ts) = {evento, de, a}

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, time
from datetime import datetime, timezone

CSFMON_NS = "CSFMON"
PRIMARY = "hermes"
SHADOW = "lisa"

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get
    return tool_set, tool_get

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def _get_order():
    from pdb_tools import tool_order
    return tool_order

# ── Config ─────────────────────────────────────────────────────────

def watchdog_config(interval=30, timeout=120, max_retries=3):
    """Configurar watchdog."""
    tool_set, _ = _get_tools()
    config = {
        "interval_sec": interval,
        "timeout_sec": timeout,
        "max_retries": max_retries,
        "primary": PRIMARY,
        "shadow": SHADOW,
        "updated": _now_iso(),
    }
    tool_set({"ns": CSFMON_NS, "subs": ["config"], "value": config})
    return config

def watchdog_get_config():
    """Leer configuración."""
    _, tool_get = _get_tools()
    r = tool_get({"ns": CSFMON_NS, "subs": ["config"]})
    return r.get("value") if r.get("success") and r.get("value") else watchdog_config()

# ── Heartbeat ──────────────────────────────────────────────────────

def watchdog_heartbeat(agent_id=PRIMARY):
    tool_set, tool_get = _get_tools()
    """Escribir heartbeat (llamado por el agente activo)."""
    tool_set, _ = _get_tools()
    ts = _now_iso()
    
    r = tool_get({"ns": CSFMON_NS, "subs": ["watchdog"]})
    wd = r.get("value") if r.get("success") and r.get("value") else {}
    
    # Primera vez o re-asunción
    if not wd.get("active"):
        wd["active"] = agent_id
        wd["failover_count"] = 0
    
    wd["heartbeat"] = ts
    wd["last_seen"] = ts
    wd["status"] = "alive"
    
    tool_set({"ns": CSFMON_NS, "subs": ["watchdog"], "value": wd})
    
    # Actualizar pulse
    r2 = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    pulse = r2.get("value") if r2.get("success") and r2.get("value") else {}
    pulse["last_heartbeat"] = ts
    pulse["status"] = "online"
    tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})
    
    return wd

# ── Check ─────────────────────────────────────────────────────────

def watchdog_check():
    """Verificar salud del agente activo.
    Retorna: ok, failover_needed, detalles."""
    _, tool_get = _get_tools()
    config = watchdog_get_config()
    
    r = tool_get({"ns": CSFMON_NS, "subs": ["watchdog"]})
    wd = r.get("value") if r.get("success") and r.get("value") else {}
    
    if not wd.get("active"):
        return {"ok": False, "reason": "no_active_agent", "failover": False}
    
    last = wd.get("last_seen", "")
    if not last:
        return {"ok": False, "reason": "no_heartbeat", "failover": True}
    
    try:
        last_dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
        age = (datetime.now(timezone.utc) - last_dt).total_seconds()
        timeout = config.get("timeout_sec", 120)
        
        if age > timeout:
            return {"ok": False, "reason": f"timeout ({int(age)}s > {timeout}s)", "failover": True}
        
        return {"ok": True, "reason": "healthy", "age_sec": int(age), "failover": False}
    except:
        return {"ok": False, "reason": "invalid_timestamp", "failover": True}

# ── Failover ───────────────────────────────────────────────────────

def watchdog_failover():
    """Ejecutar failover: Hermes → Lisa."""
    tool_set, tool_get = _get_tools()
    config = watchdog_get_config()
    
    r = tool_get({"ns": CSFMON_NS, "subs": ["watchdog"]})
    wd = r.get("value") if r.get("success") and r.get("value") else {}
    
    old_active = wd.get("active", PRIMARY)
    new_active = SHADOW
    
    # Registrar failover en historial
    ts = _now_iso()
    tool_set({"ns": CSFMON_NS, "subs": ["history", ts], "value": {
        "event": "failover",
        "from": old_active,
        "to": new_active,
        "reason": wd.get("status", "timeout"),
        "timestamp": ts,
    }})
    
    # Actualizar watchdog
    wd["active"] = new_active
    wd["failover_count"] = wd.get("failover_count", 0) + 1
    wd["status"] = "failover"
    wd["last_failover"] = ts
    tool_set({"ns": CSFMON_NS, "subs": ["watchdog"], "value": wd})
    
    # Notificar a Lisa
    tool_set({"ns": "System", "subs": ["pulse", new_active], "value": {
        "status": "online",
        "role": "active_orchestrator",
        "last_heartbeat": ts,
        "notice": f"Failover from {old_active}",
    }})
    
    return {"from": old_active, "to": new_active, "count": wd["failover_count"]}

# ── Recovery ───────────────────────────────────────────────────────

def watchdog_recover():
    """Hermes retoma el control (cuando vuelve)."""
    tool_set, tool_get = _get_tools()
    ts = _now_iso()
    
    r = tool_get({"ns": CSFMON_NS, "subs": ["watchdog"]})
    wd = r.get("value") if r.get("success") and r.get("value") else {}
    
    old_active = wd.get("active", SHADOW)
    
    tool_set({"ns": CSFMON_NS, "subs": ["history", ts], "value": {
        "event": "recovery",
        "from": old_active,
        "to": PRIMARY,
        "timestamp": ts,
    }})
    
    # Hermes retoma
    return watchdog_heartbeat(PRIMARY)

# ── Status ─────────────────────────────────────────────────────────

def watchdog_status():
    """Estado completo del watchdog."""
    _, tool_get = _get_tools()
    config = watchdog_get_config()
    
    r = tool_get({"ns": CSFMON_NS, "subs": ["watchdog"]})
    wd = r.get("value") if r.get("success") and r.get("value") else {}
    
    check = watchdog_check()
    
    return {
        "active_agent": wd.get("active", "none"),
        "status": wd.get("status", "unknown"),
        "last_heartbeat": wd.get("last_seen", "never"),
        "failover_count": wd.get("failover_count", 0),
        "health": check,
        "config": config,
    }

# ── CLI ──

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    
    if cmd == "heartbeat":
        agent = sys.argv[2] if len(sys.argv) > 2 else PRIMARY
        watchdog_heartbeat(agent)
        print(f"💓 {agent}: heartbeat")
    
    elif cmd == "check":
        c = watchdog_check()
        icon = "✅" if c['ok'] else "🔴"
        print(f"{icon} Health: {c['reason']}")
        if c.get('failover'):
            print("  ⚠️  Failover needed!")
    
    elif cmd == "failover":
        r = watchdog_failover()
        print(f"🔄 Failover: {r['from']} → {r['to']} (#{r['count']})")
    
    elif cmd == "recover":
        watchdog_recover()
        print(f"🔄 {PRIMARY} retomó el control")
    
    elif cmd == "status":
        s = watchdog_status()
        icon = {"alive": "🟢", "failover": "🟡", "unknown": "🔴"}.get(s['status'], "❓")
        h = s['health']
        print(f"{icon} Watchdog: {s['active_agent']} ({s['status']})")
        print(f"   Failovers: {s['failover_count']}")
        print(f"   Health: {h['reason']}")
        print(f"   Config: interval={s['config']['interval_sec']}s timeout={s['config']['timeout_sec']}s")
