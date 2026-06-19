#!/usr/bin/env python3
"""
LUMEN Native Thinking MCP Server — speaks LUMEN binary protocol natively.

Uses the same tool logic as server.py but with native binary transport
for 60-80% wire savings, MUX support, and streaming.
"""

from __future__ import annotations

import sys
import os

# Add parent to path so we can import server module and native_transport
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _parent)

from native_transport import native_main, set_server_name
from server import HANDLERS, TOOLS

# ── Windows: force UTF-8 on stdout ──
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

set_server_name("lumen-thinking-native")

_tool_calls = 0
_estimated_chars = 0


def process_message(msg: dict) -> dict | None:
    """Process a JSON-RPC message and return a response."""
    global _tool_calls, _estimated_chars

    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-thinking-native", "version": "2.0.0"}
            }
        }
    elif method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOLS}}
    elif method == "tools/call":
        _tool_calls += 1
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
