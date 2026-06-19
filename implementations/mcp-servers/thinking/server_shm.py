#!/usr/bin/env python3
"""
LUMEN Thinking MCP Server — Level 2 Shared Memory Transport.

Uses ShmNativeServer for zero-copy ring buffer communication.
Falls back to stdio if client doesn't support SHM.

All 29 cognitive tools available. Same handlers as server.py.
"""

from __future__ import annotations

import sys, os

# Paths
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # thinking/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # mcp-servers/
sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "python", "src"
))  # lumen package

# ── Windows UTF-8 ──
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from server import TOOLS, HANDLERS, _load_state, _save_state
from shm_native_server import ShmNativeServer
import server as _server  # for dashboard

if __name__ == "__main__":
    _load_state()
    
    # Dashboard (optional)
    if "--dashboard" in sys.argv:
        try:
            idx = sys.argv.index("--dashboard")
            port = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit() else 9876
        except (ValueError, IndexError):
            port = 9876
        try:
            _server._start_dashboard(port)
        except Exception as e:
            print(f"[lumen-shm] Dashboard failed: {e}", file=sys.stderr)
    
    server = ShmNativeServer(
        "lumen-thinking-shm",
        TOOLS,
        HANDLERS,
        shm_size=1024 * 1024,  # 1 MiB for large chains
    )
    try:
        server.run()
    finally:
        _save_state()  # persist before shutdown
        server.cleanup()
