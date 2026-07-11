#!/usr/bin/env python3
"""
pdb_ddp.py — DDP (Distributed Data Protocol) para CadencesLab.

Basado en DDP (134), DDPCIR (169), DDPCON (251) de MSM.

Conceptos MSM → Nuestra implementación:
  DDP Link   → Service binding (CF Worker ↔ Worker)
  DDP Circuit → Canal lógico entre agentes
  DDP Node   → Agente registrado en ^System("identidad")
  DDP Buffer → Cola de mensajes (Durable Object)

Esquema:
  ^DDP("links", nombre) = {target, type, status, last_heartbeat}
  ^DDP("circuits", id) = {from_agent, to_agent, status, buffers}
  ^DDP("nodes", agent_id) = {endpoint, capabilities, status}

Autor: Hermes + CadencesLab (B1 — Sprint B MSM→Lumen)
Licencia: MIT (lumen-protocol)
"""

import sys, os, json
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────

DDP_NS = "DDP"

# Status de circuitos (como MSM: O=open, F=full, C=closed)
CIRCUIT_STATUS = {"ACTIVE": "O", "IDLE": "I", "ERROR": "E", "CLOSED": "C"}

# ── Helpers ─────────────────────────────────────────────────────────

def _get_tools():
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order
    return tool_set, tool_get, tool_order

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── DDP Nodes ──────────────────────────────────────────────────────

def ddp_register_node(agent_id, endpoint, capabilities=None):
    """Registrar un agente como nodo DDP (como MSM SGDDPNT)."""
    tool_set, _, _ = _get_tools()
    node = {
        "agent_id": agent_id,
        "endpoint": endpoint,
        "capabilities": capabilities or [],
        "status": "online",
        "registered_at": _now(),
        "last_heartbeat": _now(),
    }
    tool_set({"ns": DDP_NS, "subs": ["nodes", agent_id], "value": node})
    return node

def ddp_get_node(agent_id):
    """Obtener info de un nodo DDP."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": DDP_NS, "subs": ["nodes", agent_id]})
    return r.get("value") if r.get("success") else None

def ddp_list_nodes():
    """Listar todos los nodos DDP."""
    _, _, tool_order = _get_tools()
    nodes = []
    key = ""
    while True:
        r = tool_order({"ns": DDP_NS, "subs": ["nodes", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        node = ddp_get_node(key)
        if node: nodes.append(node)
    return nodes

# ── DDP Links ──────────────────────────────────────────────────────

def ddp_add_link(name, target_url, link_type="service-binding"):
    """Añadir un enlace DDP (como MSM DDPLNK)."""
    tool_set, _, _ = _get_tools()
    link = {
        "name": name,
        "target": target_url,
        "type": link_type,
        "status": "active",
        "created": _now(),
        "last_heartbeat": _now(),
    }
    tool_set({"ns": DDP_NS, "subs": ["links", name], "value": link})
    return link

def ddp_list_links():
    """Listar todos los enlaces."""
    _, _, tool_order = _get_tools()
    links = []
    key = ""
    while True:
        r = tool_order({"ns": DDP_NS, "subs": ["links", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        lnk = ddp_get_link(key)
        if lnk: links.append(lnk)
    return links

def ddp_get_link(name):
    """Obtener info de un enlace."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": DDP_NS, "subs": ["links", name]})
    return r.get("value") if r.get("success") else None

# ── DDP Circuits ────────────────────────────────────────────────────

def ddp_open_circuit(from_agent, to_agent):
    """Abrir un circuito DDP entre dos agentes (como MSM DDPCIR)."""
    tool_set, tool_get, tool_order = _get_tools()
    # Generar ID de circuito
    circuit_id = f"{from_agent}→{to_agent}"
    circuit = {
        "id": circuit_id,
        "from": from_agent,
        "to": to_agent,
        "status": "O",  # Open
        "opened_at": _now(),
        "last_activity": _now(),
        "messages_sent": 0,
        "messages_received": 0,
    }
    tool_set({"ns": DDP_NS, "subs": ["circuits", circuit_id], "value": circuit})
    return circuit

def ddp_close_circuit(circuit_id):
    """Cerrar un circuito."""
    tool_set, tool_get, _ = _get_tools()
    r = tool_get({"ns": DDP_NS, "subs": ["circuits", circuit_id]})
    circuit = r.get("value")
    if circuit:
        circuit["status"] = "C"
        circuit["closed_at"] = _now()
        tool_set({"ns": DDP_NS, "subs": ["circuits", circuit_id], "value": circuit})

def ddp_list_circuits():
    """Listar todos los circuitos."""
    _, _, tool_order = _get_tools()
    circuits = []
    key = ""
    while True:
        r = tool_order({"ns": DDP_NS, "subs": ["circuits", key], "direction": 1})
        if not r.get("success") or r.get("value") is None: break
        key = r["value"]
        c = ddp_get_circuit(key)
        if c: circuits.append(c)
    return circuits

def ddp_get_circuit(circuit_id):
    """Obtener info de un circuito."""
    _, tool_get, _ = _get_tools()
    r = tool_get({"ns": DDP_NS, "subs": ["circuits", circuit_id]})
    return r.get("value") if r.get("success") else None

# ── DDP Send/Receive ───────────────────────────────────────────────

def ddp_send(circuit_id, message_type, payload):
    """Enviar un mensaje a través de un circuito DDP (como MSM DDPCON)."""
    tool_set, _, _ = _get_tools()
    circuit = ddp_get_circuit(circuit_id)
    if not circuit or circuit["status"] == "C":
        return {"success": False, "error": "Circuit not open"}

    now = _now()
    msg_id = f"msg_{now.replace(':', '').replace('-', '')}"
    msg = {
        "id": msg_id,
        "circuit_id": circuit_id,
        "type": message_type,
        "payload": payload,
        "sent_at": _now(),
    }

    # Almacenar en cola del circuito
    tool_set({"ns": DDP_NS, "subs": ["messages", circuit_id, msg["id"]], "value": msg})

    # Actualizar contadores
    circuit["messages_sent"] = circuit.get("messages_sent", 0) + 1
    circuit["last_activity"] = _now()
    tool_set({"ns": DDP_NS, "subs": ["circuits", circuit_id], "value": circuit})

    return {"success": True, "msg_id": msg["id"]}

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys; cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "register":
        agent = sys.argv[2]; ep = sys.argv[3] if len(sys.argv) > 3 else "local"
        r = ddp_register_node(agent, ep)
        print(f"Node {agent} registered @ {r['endpoint']}")

    elif cmd == "link-add":
        name = sys.argv[2]; target = sys.argv[3]
        r = ddp_add_link(name, target)
        print(f"Link {name} → {target}")

    elif cmd == "circuit-open":
        f = sys.argv[2]; t = sys.argv[3]
        r = ddp_open_circuit(f, t)
        print(f"Circuit {r['id']} opened")

    elif cmd == "list-nodes":
        for n in ddp_list_nodes():
            print(f"  🟢 {n['agent_id']} @ {n['endpoint']}")
    elif cmd == "list-links":
        for l in ddp_list_links():
            print(f"  🔗 {l['name']} → {l['target']} ({l['status']})")
    elif cmd == "list-circuits":
        for c in ddp_list_circuits():
            em = {"O":"🟢","C":"🔴","E":"⚠️"}.get(c['status'],"❓")
            print(f"  {em} {c['id']} ({c['status']}) msgs_sent={c.get('messages_sent',0)}")

    else:
        print("Uso: python pdb_ddp.py [register|link-add|circuit-open|list-nodes|list-links|list-circuits]")
