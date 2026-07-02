#!/usr/bin/env python3
"""
LUMEN Level 2 Native Server — Zero-Copy Shared Memory Transport.

Implements a full MCP server that uses mmap ring buffers for ALL
communication (no stdio JSON-RPC). Negotiated during PROBE handshake.

Architecture:
  1. Server creates ShmRegion + announces name in PROBE_ACK
  2. Client (Hermes) opens region, both switch to shm transport
  3. All subsequent frames go through ring buffers (zero copy)
  4. stdio only used for initial PROBE and process lifecycle

Hermes integration (future): 
  LumenStdioTransport detects "shm_region" in PROBE_ACK → 
  opens ShmRegion → creates ShmTransport → switches from stdio.
"""

from __future__ import annotations

import sys
import os
import uuid
import json
import time
from typing import Any, Callable, Optional

# Add parent to path for native_transport and lumen imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "python", "src"
))

from lumen.shm import ShmRegion, ShmRingBuffer, ShmTransport, RingSide
from lumen import (
    build_frame, parse_frame, compress_value, decompress_value,
    TYPE_REQUEST, TYPE_RESPONSE, TYPE_PROBE_ACK, FLAG_COMPRESSED,
    ParseComplete, build_size
)


class ShmNativeServer:
    """
    MCP server that speaks LUMEN binary protocol over shared memory.
    
    Falls back to stdio transport if client doesn't support shm.
    """

    def __init__(
        self,
        name: str,
        tools: list[dict],
        handlers: dict[str, Callable],
        shm_size: int = 512 * 1024,  # 512 KiB
        large_payload_threshold: int = 4096,  # 4KB
    ):
        self.name = name
        self.tools = tools
        self.handlers = handlers
        self.shm_size = shm_size
        self.large_threshold = large_payload_threshold
        self._shm_region: Optional[ShmRegion] = None
        self._shm_transport: Optional[ShmTransport] = None
        self._shm_name: Optional[str] = None
        self._use_shm = False

    # ── SHM Lifecycle ────────────────────────────────────────────────

    def _create_shm_region(self) -> str:
        """Create shared memory region. Returns region name."""
        name = f"lumen-{self.name}-{uuid.uuid4().hex[:8]}"
        self._shm_region = ShmRegion.create(name, self.shm_size)
        self._shm_region.init_header()
        self._shm_name = name
        return name

    def _setup_shm_transport(self) -> None:
        """Set up ring buffers for bidirectional communication."""
        assert self._shm_region is not None
        # Server writes to Ring B, reads from Ring A
        write_ring = self._shm_region.ring_buffer(RingSide.B)
        read_ring = self._shm_region.ring_buffer(RingSide.A)
        self._shm_transport = ShmTransport(write_ring, read_ring)

    # ── Frame I/O ────────────────────────────────────────────────────

    def _read_frame_stdio(self) -> Optional[dict]:
        """Read a LUMEN frame from stdin (binary mode)."""
        buf = bytearray()
        while True:
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
                return payload

    def _read_frame_shm(self) -> Optional[dict]:
        """Read a LUMEN frame from shared memory ring buffer."""
        assert self._shm_transport is not None
        raw = self._shm_transport.recv_frame()
        if raw is None:
            return None
        # Parse the raw frame bytes
        result = parse_frame(bytearray(raw), 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload
        return None

    def _send_frame_stdio(self, data: dict | None) -> None:
        """Send a LUMEN frame to stdout (binary mode)."""
        if data is None:
            return

        # Handle PROBE_ACK marker
        if data.get("__lumen_ack__"):
            ack = data["ack"]
            # If shm is available, advertise it
            if self._shm_name:
                ack["shm_region"] = self._shm_name
                ack["shm_size"] = self.shm_size

            payload = compress_value(ack)
            buf = bytearray(build_size(payload_len=len(payload)))
            build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, payload, buf, 0)
            sys.stdout.buffer.write(buf)
            sys.stdout.buffer.flush()
            return

        # Regular response
        payload = compress_value(data)
        buf = bytearray(build_size(payload_len=len(payload)))
        build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()

    def _send_frame_shm(self, data: dict | None) -> None:
        """Send a LUMEN frame through shared memory ring buffer."""
        if data is None:
            return

        payload = compress_value(data)
        total_size = build_size(payload_len=len(payload))
        buf = bytearray(total_size)
        build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
        self._shm_transport.send_frame(bytes(buf))

    # ── Message Processing ───────────────────────────────────────────

    def _process_probe(self, msg: dict) -> dict:
        """Handle LUMEN PROBE — create SHM region + respond with ACK."""
        client_versions = msg.get("supported_versions", ["1.0"])
        accepted = "1.0" if "1.0" in client_versions else client_versions[0]

        # Create shared memory region
        shm_name = self._create_shm_region()

        ack = {
            "protocol": "LUMEN",
            "server_name": self.name,
            "accepted_version": accepted,
            "shm_region": shm_name,
            "shm_size": self.shm_size,
        }

        # Send ACK via stdio (client still on stdio at this point)
        payload = compress_value(ack)
        buf = bytearray(build_size(payload_len=len(payload)))
        build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()

        # Now set up shm transport for subsequent communication
        self._setup_shm_transport()

        # Return signal to switch to shm mode
        return {"__lumen_ack__": True, "ack": ack, "__switch_to_shm__": True}

    def _process_message(self, msg: dict) -> Optional[dict]:
        """Process a JSON-RPC message and return response."""
        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "initialize":
            return {
                "jsonrpc": "2.0", "id": req_id,
                "result": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {"tools": {}},
                    "serverInfo": {
                        "name": self.name,
                        "version": "2.0.0",
                        "transport": "lumen-shm" if self._use_shm else "lumen-stdio",
                    }
                }
            }
        elif method == "tools/list":
            return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.tools}}
        elif method == "tools/call":
            params = msg.get("params", {})
            tool_name = params.get("name", "")
            tool_args = params.get("arguments", {})
            handler = self.handlers.get(tool_name)
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

    # ── Main Loop ────────────────────────────────────────────────────

    def run(self) -> None:
        """Main loop: read frames, process, respond."""
        read_frame = self._read_frame_stdio
        send_frame = self._send_frame_stdio

        while True:
            try:
                msg = read_frame()
                if msg is None:
                    break

                # Check for LUMEN PROBE
                if msg.get("protocol") == "LUMEN":
                    result = self._process_probe(msg)
                    send_frame(result)

                    # If shm was negotiated, switch transport
                    if result.get("__switch_to_shm__"):
                        self._use_shm = True
                        read_frame = self._read_frame_shm
                        send_frame = self._send_frame_shm
                        sys.stderr.write(
                            f"[SHM] Switched to shared memory transport: "
                            f"{self._shm_name}\n"
                        )
                        sys.stderr.flush()
                    continue

                # Normal JSON-RPC processing
                t0 = time.time()
                response = self._process_message(msg)
                elapsed = time.time() - t0
                if elapsed > 0.05:  # log anything > 50ms
                    tool_name = msg.get("params", {}).get("name", "?")
                    sys.stderr.write(
                        f"[lumen-shm] SLOW call: {tool_name} took {elapsed*1000:.0f}ms\n"
                    )
                    sys.stderr.flush()
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

    def cleanup(self) -> None:
        """Clean up shared memory region."""
        if self._shm_region:
            self._shm_region.close()
            self._shm_region = None
