"""
Shared LUMEN Native Transport for MCP servers.

Import by server_native.py files to speak LUMEN binary protocol over stdio.
Handles frame reading/writing, PROBE handshake, and compression.
"""

from __future__ import annotations

import sys
import json
from typing import Any

from lumen import (
    build_frame, build_size, parse_frame, compress_value, decompress_value,
    TYPE_REQUEST, TYPE_RESPONSE, TYPE_PROBE_ACK, FLAG_COMPRESSED,
    ParseComplete,
)


def read_frame() -> dict | None:
    """Read a LUMEN frame from stdin (binary), return parsed dict or None on EOF."""
    from lumen import ParseIncompletePayload

    buf = bytearray()
    while True:
        b = sys.stdin.buffer.read(1)  # 1 byte at a time — avoids Windows pipe deadlock
        if not b:
            return None
        buf.extend(b)

        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload  # Already a dict (decompress_value returns native Python)
        elif hasattr(result, 'needed'):
            continue  # Need more bytes
        # else: parse error, keep accumulating (shouldn't happen)


def send_frame(data: dict | None) -> None:
    """Build a LUMEN frame from a dict and write to stdout (binary)."""
    if data is None:
        return

    # Handle PROBE_ACK marker from process_message()
    if data.get("__lumen_ack__"):
        ack = data["ack"]
        payload = compress_value(ack)
        total_size = build_size(payload_len=len(payload))
        buf = bytearray(total_size)
        build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()
        return

    # Regular response
    payload = compress_value(data)
    total_size = build_size(payload_len=len(payload))
    buf = bytearray(total_size)
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
    sys.stdout.buffer.write(buf)
    sys.stdout.buffer.flush()


def handle_probe(msg: dict) -> dict | None:
    """Handle a LUMEN PROBE message. Returns __lumen_ack__ marker dict or None."""
    if msg.get("protocol") == "LUMEN":
        client_name = msg.get("client_name", "unknown")
        client_versions = msg.get("supported_versions", ["1.0"])
        accepted = "1.0" if "1.0" in client_versions else client_versions[0]
        ack = {
            "protocol": "LUMEN",
            "server_name": _server_name,
            "accepted_version": accepted,
        }
        return {"__lumen_ack__": True, "ack": ack}
    return None


_server_name = "lumen-native"


def set_server_name(name: str) -> None:
    """Set the server name for PROBE_ACK responses."""
    global _server_name
    _server_name = name


def native_main(process_message_fn) -> None:
    """
    Main loop for native LUMEN servers.
    
    Args:
        process_message_fn: Callable that takes a dict (JSON-RPC message) and
                           returns a dict response (or None for notifications).
                           Should also handle PROBE detection (use handle_probe helper).
    """
    while True:
        try:
            msg = read_frame()
            if msg is None:
                break

            # Check for LUMEN PROBE first
            probe_response = handle_probe(msg)
            if probe_response:
                send_frame(probe_response)
                continue

            response = process_message_fn(msg)
            send_frame(response)

        except Exception as e:
            error_resp = {
                "jsonrpc": "2.0", "id": None,
                "error": {"code": -32603, "message": f"Internal error: {e}"}
            }
            try:
                send_frame(error_resp)
            except Exception:
                pass
