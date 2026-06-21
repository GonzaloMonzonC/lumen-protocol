#!/usr/bin/env python3
"""
PDBM-Lumen Native MCP Server — speaks LUMEN binary protocol natively.

Uses the same tool logic as server.py but with native binary transport
for 55-80% wire savings via LUMEN session dictionary compression.

Iteration patterns (pdb_order in a loop) benefit enormously:
  - Repeated keys ("ns", "subs", namespace names) → 1 byte each
  - Repeated subkey prefixes → shared in dictionary
  - ~90 bytes JSON per call → ~15 bytes LUMEN
"""

from __future__ import annotations

import sys
import os

# Add parent to path for native_transport import
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _parent)

from native_transport import native_main, set_server_name
from pdb_tools import TOOLS, HANDLERS

# Windows: force UTF-8 on stdout
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

set_server_name("lumen-pdb-native")


def process_message(msg: dict) -> dict | None:
    """Process a JSON-RPC message and return a LUMEN-compressible response."""
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {
                        "listChanged": False,
                        "toolCount": len(TOOLS),
                    }
                },
                "serverInfo": {
                    "name": "lumen-pdb-native",
                    "version": "0.1.0",
                }
            }
        }

    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}

    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})

        handler = HANDLERS.get(name)
        if handler:
            try:
                result = handler(**args)
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "result": {"content": [
                        {"type": "text", "text": json_dumps(result)}
                    ]}
                }
            except Exception as e:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32603, "message": str(e)}
                }
        else:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {name}"}
            }

    elif method == "notifications/initialized":
        return None  # Notification — no response

    return {
        "jsonrpc": "2.0", "id": req_id,
        "error": {"code": -32601, "message": f"Unknown method: {method}"}
    }


def json_dumps(obj) -> str:
    """Compact JSON serialization, ensure_ascii=False for Unicode."""
    import json
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


if __name__ == "__main__":
    native_main(process_message)
