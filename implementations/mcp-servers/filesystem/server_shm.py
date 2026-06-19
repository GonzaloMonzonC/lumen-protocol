#!/usr/bin/env python3
"""
LUMEN Filesystem MCP Server — Level 2 Shared Memory Transport.

Zero-copy file operations. Large file contents go through mmap
ring buffers instead of stdio pipes.
"""

from __future__ import annotations

import sys, os

# Paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # filesystem/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # mcp-servers/
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
        "lumen-filesystem-shm",
        shared_tools.TOOLS,
        shared_tools.HANDLERS,
        shm_size=8 * 1024 * 1024,  # 8 MiB for large files
    )
    try:
        server.run()
    finally:
        server.cleanup()
