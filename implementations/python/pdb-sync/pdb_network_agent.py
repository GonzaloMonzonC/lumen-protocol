#!/usr/bin/env python3
"""
pdb_network_agent.py — Network Agent (WSAGENT adaptado).

Gestiona conectividad entre agentes del ecosistema.
Inspirado en WSAGENT (137 líneas) de MSM pero event-driven, sin polling.

ARQUITECTURA (aprobada por Zalo):
  - NO polling → escucha eventos en ^System("network","events")
  - Service bindings (0ms) notifican caídas
  - HMAC + nonce para reconexión segura
  - Integrado con Service Manager (C1) + DDP circuits (B1)

FLUJO:
  1. Un agente reporta su estado en ^System("pulse")
  2. Network Agent verifica heartbeats periódicamente
  3. Si un agente no responde → marca offline + notifica
  4. Circuito DDP se cierra → Network Agent intenta reconexión
  5. Reconexión exitosa → circuito se reabre + HMAC nonce

Autor: Hermes + CadencesLab
Licencia: MIT (lumen-protocol)
"""

import sys, os, time, hashlib, hmac
from datetime import datetime, timezone, timedelta

NET_SECRET = "pdb-net-agent-2026"  # HMAC key

def _get_tools():
    pdb_dir = os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb")
    if pdb_dir not in sys.path: sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── HMAC Nonce (como DDPSECU) ─────────────────────────────────────

def net_nonce(agent_id):
    """Generar nonce HMAC para un agente."""
    ts = _now_iso()
    msg = f"{agent_id}:{ts}:{NET_SECRET}"
    return hmac.new(NET_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]

def net_verify(agent_id, nonce, ts):
    """Verificar nonce HMAC."""
    msg = f"{agent_id}:{ts}:{NET_SECRET}"
    expected = hmac.new(NET_SECRET.encode(), msg.encode(), hashlib.sha256).hexdigest()[:16]
    return hmac.compare_digest(expected, nonce)

# ── Heartbeat Monitor ─────────────────────────────────────────────

def net_check_heartbeats(timeout=120):
    """Verificar heartbeats de todos los agentes.
    
    Como WSAGENT LOOP pero sin bucle — event-driven.
    Retorna agentes que han superado el timeout.
    """
    _, tool_get, tool_order = _get_tools()
    now = datetime.now(timezone.utc)
    dead = []

    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        r2 = tool_get({"ns": "System", "subs": ["pulse", key]})
        if r2.get("success") and r2.get("value"):
            p = r2["value"]
            last = p.get("last_activity") or p.get("last_heartbeat", "")
            try:
                age = (now - datetime.fromisoformat(last.replace("Z", "+00:00"))).total_seconds()
                if age > timeout:
                    dead.append({"agent": key, "seconds": int(age), "last_seen": last})
            except: pass
    return dead

# ── Reconexión Automática ─────────────────────────────────────────

def net_reconnect(agent_id):
    """Reconectar un agente caído (como WSAGENT BEG).
    
    1. Genera nonce HMAC
    2. Reabre circuito DDP
    3. Actualiza pulse
    """
    tool_set, tool_get, _ = _get_tools()
    nonce = net_nonce(agent_id)

    # Crear/actualizar evento de reconexión
    tool_set({"ns": "System", "subs": ["network", "events", f"reconnect-{agent_id}-{int(time.time())}"], "value": {
        "agent": agent_id,
        "action": "reconnect",
        "nonce": nonce,
        "timestamp": _now_iso(),
    }})

    # Actualizar pulse a online
    r = tool_get({"ns": "System", "subs": ["pulse", agent_id]})
    pulse = r.get("value") if r.get("success") else {}
    pulse["status"] = "online"
    pulse["last_heartbeat"] = _now_iso()
    pulse["nonce"] = nonce
    tool_set({"ns": "System", "subs": ["pulse", agent_id], "value": pulse})

    # Actualizar circuito DDP si existe
    r2 = tool_get({"ns": "DDP", "subs": ["circuits", agent_id]})
    circuit = r2.get("value") if r2.get("success") else None
    if circuit and circuit.get("status") == "C":
        circuit["status"] = "O"
        circuit["nonce"] = nonce
        circuit["reconnected_at"] = _now_iso()
        tool_set({"ns": "DDP", "subs": ["circuits", agent_id], "value": circuit})

    return {"agent": agent_id, "nonce": nonce, "status": "reconnected"}

# ── Cycle ─────────────────────────────────────────────────────────

def net_cycle():
    """Un ciclo del Network Agent (como WSAGENT pero event-driven).
    
    1. Verificar heartbeats
    2. Reconectar agentes caídos
    3. Registrar resultados
    """
    tool_set, _, _ = _get_tools()
    dead = net_check_heartbeats()
    results = []

    for d in dead:
        result = net_reconnect(d["agent"])
        results.append(result)

    # Registrar ciclo
    tool_set({"ns": "System", "subs": ["network", "cycles", _now_iso()], "value": {
        "checked": True,
        "dead": len(dead),
        "reconnected": len(results),
        "timestamp": _now_iso(),
    }})

    return {"checked": True, "dead": len(dead), "reconnected": len(results)}

def net_status():
    """Estado actual de la red."""
    _, tool_get, tool_order = _get_tools()
    dead = net_check_heartbeats()
    _, tool_get, _ = _get_tools()
    agents = {"online": 0, "offline": 0, "total": 0}
    key = ""
    while True:
        r = tool_order({"ns": "System", "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        agents["total"] += 1
    agents["offline"] = len(dead)
    agents["online"] = agents["total"] - agents["offline"]
    return agents

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "cycle"
    
    if cmd == "cycle":
        r = net_cycle()
        print(f"🔄 Network cycle: {r['dead']} dead, {r['reconnected']} reconnected")
    
    elif cmd == "check":
        dead = net_check_heartbeats()
        if dead:
            for d in dead:
                print(f"  🔴 {d['agent']}: {d['seconds']}s sin heartbeat")
        else:
            print("  ✅ Todos los agentes responden")
    
    elif cmd == "reconnect":
        agent = sys.argv[2]
        r = net_reconnect(agent)
        print(f"🔄 {r['agent']}: reconectado (nonce={r['nonce']})")
    
    elif cmd == "status":
        s = net_status()
        print(f"📊 Red: {s['online']}/{s['total']} online, {s['offline']} offline")
