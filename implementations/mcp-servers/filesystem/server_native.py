#!/usr/bin/env python3
"""
LUMEN Filesystem MCP Server — LUMEN binary protocol over Shared Memory.

Uses ShmNativeServer for full Level 2 zero-copy SHM transport.
Communicates via mmap ring buffers after initial PROBE handshake.
Falls back to stdio if client doesn't support SHM.

Usage:
    python server_native.py
    hermes mcp add lumen-fs-native --command python --args server_native.py --transport lumen
"""

from __future__ import annotations

import sys, os

# Paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "python", "src"
))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import shared_tools
from shm_native_server import ShmNativeServer

if __name__ == "__main__":
    server = ShmNativeServer(
        "lumen-filesystem-native",
        shared_tools.TOOLS,
        shared_tools.HANDLERS,
        shm_size=8 * 1024 * 1024,  # 8 MiB for large files
    )
    try:
        server.run()
    finally:
        server.cleanup()
