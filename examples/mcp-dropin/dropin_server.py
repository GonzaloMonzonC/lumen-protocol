#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════════════════╗
║                      LUMEN MCP DROP-IN  -  v1.0                            ║
║          "Your MCP server. Our wire. Zero code changes."                   ║
╚══════════════════════════════════════════════════════════════════════════════╝

A production-style MCP HTTP server that demonstrates LUMEN as a transparent
wire-format upgrade: clients send standard JSON-RPC, the server auto-detects
and can respond in JSON-RPC or LUMEN binary format.

Usage:
    python dropin_server.py                     # port 9090
    python dropin_server.py --port 8080         # custom port
    python dropin_server.py --accept-lumens     # negotiate LUMEN responses

Endpoints:
    POST /rpc           Standard MCP JSON-RPC endpoint
    POST /rpc?lumen=1   Accept LUMEN binary responses
    GET  /              Live dashboard
    GET  /stats         JSON stats summary

Test with curl:
    curl -X POST http://localhost:9090/rpc -H "Content-Type: application/json" -d ""{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}""
    curl -X POST "http://localhost:9090/rpc?lumen=1" -H "Content-Type: application/json" -d ""{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\"}""

Requires: pip install -e implementations/python
"""

from __future__ import annotations

import argparse
import http.server
import json
import os
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, urlparse

try:
    from lumen import compress_value
    from lumen.frame import (
        build_size, build_frame, FLAG_COMPRESSED,
        TYPE_NOTIFY, TYPE_RESPONSE, TYPE_REQUEST,
    )
except ImportError:
    print("\n  LUMEN Python package required.")
    print("  Install: pip install -e implementations/python")
    sys.exit(1)


# ═══════════════════════════════════════════════════════════════════════════════
# Tool implementations
# ═══════════════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "echo",
        "description": "Echo back the input message. Useful for testing connectivity.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "The message to echo"},
                "repeat": {"type": "integer", "description": "Number of times to repeat", "default": 1},
            },
            "required": ["message"],
        },
    },
    {
        "name": "get_time",
        "description": "Get the current server time in ISO 8601 format.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string", "description": "IANA timezone (e.g. UTC, America/New_York)", "default": "UTC"},
                "format": {"type": "string", "enum": ["iso", "unix", "human"], "description": "Output format", "default": "iso"},
            },
        },
    },
    {
        "name": "file_info",
        "description": "Retrieve metadata about a file (simulated).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to inspect"},
            },
            "required": ["path"],
        },
    },
    {
        "name": "search_code",
        "description": "Search for patterns in the codebase (simulated).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory to search in", "default": "."},
                "max_results": {"type": "integer", "description": "Max results to return", "default": 20},
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "get_health",
        "description": "Return server health status and wire statistics.",
        "inputSchema": {
            "type": "object",
            "properties": {},
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any], stats: Stats) -> dict[str, Any]:
    """Execute a tool call and return the result."""
    if name == "echo":
        msg = arguments.get("message", "")
        repeat = min(int(arguments.get("repeat", 1)), 10)
        return {"echo": msg * repeat, "length": len(msg * repeat)}

    elif name == "get_time":
        fmt = arguments.get("format", "iso")
        now = time.time()
        if fmt == "unix":
            return {"time": now}
        elif fmt == "human":
            return {"time": time.ctime(now)}
        else:
            return {"time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}

    elif name == "file_info":
        path = arguments.get("path", "/")
        import random
        random.seed(hash(path) & 0xFFFFFFFF)
        return {
            "path": path,
            "size_bytes": random.randint(1024, 1048576),
            "modified": "2024-12-15T10:30:00Z",
            "permissions": "0644",
            "type": "file",
            "language": path.rsplit(".", 1)[-1] if "." in path else "unknown",
        }

    elif name == "search_code":
        pattern = arguments.get("pattern", "")
        max_results = min(int(arguments.get("max_results", 20)), 100)
        import random
        random.seed(hash(pattern) & 0xFFFFFFFF)
        results = []
        for i in range(min(random.randint(1, max_results), max_results)):
            results.append({
                "file": f"src/module_{random.randint(1,20):03d}.py",
                "line": random.randint(1, 500),
                "column": random.randint(1, 80),
                "match": f"...{pattern}_{random.randint(100,999)}...",
            })
        return {"matches": len(results), "results": results}

    elif name == "get_health":
        return {
            "status": "healthy",
            "uptime_seconds": time.time() - stats.start_time,
            "requests_served": stats.total_requests,
            "json_bytes_served": stats.total_json_bytes,
            "lumen_bytes_served": stats.total_lumen_bytes,
            "savings_pct": round((1 - stats.total_lumen_bytes / max(stats.total_json_bytes, 1)) * 100, 1),
        }

    return {"error": f"Unknown tool: {name}"}


# ═══════════════════════════════════════════════════════════════════════════════
# Statistics tracker
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class Stats:
    start_time: float = field(default_factory=time.time)
    total_requests: int = 0
    total_json_bytes: int = 0
    total_lumen_bytes: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def record(self, json_bytes: int, lumen_bytes: int) -> None:
        with self._lock:
            self.total_requests += 1
            self.total_json_bytes += json_bytes
            self.total_lumen_bytes += lumen_bytes

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "total_requests": self.total_requests,
                "total_json_bytes": self.total_json_bytes,
                "total_lumen_bytes": self.total_lumen_bytes,
                "savings_pct": round(
                    (1 - self.total_lumen_bytes / max(self.total_json_bytes, 1)) * 100, 1
                ),
                "uptime_seconds": time.time() - self.start_time,
            }


# ═══════════════════════════════════════════════════════════════════════════════
# MCP request processing
# ═══════════════════════════════════════════════════════════════════════════════

def handle_mcp_request(body: bytes, stats: Stats) -> dict[str, Any]:
    """Process an MCP JSON-RPC request and return the response dict."""
    try:
        request = json.loads(body)
    except json.JSONDecodeError:
        return {
            "jsonrpc": "2.0",
            "error": {"code": -32700, "message": "Parse error"},
        }

    rid = request.get("id")
    method = request.get("method", "")

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {
                    "name": "lumen-dropin-demo",
                    "version": "1.0.0",
                },
                "capabilities": {
                    "tools": {},
                    "resources": {"subscribe": True},
                },
            },
        }

    elif method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {"tools": TOOLS},
        }

    elif method == "tools/call":
        params = request.get("params", {})
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = execute_tool(tool_name, arguments, stats)
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "result": {
                "content": [{"type": "text", "text": json.dumps(result)}],
                "data": result,
            },
        }

    elif method == "notifications/initialized":
        return {"jsonrpc": "2.0"}  # No id for notifications

    else:
        return {
            "jsonrpc": "2.0",
            "id": rid,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

# ═══════════════════════════════════════════════════════════════════════════════
# HTTP Server
# ═══════════════════════════════════════════════════════════════════════════════

DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LUMEN MCP Drop-In — Live Dashboard</title>
<style>
  :root { --bg: #0a0a0f; --card: #13131a; --accent: #7c3aed; --text: #e2e8f0; --muted: #94a3b8; --green: #10b981; --red: #ef4444; }
  * { margin:0; padding:0; box-sizing:border-box; }
  body { font-family: system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; }
  header { background: var(--card); border-bottom: 1px solid #1e1e2e; padding: 20px 40px; display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.5rem; font-weight: 700; }
  header h1 span { color: var(--accent); }
  .badge { background: var(--accent); color: white; padding: 4px 12px; border-radius: 20px; font-size: 0.75rem; font-weight: 600; }
  main { max-width: 900px; margin: 30px auto; padding: 0 20px; }
  .cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 16px; margin-bottom: 30px; }
  .card { background: var(--card); border: 1px solid #1e1e2e; border-radius: 12px; padding: 20px; }
  .card .label { font-size: 0.8rem; color: var(--muted); margin-bottom: 6px; text-transform: uppercase; letter-spacing: 0.5px; }
  .card .value { font-size: 1.8rem; font-weight: 700; }
  .card .value.savings { color: var(--green); }
  .bars { display: flex; gap: 4px; align-items: flex-end; height: 100px; margin-top: 10px; }
  .bar { flex:1; border-radius: 2px 2px 0 0; transition: height .3s; }
  .bar.json { background: #334155; }
  .bar.lumen { background: var(--accent); }
  .legend { display: flex; gap: 20px; margin-top: 8px; font-size: 0.75rem; color: var(--muted); }
  .legend span { display: inline-block; width: 10px; height: 10px; border-radius: 2px; margin-right: 4px; vertical-align: middle; }
  .legend .json-dot { background: #334155; }
  .legend .lumen-dot { background: var(--accent); }
  table { width: 100%; border-collapse: collapse; margin-top: 10px; }
  th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #1e1e2e; }
  th { font-size: 0.75rem; color: var(--muted); text-transform: uppercase; }
  .curl-box { background: #0d0d15; border: 1px solid #1e1e2e; border-radius: 8px; padding: 16px; margin-top: 16px; font-family: monospace; font-size: 0.8rem; overflow-x: auto; }
  .curl-box .cmd { color: var(--green); }
  .curl-box .url { color: #93c5fd; }
  .endpoint { display: flex; gap: 10px; align-items: center; margin-bottom: 8px; }
  .method { font-weight: 700; font-size: 0.7rem; padding: 2px 8px; border-radius: 4px; }
  .method.post { background: #1e40af; color: #93c5fd; }
  .method.get { background: #166534; color: #86efac; }
  .path { font-family: monospace; color: #93c5fd; }
</style>
</head>
<body>
<header>
  <h1><span>◆</span> LUMEN MCP Drop-In</h1>
  <div style="display:flex;gap:10px;">
    <span class="badge" id="status">● LIVE</span>
  </div>
</header>
<main>
  <div class="cards">
    <div class="card">
      <div class="label">Requests Served</div>
      <div class="value" id="total-reqs">0</div>
    </div>
    <div class="card">
      <div class="label">JSON Wire</div>
      <div class="value" id="json-bytes">0 B</div>
    </div>
    <div class="card">
      <div class="label">LUMEN Wire</div>
      <div class="value" id="lumen-bytes">0 B</div>
    </div>
    <div class="card">
      <div class="label">Wire Savings</div>
      <div class="value savings" id="savings">0%</div>
    </div>
  </div>

  <div class="card">
    <div class="label">Last 20 Wire Sizes (JSON vs LUMEN)</div>
    <div class="bars" id="viz"></div>
    <div class="legend">
      <span><span class="json-dot"></span> JSON-RPC</span>
      <span><span class="lumen-dot"></span> LUMEN</span>
    </div>
  </div>

  <div class="card" style="margin-top:20px;">
    <div class="label">API Endpoints</div>
    <div class="endpoint"><span class="method post">POST</span><span class="path">/rpc</span> <span style="color:var(--muted);">— Standard JSON-RPC MCP</span></div>
    <div class="endpoint"><span class="method post">POST</span><span class="path">/rpc?lumen=1</span> <span style="color:var(--muted);">— JSON-RPC in, LUMEN binary out</span></div>
    <div class="endpoint"><span class="method get">GET</span><span class="path">/stats</span> <span style="color:var(--muted);">— JSON statistics</span></div>
    <div class="curl-box">
      <div><span class="cmd">curl</span> -X POST <span class="url">http://localhost:PORT/rpc</span> \</div>
      <div>  -H "Content-Type: application/json" \</div>
      <div>  -d ""{"jsonrpc":"2.0","id":1,"method":"tools/list"}""</div>
    </div>
    <div class="curl-box" style="margin-top:8px;">
      <div><span class="cmd">curl</span> -X POST <span class="url">"http://localhost:PORT/rpc?lumen=1"</span> \</div>
      <div>  -H "Content-Type: application/json" \</div>
      <div>  -o response.bin \</div>
      <div>  -d ""{"jsonrpc":"2.0","id":1,"method":"tools/list"}""</div>
    </div>
  </div>
</main>
<script>
const PORT = location.port || 9090;
async function refresh() {
  try {
    const r = await fetch("/stats");
    const s = await r.json();
    document.getElementById("total-reqs").textContent = s.total_requests;
    document.getElementById("json-bytes").textContent = fmtBytes(s.total_json_bytes);
    document.getElementById("lumen-bytes").textContent = fmtBytes(s.total_lumen_bytes);
    document.getElementById("savings").textContent = s.savings_pct + "%";
    if (s.recent) drawBars(s.recent);
  } catch(e) {}
}
function fmtBytes(b) {
  if (b >= 1048576) return (b/1048576).toFixed(1) + " MB";
  if (b >= 1024) return (b/1024).toFixed(1) + " KB";
  return b + " B";
}
function drawBars(recents) {
  const viz = document.getElementById("viz");
  viz.innerHTML = "";
  const max = Math.max(...recents.map(r => r.json), 1);
  for (const r of recents.slice(-20)) {
    const jsonH = (r.json / max * 100).toFixed(0);
    const lumenH = (r.lumen / max * 100).toFixed(0);
    viz.innerHTML += `<div style="display:flex;flex-direction:column;align-items:center;flex:1;gap:1px;">
      <div class="bar json" style="height:${jsonH}px"></div>
      <div class="bar lumen" style="height:${lumenH}px"></div>
    </div>`;
  }
}
setInterval(refresh, 2000);
refresh();
</script>
</body>
</html>"""


# Store recent measurements for the dashboard
_recent_wires: list[dict[str, int]] = []


class MCPHandler(http.server.BaseHTTPRequestHandler):
    """HTTP request handler for MCP endpoints."""

    # Class-level reference to shared state
    stats: Stats = None  # type: ignore
    server_port: int = 9090

    def log_message(self, format, *args):
        """Suppress default logging; we have our own."""
        pass

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_lumen(self, data: dict) -> None:
        """Compress and send as LUMEN binary frame."""
        compressed = compress_value(data)
        frame_size = build_size(payload_len=len(compressed))
        buf = bytearray(frame_size)
        build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, compressed, buf, 0)
        self.send_response(200)
        self.send_header("Content-Type", "application/lumen+binary")
        self.send_header("Content-Length", str(frame_size))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("X-Lumen-Frame-Type", "response")
        self.send_header("X-Lumen-Compressed", "true")
        self.end_headers()
        self.wfile.write(buf[:frame_size])

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Accept")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)

        if parsed.path == "/" or parsed.path == "/dashboard":
            html = DASHBOARD_HTML.replace("PORT", str(self.server_port))
            body = html.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        elif parsed.path == "/stats":
            snap = self.stats.snapshot()
            snap["recent"] = list(_recent_wires[-20:])
            self._send_json(snap)

        else:
            self._send_json({"error": "Not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)
        use_lumen = "lumen" in params and params["lumen"][0] == "1"

        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len) if content_len > 0 else b""

        # Process MCP request
        json_resp = handle_mcp_request(body, self.stats)

        # Measure wire sizes
        json_wire = len(json.dumps(json_resp, ensure_ascii=False).encode("utf-8"))
        compressed = compress_value(json_resp)
        lumen_wire = build_size(payload_len=len(compressed))

        self.stats.record(json_wire, lumen_wire)
        _recent_wires.append({"json": json_wire, "lumen": lumen_wire})
        if len(_recent_wires) > 100:
            _recent_wires[:] = _recent_wires[-50:]

        if use_lumen:
            self._send_lumen(json_resp)
        else:
            self._send_json(json_resp)


# ═══════════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="LUMEN MCP Drop-In — transparent wire-format upgrade for MCP servers"
    )
    parser.add_argument("--port", type=int, default=9090,
                        help="HTTP server port (default: 9090)")
    parser.add_argument("--bind", type=str, default="127.0.0.1",
                        help="Bind address (default: 127.0.0.1)")
    args = parser.parse_args()

    stats = Stats()

    handler = MCPHandler
    handler.stats = stats
    handler.server_port = args.port

    server = http.server.HTTPServer((args.bind, args.port), handler)

    print()
    print("  " + "\u2550" * 68)
    print("  \u2551" + "LUMEN MCP Drop-In Server".center(66) + "\u2551")
    print("  \u2551" + "\"Your MCP server. Our wire. Zero code changes.\"".center(66) + "\u2551")
    print("  " + "\u2550" * 68)
    print()
    print(f"  Server listening on http://{args.bind}:{args.port}")
    print()
    print("  Endpoints:")
    print(f"    Dashboard  \u2192 http://{args.bind}:{args.port}/")
    print(f"    JSON-RPC   \u2192 POST http://{args.bind}:{args.port}/rpc")
    print(f"    LUMEN      \u2192 POST http://{args.bind}:{args.port}/rpc?lumen=1")
    print(f"    Stats      \u2192 GET  http://{args.bind}:{args.port}/stats")
    print()
    print("  Tools registered:")
    for t in TOOLS:
        print(f"    \u2022 {t['name']:<15} — {t['description']}")
    print()
    print("  Quick test:")
    print(f'    curl -X POST http://{args.bind}:{args.port}/rpc -H "Content-Type: application/json" -d "{{\\\\"jsonrpc\\\\\\":\\\\\\"2.0\\\\\\",\\\\\\"id\\\\\\":1,\\\\\\"method\\\\\\":\\\\\\"tools/list\\\\\\"}}"')
    print()
    print("  Press Ctrl+C to stop.")
    print()

    # Graceful shutdown
    def shutdown(sig, frame):
        print("\n  Shutting down...")
        snap = stats.snapshot()
        print(f"  Served {snap['total_requests']} requests")
        print(f"  LUMEN saved {snap['savings_pct']}% wire size")
        server.shutdown()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
