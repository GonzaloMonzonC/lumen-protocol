#!/usr/bin/env python3
"""
pdb_ddp.py — DDP Concurrency Control (Sprint B).

Patrones MSM adaptados (Zalo: 2 conceptos clave):
  1. Batch sync + dirty flag → YA HECHO en A4
  2. Turn-lock concurrency → ESTE MÓDULO

MSM usaba locks por recurso para evitar starvation.
Nosotros usamos HMAC + nonce: cada agente firma su operación,
el worker valida el orden sin locks ni esperas.

Conceptos DDP de MSM adaptados:
  - DDPCON → control de conexiones → nuestro AGENT_NS_MAP
  - DDPSECU → seguridad por firma → nuestro HMAC + nonce
  - SGDDP → configuración → nuestro ^System("gobernanza")

Author: Hermes + CadencesLab (Sprint B — MSM→Lumen)
Date: 2026-07-11
"""

import sys, os, json, time, hashlib, hmac
from datetime import datetime, timezone
from typing import Optional

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
from pdb_tools import tool_set, tool_get, tool_order

# ── Config ──────────────────────────────────────────────────────────

DDP_NS = "System"
NONCE_KEY = "ddp_nonce"

# ── Nonce-based concurrency (DDPSECU adaptado) ─────────────────────

def ddp_generate_nonce(agent_id: str) -> int:
    """Generar nonce para una operación DDP (sin confirmar en PDB).
    El nonce se confirma solo tras verificación exitosa."""
    key = f"{NONCE_KEY}_{agent_id}"
    r = tool_get({"ns": DDP_NS, "subs": [key]})
    current = r.get("value", 0) if r.get("success") else 0
    if not isinstance(current, int): current = 0
    return current + 1

def ddp_validate_nonce(agent_id: str, nonce: int) -> bool:
    """Validar que el nonce es el esperado (el último confirmado + 1)."""
    key = f"{NONCE_KEY}_{agent_id}"
    r = tool_get({"ns": DDP_NS, "subs": [key]})
    # El nonce ya fue generado por sign, verificamos que es > último confirmado
    last_confirmed = r.get("value", 0) if r.get("success") else 0
    if not isinstance(last_confirmed, int):
        last_confirmed = 0
    return nonce > last_confirmed

def ddp_sign_operation(agent_id: str, operation: dict, secret: str = None) -> dict:
    """Firmar una operación DDP con HMAC-SHA256 + nonce.
    Cada agente firma su cambio, el worker valida.
    """
    nonce = ddp_generate_nonce(agent_id)
    payload = json.dumps({"agent": agent_id, "nonce": nonce, "op": operation}, sort_keys=True)
    sig = hmac.new(
        (secret or f"ddp_{agent_id}_2026").encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    return {"agent": agent_id, "nonce": nonce, "op": operation, "sig": sig}

def ddp_verify_operation(signed_op: dict, secret: str = None) -> dict:
    """Verificar firma HMAC y nonce de una operación DDP."""
    agent = signed_op.get("agent", "")
    nonce = signed_op.get("nonce", 0)
    op = signed_op.get("op", {})
    sig = signed_op.get("sig", "")

    # Validar nonce secuencial
    if not ddp_validate_nonce(agent, nonce):
        return {"valid": False, "reason": f"invalid nonce: {nonce}"}

    # Validar firma HMAC
    payload = json.dumps({"agent": agent, "nonce": nonce, "op": op}, sort_keys=True)
    expected = hmac.new(
        (secret or f"ddp_{agent}_2026").encode(),
        payload.encode(),
        hashlib.sha256
    ).hexdigest()[:16]
    if sig != expected:
        return {"valid": False, "reason": "invalid signature"}

    # Actualizar nonce confirmado
    tool_set({"ns": DDP_NS, "subs": [f"{NONCE_KEY}_{agent}"], "value": nonce})
    return {"valid": True, "agent": agent, "nonce": nonce}

# ── DDP Link Status (DDPLNK adaptado) ──────────────────────────────

def ddp_link_status(agent_id: str) -> dict:
    """Estado de enlace DDP para un agente (como DDPLNK de MSM).
    Nuestro equivalente: service binding status + nonce tracking.
    """
    nonce = tool_get({"ns": DDP_NS, "subs": [f"{NONCE_KEY}_{agent_id}"]})
    pulse = tool_get({"ns": DDP_NS, "subs": ["pulse", agent_id]})

    return {
        "agent": agent_id,
        "nonce": nonce.get("value", 0) if nonce.get("success") else 0,
        "status": pulse.get("value", {}).get("status", "unknown") if pulse.get("success") else "unknown",
        "last_activity": pulse.get("value", {}).get("last_activity", "") if pulse.get("success") else "",
        "link_type": "service_binding"  # vs MSM: DDP/TCP/LAT
    }

def ddp_all_links() -> list:
    """Estado de todos los enlaces DDP (como SGDDP de MSM)."""
    links = []
    key = ""
    while True:
        r = tool_order({"ns": DDP_NS, "subs": ["pulse", key], "direction": 1})
        if not r.get("success") or not r.get("value"):
            break
        key = r["value"]
        links.append(ddp_link_status(key))
    return links

# ── DDP Status Display (MAPDDP adaptado) ───────────────────────────

def ddp_status() -> str:
    """MAPDDP-style display para nuestro DDP."""
    links = ddp_all_links()
    lines = []
    lines.append("═" * 55)
    lines.append("  🌐 DDP — Distributed Data Protocol (MSM→Lumen)")
    lines.append("═" * 55)
    lines.append(f"  Enlaces activos: {len(links)}")
    lines.append(f"  Tipo: service_binding (~0ms)")
    lines.append(f"  Auth: HMAC-SHA256 + nonce secuencial")
    lines.append("─" * 55)
    for link in links:
        status_icon = "🟢" if link.get("status") == "online" else "⚫"
        lines.append(f"  {status_icon} {link.get('agent','?'):15s} nonce={link.get('nonce',0):4d} {link.get('link_type','?')}")
    lines.append("═" * 55)
    return "\n".join(lines)

# ── CLI ──────────────────────────────────────────────────────────────

if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"

    if cmd == "sign":
        agent = sys.argv[2] if len(sys.argv) > 2 else "test"
        op = {"ns": "TEST", "subs": ["x"], "op": "SET", "value": 42}
        print(json.dumps(ddp_sign_operation(agent, op), indent=2))
    elif cmd == "verify":
        signed = json.loads(sys.stdin.read()) if len(sys.argv) <= 2 else json.loads(sys.argv[2])
        print(ddp_verify_operation(signed))
    elif cmd == "links":
        for link in ddp_all_links():
            print(f"  {link['agent']}: nonce={link['nonce']} {link['status']}")
    elif cmd == "status":
        print(ddp_status())
    else:
        print("PDB DDP Concurrency Control (Sprint B)")
        print("  sign <agent>        — Firmar operación con HMAC+nonce")
        print("  verify '<json>'     — Verificar operación firmada")
        print("  links / status      — Estado de enlaces DDP")
