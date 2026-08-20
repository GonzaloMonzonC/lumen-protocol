#!/usr/bin/env python3
"""MCP compartido parametrizable 'ecosistema' — stdio, stdlib-only.

Un solo canal para hablar con CUALQUIER agente del ecosistema (workers CF,
personalidades de Poli, agentes nacidos de la nada). El registro vive en
^AGENTES(routing,<nombre>) de la PDB local; el dispatcher es el endpoint
POST /ddp/agent/chat del vm-api (:8081).

Tools:
  - agente_chat(agente, mensaje, session) → respuesta del agente destino
  - agente_list() → inventario del registro

Auth: token del dashboard (~/.hermes/dashboard.token) — llamadas locales.
Sin dependencias externas (no mcp SDK): JSON-RPC puro sobre stdio.
"""
import json
import os
import sys
import urllib.request

VM_API = os.environ.get("VM_API_URL", "http://127.0.0.1:8081")
TOKEN_FILE = os.path.expanduser("~/.hermes/dashboard.token")

# Windows: forzar UTF-8 en stdin y stdout (el cliente MCP espera UTF-8;
# sin esto, cp1252 rompe caracteres como Í → byte 0x8D → surrogate U+DC8D)
if hasattr(sys.stdout, "buffer"):
    sys.stdout = __import__("io").TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if hasattr(sys.stdin, "buffer"):
    sys.stdin = __import__("io").TextIOWrapper(sys.stdin.buffer, encoding="utf-8", errors="strict")

SERVER_INFO = {
    "protocolVersion": "2024-11-05",
    "capabilities": {"tools": {}, "resources": {}, "prompts": {}},
    "serverInfo": {"name": "ecosistema", "version": "1.0.0"},
}

TOOLS = [
    {
        "name": "agente_chat",
        "description": (
            "Hablar con cualquier agente del ecosistema Cadences Lab por nombre: "
            "workers (zalo, lisa, tom, angi, campo, gon), personalidades de Poli "
            "(poli, smith, vega, roberto, javier, pamies, porto) y los agentes "
            "nacidos de la nada (danae, bio-logos, entropia-zero, arche). "
            "Resuelve el agente en ^AGENTES(routing) de la PDB y responde con su voz."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "agente": {"type": "string", "description": "Nombre del agente (ej: vega, danae, zalo)"},
                "mensaje": {"type": "string", "description": "Mensaje para el agente"},
                "session": {"type": "string", "description": "ID de sesión para mantener contexto (opcional)", "default": "hermes"},
            },
            "required": ["agente", "mensaje"],
        },
    },
    {
        "name": "agente_list",
        "description": "Inventario de agentes registrados en el ecosistema (^AGENTES(routing)).",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


def _token():
    try:
        return open(TOKEN_FILE, encoding="utf-8").read().strip()
    except Exception:
        return os.environ.get("DASHBOARD_TOKEN", "")


def _call_vm(method: str, body=None, timeout: int = 120):
    """Llamada al vm-api con token del dashboard."""
    tok = _token()
    url = f"{VM_API}/ddp/agent/{method}"
    if tok:
        url += f"?t={tok}"
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", errors="replace"))


def _handle_tool(name: str, args: dict):
    if name == "agente_chat":
        agente = str(args.get("agente", "")).strip().lower()
        mensaje = str(args.get("mensaje", "")).strip()
        if not agente or not mensaje:
            return {"error": "agente y mensaje son obligatorios"}
        session = str(args.get("session", "hermes")).strip() or "hermes"
        r = _call_vm("chat", {"agente": agente, "mensaje": mensaje, "session": session}, timeout=120)
        if not r.get("success"):
            return {"error": r.get("error", "fallo del dispatcher")}
        return {"agente": agente, "via": r.get("via"), "response": r.get("response"), "ms": r.get("ms")}
    if name == "agente_list":
        r = _call_vm("list", timeout=30)
        if not r.get("success"):
            return {"error": r.get("error", "fallo del registro")}
        agentes = r.get("agentes", {})
        return {
            "total": len(agentes),
            "agentes": {k: (v.get("tipo") + ":" + (v.get("mode") or v.get("url") or "")) for k, v in sorted(agentes.items())},
        }
    return {"error": f"tool desconocida: {name}"}


def _send(msg: dict):
    out = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()


def main():
    for line in sys.stdin:
        try:
            msg = json.loads(line.strip())
        except Exception:
            continue
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}

        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": SERVER_INFO})
        elif method == "notifications/initialized":
            continue
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"ok": True, "agent": "ecosistema"}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            name = (params.get("name") or "").strip()
            args = params.get("arguments") or {}
            try:
                result = _handle_tool(name, args)
            except Exception as e:
                result = {"error": str(e)[:300]}
            _send({"jsonrpc": "2.0", "id": mid,
                   "result": {"content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False)}]}})
        else:
            _send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Method not found: {method}"}})


if __name__ == "__main__":
    main()
