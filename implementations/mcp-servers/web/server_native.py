#!/usr/bin/env python3
"""
LUMEN Native Web MCP Server — speaks LUMEN binary protocol natively.

Unified web_search + web_extract with native binary transport
for 40-50% wire savings and multi-agent cache sharing.
"""

from __future__ import annotations

import sys
import os

# Add parent to path for native_transport import
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _parent)

from native_transport import native_main, set_server_name
from server import TOOLS, HANDLERS

# ── Windows: force UTF-8 on stdout ──
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

set_server_name("lumen-web-native")


def process_message(msg: dict) -> dict | None:
    """Process a JSON-RPC message and return a response."""
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-web-native", "version": "1.0.0"}
            }
        }
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(tool_args)
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            except Exception as e:
                return {
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": f"Tool error: {e}"}
                }
        else:
            return {
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            }
    elif method == "notifications/initialized":
        return None
    else:
        return {
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        }


if __name__ == "__main__":
    native_main(process_message)
