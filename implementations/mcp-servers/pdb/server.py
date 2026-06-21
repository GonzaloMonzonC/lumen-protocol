#!/usr/bin/env python3
"""
PDBM-Lumen MCP Server — JSON-RPC over stdio.

Start: python server.py
Config in Hermes:
    mcp_servers:
      lumen-pdb:
        command: python
        args: ["path/to/server.py"]
        transport: stdio   # or 'lumen' for LUMEN native
"""

from __future__ import annotations
import sys, json, logging, os

# Windows: reconfigure stdout for UTF-8
if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

from pdb_tools import TOOLS, HANDLERS

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)


def send(msg: dict):
    line = json.dumps(msg, ensure_ascii=False)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def handle(msg: dict):
    msg_id = msg.get("id")
    method = msg.get("method", "")

    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": msg_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                        "toolCount": len(TOOLS),
                    }
                },
                "serverInfo": {
                    "name": "lumen-pdb",
                    "version": "0.1.0",
                }
            }
        })

    elif method == "tools/list":
        send({"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}})

    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = HANDLERS.get(name)
        if handler:
            try:
                result = handler(**args)
                send({
                    "jsonrpc": "2.0", "id": msg_id,
                    "result": {"content": [
                        {"type": "text", "text": json.dumps(result, ensure_ascii=False)}
                    ]}
                })
            except Exception as e:
                send({
                    "jsonrpc": "2.0", "id": msg_id,
                    "error": {"code": -32603, "message": str(e)}
                })
        else:
            send({
                "jsonrpc": "2.0", "id": msg_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"}
            })

    elif method == "notifications/initialized":
        # No-op, just acknowledge
        pass

    else:
        send({
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        })


def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle(msg)
        except json.JSONDecodeError as e:
            send({
                "jsonrpc": "2.0",
                "error": {"code": -32700, "message": f"Parse error: {e}"}
            })


if __name__ == "__main__":
    main()
