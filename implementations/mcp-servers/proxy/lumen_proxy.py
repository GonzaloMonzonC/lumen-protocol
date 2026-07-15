"""
LUMEN → HTTP Proxy for Cloudflare Workers
==========================================
Translates LUMEN binary frames to JSON HTTP calls for workers
that don't speak LUMEN native yet (Lisa, Tom, Angi, Campo, Gon).

Usage:
    python lumen_proxy.py [--port 8765]

Architecture:
    Hermes → LUMEN frame → Proxy(localhost:8765) → JSON HTTP → Worker
    Worker → JSON HTTP → Proxy → LUMEN frame → Hermes

The proxy maps agent names to their Cloudflare Worker URLs.
Add new agents to AGENT_URLS below.
"""
import sys, json, os, time, urllib.request, http.server
from pathlib import Path

# Add LUMEN Python to path
sys.path.insert(0, str(Path(__file__).parent.parent / "lumen-protocol" / "implementations" / "python" / "src"))

try:
    from lumen import compress_value, decompress_value, build_frame, build_size, parse_frame
    from lumen import TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED, ParseComplete
    HAS_LUMEN = True
except ImportError:
    HAS_LUMEN = False
    print("⚠️  lumen-mcp not found. Install: pip install lumen-mcp")

# ═══════════════════════════════════════════════════════
# Agent registry — maps agent name to worker URL
# ═══════════════════════════════════════════════════════

AGENT_URLS = {
    "zalo":   "https://workers.dev.internal/chat",
    "lisa":   "https://workers.dev.internal/chat",
    "tom":    "https://workers.dev.internal/chat",
    "angi":   "https://workers.dev.internal/chat",
    "campo":  "https://workers.dev.internal/chat",
    "gon":    "https://workers.dev.internal/chat",
}

# Aliases
AGENT_ALIASES = {
    "lisa": "lisa",
    "tom": "tom",
    "angi": "angi",
    "campo": "campo",
    "gon": "gon",
    "g": "gon",
    "z": "zalo",
}

# ═══════════════════════════════════════════════════════
# LUMEN ↔ HTTP translation
# ═══════════════════════════════════════════════════════

def lumen_to_json(lumen_body: bytes) -> tuple[str, dict, str]:
    """
    Decode a LUMEN frame into (agent_name, json_body, session_id).
    Frame payload: {agent: "zalo", mensaje: "...", session_id: "...", ...}
    """
    result = parse_frame(bytearray(lumen_body), 0)
    if not isinstance(result, ParseComplete):
        raise ValueError(f"Invalid LUMEN frame: {result.kind}")

    frame = result.frame
    if frame.frame_type != TYPE_REQUEST:
        raise ValueError(f"Expected REQUEST, got type {frame.frame_type}")

    data = decompress_value(frame.payload)
    if not isinstance(data, dict):
        raise ValueError(f"Expected dict, got {type(data)}")

    agent = data.get("agent", "zalo")
    session_id = data.get("session_id", f"proxy_{int(time.time())}")

    return agent, data, session_id


def json_to_lumen(response_json: dict) -> bytes:
    """Encode a JSON response as a LUMEN binary frame."""
    payload = compress_value(response_json)
    buf = bytearray(build_size(len(payload)))
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
    return bytes(buf)


def forward_to_agent(agent: str, body: dict) -> tuple[int, dict]:
    """
    Forward a request to a Cloudflare Worker via HTTP JSON.
    Returns (http_status, response_dict).
    """
    url = AGENT_URLS.get(agent)
    if not url:
        return 404, {"ok": False, "error": f"Unknown agent: {agent}"}

    # Build JSON payload for the worker's /v1/chat
    json_payload = json.dumps({
        "mensaje": body.get("mensaje", ""),
        "session_id": body.get("session_id", ""),
    }).encode()

    req = urllib.request.Request(url, data=json_payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "LumenProxy/1.0")

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = json.loads(resp.read())
        return resp.status, {
            "ok": data.get("ok", True),
            "respuesta": data.get("respuesta", ""),
            "session": data.get("session", ""),
            "agent": agent,
            "via": "lumen-proxy",
        }
    except urllib.error.HTTPError as e:
        return e.code, {"ok": False, "error": f"HTTP {e.code} from {agent}"}
    except Exception as e:
        return 502, {"ok": False, "error": f"Proxy error: {e}"}


# ═══════════════════════════════════════════════════════
# HTTP Server
# ═══════════════════════════════════════════════════════

METRICS = {"lumen_requests": 0, "json_requests": 0, "errors": 0, "agents": {}}

class LumenProxyHandler(http.server.BaseHTTPRequestHandler):
    """Handles incoming LUMEN binary requests, forwards to workers."""

    def log_message(self, format, *args):
        """Suppress default logging to stderr."""
        pass

    def do_POST(self):
        content_type = self.headers.get("Content-Type", "")
        content_length = int(self.headers.get("Content-Length", 0))
        sys.stderr.write(f"[proxy] POST CT={content_type} CL={content_length}\n")
        sys.stderr.flush()
        open("/tmp/proxy_debug.log", "a").write(f"POST CT={content_type} CL={content_length}\n")

        if not content_length:
            self.send_error(400, "Empty body")
            return

        body = self.rfile.read(content_length)
        open("/tmp/proxy_debug.log", "a").write(f"Body read: {len(body)} bytes\n")

        # ── LUMEN binary path ──
        if "application/lumen" in content_type:
            METRICS["lumen_requests"] += 1
            try:
                agent, request_data, session_id = lumen_to_json(body)
                METRICS["agents"][agent] = METRICS["agents"].get(agent, 0) + 1

                status, response_data = forward_to_agent(agent, request_data)

                if status == 200:
                    # Encode successful response as LUMEN binary
                    lumen_resp = json_to_lumen(response_data)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/lumen")
                    self.send_header("X-Agent", agent)
                    self.end_headers()
                    self.wfile.write(lumen_resp)
                else:
                    # Forward HTTP error as LUMEN error frame
                    error_resp = json_to_lumen(response_data)
                    self.send_response(status)
                    self.send_header("Content-Type", "application/lumen")
                    self.end_headers()
                    self.wfile.write(error_resp)

            except Exception as e:
                import traceback
                sys.stderr.write(f"[proxy] ERROR: {e}\n{traceback.format_exc()}\n")
                METRICS["errors"] += 1
                err = json_to_lumen({"ok": False, "error": str(e)})
                self.send_response(400)
                self.send_header("Content-Type", "application/lumen")
                self.end_headers()
                self.wfile.write(err)
            return

        # ── JSON fallback (for health checks) ──
        METRICS["json_requests"] += 1
        try:
            data = json.loads(body)
            agent = data.get("agent", "zalo")
            status, response_data = forward_to_agent(agent, data)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response_data).encode())
        except Exception as e:
            METRICS["errors"] += 1
            self.send_error(400, str(e))

    def do_GET(self):
        """Health check and metrics."""
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"OK")
        elif self.path == "/metrics":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "proxy": "lumen-proxy",
                "version": "1.0.0",
                "uptime_seconds": int(time.time() - START_TIME),
                **METRICS,
            }, indent=2).encode())
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"LUMEN Proxy -- POST application/lumen to /")


# ═══════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════

START_TIME = time.time()

def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

    if not HAS_LUMEN:
        print("❌ lumen-mcp not installed. Run: pip install lumen-mcp")
        sys.exit(1)

    print(f"🔌 LUMEN Proxy v1.0.0 — localhost:{port}")
    print(f"   Agents: {', '.join(AGENT_URLS.keys())}")
    print(f"   POST application/lumen → LUMEN binary")
    print(f"   POST application/json  → JSON passthrough")
    print(f"   GET  /health, /metrics")

    server = http.server.HTTPServer(("127.0.0.1", port), LumenProxyHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Proxy stopped.")


if __name__ == "__main__":
    main()
