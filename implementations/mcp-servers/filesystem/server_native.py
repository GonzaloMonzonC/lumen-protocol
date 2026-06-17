#!/usr/bin/env python3
"""
LUMEN Native Filesystem MCP Server — speaks LUMEN binary protocol natively.

No JSON-RPC text wrapping — pure binary frames over stdio.
Uses the LUMEN Python package for frame building/parsing and compression.

Compare to server.py (JSON-RPC over LUMEN wrapper) for benchmark:
  - server_native.py: 50-70% wire savings, MUX, streaming
  - server.py:        32-60% wire savings, no MUX, no streaming

Usage:
    python server_native.py
    hermes mcp add lumen-fs-native --command python --args server_native.py --transport lumen
"""

import sys
import json

import shared_tools

# ── LUMEN native imports ──
from lumen import (
    build_frame, build_size, parse_frame, compress_value, decompress_value,
    TYPE_REQUEST, TYPE_RESPONSE, TYPE_PROBE_ACK, FLAG_COMPRESSED,
    ParseComplete,
)

# ═══════════════════════════════════════════════════════════════════════
# LUMEN Native Transport — binary frames, no JSON-RPC wrapping
# ═══════════════════════════════════════════════════════════════════════

def process_message(msg: dict) -> dict:
    """Process a message. Handles LUMEN PROBE or JSON-RPC."""
    
    # ── LUMEN PROBE handshake ──
    if "protocol" in msg and msg.get("protocol") == "LUMEN":
        # This is a LUMEN probe, respond with PROBE_ACK
        client_name = msg.get("client_name", "unknown")
        client_versions = msg.get("supported_versions", ["1.0"])
        accepted = "1.0" if "1.0" in client_versions else client_versions[0]
        ack = {
            "protocol": "LUMEN",
            "server_name": "lumen-filesystem-native",
            "accepted_version": accepted,
        }
        # Return special marker for send_lumen_frame to handle differently
        return {"__lumen_ack__": True, "ack": ack}
    
    # ── JSON-RPC handling ──
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-filesystem-native", "version": "2.0.0"}
            }
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": shared_tools.TOOLS}
        }
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = shared_tools.HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(tool_args)
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32000, "message": f"Tool error: {e}"}}
        else:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
    elif method == "notifications/initialized":
        return None  # No response
    else:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def read_lumen_frame() -> dict | None:
    """Read a LUMEN frame from stdin (binary mode), return parsed JSON message."""
    from lumen import ParseIncompletePayload

    buf = bytearray()
    while True:
        # Read 1 byte at a time — prevents blocking on pipe
        # (sys.stdin.buffer.read(N) blocks until N bytes or EOF on Windows)
        b = sys.stdin.buffer.read(1)
        if not b:
            return None
        buf.extend(b)

        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload  # Already a dict
        elif hasattr(result, 'needed'):
            continue  # Need more bytes
        # else: parse error, keep accumulating


def send_lumen_frame(response: dict) -> None:
    """Build a LUMEN frame and write to stdout (binary mode)."""
    if response is None:
        return

    from lumen.negotiation import LumenAck
    from lumen import TYPE_PROBE_ACK, FLAG_COMPRESSED as FC

    # Handle PROBE_ACK marker
    if response.get("__lumen_ack__"):
        ack = response["ack"]
        payload = compress_value(ack)
        header_size = build_size(payload)
        total_size = header_size + len(payload)
        buf = bytearray(total_size)
        build_frame(TYPE_PROBE_ACK, FC, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()
        return

    payload = compress_value(response)
    header_size = build_size(payload)  # header only
    total_size = header_size + len(payload)
    buf = bytearray(total_size)
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
    sys.stdout.buffer.write(buf)
    sys.stdout.buffer.flush()


def main() -> None:
    """Main loop: read LUMEN frames from stdin, process, respond on stdout."""
    while True:
        try:
            msg = read_lumen_frame()
            if msg is None:
                break

            response = process_message(msg)
            send_lumen_frame(response)

        except Exception as e:
            error_resp = {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32603, "message": f"Internal error: {e}"}}
            try:
                send_lumen_frame(error_resp)
            except Exception:
                pass


if __name__ == "__main__":
    main()
