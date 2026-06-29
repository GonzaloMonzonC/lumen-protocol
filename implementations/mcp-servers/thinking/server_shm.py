#!/usr/bin/env python3
"""
LUMEN Thinking MCP Server — Level 2 Shared Memory Transport.

Uses ShmNativeServer for zero-copy ring buffer communication.
Falls back to stdio if client doesn't support SHM.

All 29 cognitive tools available. Same handlers as server.py.
"""

from __future__ import annotations

import sys, os, time

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

    # Dashboard (optional) — runs in a daemon thread alongside SHM server
    if "--dashboard" in sys.argv:
        try:
            idx = sys.argv.index("--dashboard")
            port = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) and sys.argv[idx + 1].isdigit() else 9876
        except (ValueError, IndexError):
            port = 9876
        import threading
        dashboard_thread = threading.Thread(
            target=lambda: _server._start_dashboard(port),
            daemon=True,
            name="lumen-dashboard"
        )
        dashboard_thread.start()
        print(f"[lumen-shm] Dashboard started on port {port} (background thread)", file=sys.stderr)

    standalone = "--standalone" in sys.argv

    if standalone:
        # Standalone mode: keep alive with HTTP/WS dashboard, no stdin loop.
        import signal
        _running = True
        def _handle_signal(signum, frame):
            global _running
            _running = False
        signal.signal(signal.SIGTERM, _handle_signal)
        signal.signal(signal.SIGINT, _handle_signal)
        try:
            while _running:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        finally:
            _save_state()
        print("[lumen-shm] Shutdown complete.")
    else:
        # MCP mode: run SHM server loop (reads stdin for MCP JSON-RPC)
        server = ShmNativeServer(
            f"lumen-thinking-shm-{os.getpid()}",
            TOOLS,
            HANDLERS,
            shm_size=1024 * 1024,  # 1 MiB for large chains
        )
        try:
            server.run()
        finally:
            _save_state()  # persist before shutdown
            server.cleanup()
