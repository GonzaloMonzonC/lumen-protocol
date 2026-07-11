#!/usr/bin/env python3
"""
pdb_journal_ddp_bridge.py — A4: Journal→DDP bridge (JRNXDDP adaptado).

Conecta ^CHANGES (journaling) con ^DDP (protocolo distribuido).
Cuando un cambio se registra en el journal, el bridge lo reenvía
a los circuitos DDP que están suscritos al namespace cambiado.

Inspirado en JRNXDDP (68 líneas) y DEJRNDDP (297 líneas) de MSM.

Flujo:
  tool_set/kill → _record_change → subscribers → journal_ddp_bridge
     → ddp_send(circuit, "journal", change_data)

Autor: Hermes + CadencesLab (A4 — Sprint A→B bridge)
Licencia: MIT (lumen-protocol)
"""

import sys, os, json
from datetime import datetime, timezone

# ── Config ──────────────────────────────────────────────────────────

CHANGES_NS = "CHANGES"

# ── Helpers ─────────────────────────────────────────────────────────

def _get_tools():
    pdb_dir = os.path.expanduser(
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"
    )
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get, tool_order, _subscribers, _ns_matches
    return tool_set, tool_get, tool_order, _subscribers, _ns_matches

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── DDP Bridge subscriber ──────────────────────────────────────────

def journal_ddp_callback(change_data):
    """Callback que recibe cambios de ^CHANGES y los reenvía vía DDP.

    Se registra como subscriber de _record_change.
    """
    # Solo reenviar cambios de namespaces no-sistema
    ns = change_data.get("ns", "")
    if ns in (CHANGES_NS, "DDP", "ROUTINE"):
        return  # no reenviar cambios del propio sistema

    # Reenviar a circuitos DDP suscritos a este namespace
    from pdb_ddp import ddp_list_circuits, ddp_send

    for circuit in ddp_list_circuits():
        if circuit.get("status") != "O":  # Open
            continue

        ddp_send(
            circuit["id"],
            "journal",
            {
                "op": change_data.get("op"),
                "ns": ns,
                "subs": change_data.get("subs", []),
                "old_value": change_data.get("old_value"),
                "new_value": change_data.get("new_value"),
                "timestamp": change_data.get("timestamp"),
            }
        )

# ── Bridge management ──────────────────────────────────────────────

def bridge_subscribe():
    """Registrar el bridge como subscriber de ^CHANGES."""
    _, _, _, subscribers, ns_matches = _get_tools()

    # Nuestro callback recibe TODOS los cambios (pattern="*")
    subscribers.append(("*", journal_ddp_callback))

    # Registrar en ^DDP("bridge") que el bridge está activo
    from pdb_ddp import _get_tools as ddp_tools
    ts, tg, _ = ddp_tools()
    tg({"ns": "DDP", "subs": ["bridge", "status"], "value": {
        "active": True,
        "subscribed_at": _now(),
        "pattern": "*",
    }})

def bridge_unsubscribe():
    """Desregistrar el bridge."""
    _, _, _, subscribers, _ = _get_tools()
    subscribers[:] = [(p, c) for p, c in subscribers if c != journal_ddp_callback]

def bridge_status():
    """Verificar estado del bridge."""
    from pdb_ddp import ddp_list_circuits, ddp_list_links
    circuits = ddp_list_circuits()
    links = ddp_list_links()

    _, tool_get, _, _, _ = _get_tools()
    r = tool_get({"ns": "DDP", "subs": ["bridge", "status"]})
    bridge_info = r.get("value") if r.get("success") else None

    return {
        "active": bridge_info.get("active", False) if bridge_info else False,
        "subscribed_at": bridge_info.get("subscribed_at") if bridge_info else None,
        "circuits": len(circuits),
        "links": len(links),
    }

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "start":
        bridge_subscribe()
        print("Bridge started — journaling → DDP forwarding active")

    elif cmd == "stop":
        bridge_unsubscribe()
        print("Bridge stopped")

    elif cmd == "status":
        s = bridge_status()
        print(f"Active:        {s['active']}")
        print(f"Subscribed:    {s['subscribed_at']}")
        print(f"DDP circuits:  {s['circuits']}")
        print(f"DDP links:     {s['links']}")
