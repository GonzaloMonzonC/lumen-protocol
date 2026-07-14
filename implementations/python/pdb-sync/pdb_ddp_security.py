#!/usr/bin/env python3
"""
pdb_ddp_security.py — B3: DDPSECU seguridad DDP.

Basado en DDPSECU (302 líneas) de MSM + nuestra gobernanza HMAC existente.

Seguridad en 3 capas:
1. AUTENTICACIÓN — HMAC-SHA256 de cada mensaje DDP
2. AUTORIZACIÓN — verificar que emisor puede enviar al receptor
3. AUDITORÍA — registro de intentos de acceso denegados

Autor: Hermes + CadencesLab (B3 — Sprint B MSM→Lumen)
Licencia: MIT (lumen-protocol)
"""

import sys, os, hashlib, hmac, json
import _paths  # rutas repo-relativas
from datetime import datetime, timezone

SECRET_KEY = "ddp_secret_key_change_in_production"  # ¡CAMBIAR en prod!

def _get_tools():
    pdb_dir = _paths.PDB_DIR_S
    if pdb_dir not in sys.path:
        sys.path.insert(0, pdb_dir)
    from pdb_tools import tool_set, tool_get
    return tool_set, tool_get

def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

# ── Capa 1: HMAC (como MSM verifica integridad) ────────────────────

def ddp_sign(message: str, key: str = SECRET_KEY) -> str:
    """Firmar un mensaje DDP con HMAC-SHA256."""
    return hmac.new(
        key.encode(), message.encode(), hashlib.sha256
    ).hexdigest()

def ddp_verify(message: str, signature: str, key: str = SECRET_KEY) -> bool:
    """Verificar firma HMAC de un mensaje DDP."""
    expected = ddp_sign(message, key)
    return hmac.compare_digest(expected, signature)

# ── Capa 2: Autorización (como MSM DDPSECU) ────────────────────────

def ddp_check_auth(from_agent: str, to_agent: str, operation: str) -> dict:
    """Verificar si from_agent puede ejecutar operation contra to_agent.
    
    Retorna: {"allowed": True, "reason": ""}
             {"allowed": False, "reason": "no route"}
    """
    _, tool_get = _get_tools()
    
    # Verificar que from_agent existe
    r1 = tool_get({"ns": "System", "subs": ["identidad", from_agent]})
    if not r1.get("success") or not r1.get("value"):
        return {"allowed": False, "reason": f"unknown source: {from_agent}"}
    
    # Verificar que to_agent existe
    r2 = tool_get({"ns": "System", "subs": ["identidad", to_agent]})
    if not r2.get("success") or not r2.get("value"):
        return {"allowed": False, "reason": f"unknown target: {to_agent}"}
    
    # Verificar enlace DDP
    link_name = f"{from_agent}→{to_agent}"
    r3 = tool_get({"ns": "System", "subs": ["ddp", "links", link_name]})
    if not r3.get("success") or not r3.get("value"):
        return {"allowed": False, "reason": f"no link: {link_name}"}
    
    return {"allowed": True, "reason": "link active"}

# ── Capa 3: Auditoría (registro de accesos) ────────────────────────

def ddp_audit_log(from_agent: str, to_agent: str, operation: str, allowed: bool, reason: str):
    """Registrar intento de acceso DDP en ^System("ddp","audit")."""
    tool_set, _ = _get_tools()
    entry = {
        "from": from_agent,
        "to": to_agent,
        "operation": operation,
        "allowed": allowed,
        "reason": reason,
        "timestamp": _now(),
    }
    tool_set({"ns": "System", "subs": ["ddp", "audit", from_agent, _now()], "value": entry})

# ── CLI ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    cmd = sys.argv[1] if len(sys.argv) > 1 else "check"
    
    if cmd == "sign":
        msg = sys.argv[2] if len(sys.argv) > 2 else "test"
        sig = ddp_sign(msg)
        print(f"signature: {sig}")
        print(f"verify: {ddp_verify(msg, sig)}")
    
    elif cmd == "check":
        f = sys.argv[2] if len(sys.argv) > 2 else "hermes"
        t = sys.argv[3] if len(sys.argv) > 3 else "zalo"
        op = sys.argv[4] if len(sys.argv) > 4 else "query"
        result = ddp_check_auth(f, t, op)
        print(f"{'✅' if result['allowed'] else '❌'} {f}→{t}: {result['reason']}")
        ddp_audit_log(f, t, op, result['allowed'], result['reason'])
    
    elif cmd == "config":
        print(f"HMAC key: {SECRET_KEY[:15]}... (change in production)")
