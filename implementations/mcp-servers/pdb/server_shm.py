#!/usr/bin/env python3
"""
PDBM-Lumen MCP Server — Level 2 Shared Memory Transport.

Zero-copy tool operations via mmap ring buffers. SQLite data still
lives on disk, but tool calls go through SHM instead of stdio pipes.

Consistent with filesystem, thinking, and web servers.
"""

from __future__ import annotations

import sys
import os

# Paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # pdb/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # mcp-servers/
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "python", "src"
))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import pdb_tools
from shm_native_server import ShmNativeServer

if __name__ == "__main__":
    server = ShmNativeServer(
        "lumen-pdb-shm",
        pdb_tools.TOOLS,
        pdb_tools.HANDLERS,
        shm_size=4 * 1024 * 1024,  # 4 MiB — tool payloads are small
    )
    try:
        server.run()
    finally:
        server.cleanup()
