#!/usr/bin/env python3
"""
LUMEN Filesystem MCP Server — high-performance file ops via MCP + LUMEN transport.

Exposes read_file, write_file, search_files, and patch as MCP tools.
Designed to be used with Hermes Agent's ``transport: lumen`` config option.
The LUMEN binary compression happens transparently at the transport layer
— this server speaks standard JSON-RPC over stdio.

Usage:
    python server.py                          # direct
    python server.py                            # via Hermes mcp_servers config
    hermes mcp add lumen-fs --command python --args server.py
"""

from __future__ import annotations

import sys
import json

import shared_tools


def send(msg: dict) -> None:
    """Send a JSON-RPC response to stdout."""
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def handle_message(msg: dict) -> None:
    """Handle a single JSON-RPC message."""
    shared_tools._request_count += 1
    
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-filesystem", "version": "1.0.0"}
            }
        })
    elif method == "tools/list":
        send({
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": shared_tools.TOOLS}
        })
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})

        handler = shared_tools.HANDLERS.get(tool_name)
        if handler:
            shared_tools._tool_usage[tool_name] = shared_tools._tool_usage.get(tool_name, 0) + 1
            try:
                result = handler(tool_args)
                send({"jsonrpc": "2.0", "id": req_id, "result": result})
            except Exception as e:
                send({
                    "jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32000, "message": f"Tool error: {e}"}
                })
        else:
            send({
                "jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
            })
    elif method == "notifications/initialized":
        pass  # No response needed
    else:
        send({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Unknown method: {method}"}
        })


def main() -> None:
    """Main loop: read JSON-RPC lines from stdin, respond on stdout."""
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
            handle_message(msg)
        except json.JSONDecodeError:
            # Silently ignore malformed lines (binary probe garbage from LUMEN)
            pass


if __name__ == "__main__":
    main()
