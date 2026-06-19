#!/usr/bin/env python3
"""
LUMEN Web MCP Server — Level 2 Shared Memory Transport.

Zero-copy web results. Large HTML extracts go through mmap ring buffers.
"""

from __future__ import annotations

import sys, os

# Paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # web/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # mcp-servers/
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "python", "src"
))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from server import TOOLS, HANDLERS
from shm_native_server import ShmNativeServer

if __name__ == "__main__":
    server = ShmNativeServer(
        "lumen-web-shm",
        TOOLS,
        HANDLERS,
        shm_size=512 * 1024,  # 512 KiB for web content
    )
    try:
        server.run()
    finally:
        server.cleanup()
