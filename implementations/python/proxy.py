#!/usr/bin/env python3
"""
LUMEN → HTTP Proxy for Cadences Lab agents

Receives LUMEN binary frames via stdin, translates to JSON HTTP calls
to Cloudflare Workers, and returns LUMEN-encoded responses via stdout.

Usage:
  python proxy.py                          # stdio mode (for Hermes MCP)
  python proxy.py --http 9999              # HTTP server mode (for testing)
  python proxy.py --agent lisa --http 9999 # single-agent proxy

Protocol:
  Input frame:  {agent: "lisa", mensaje: "...", session_id: "...", macaroon: "..."}
  Output frame: {ok: true, respuesta: "...", agent: "lisa", ...}

Supports MUX: if mux_channels is present, fans out in parallel.
"""
import sys, os, json, time, asyncio, hmac, hashlib, urllib.request, traceback

# Add LUMEN to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..",
    "lumen-protocol", "implementations", "python", "src"))

from lumen import (
    compress_value, decompress_value,
    build_frame, build_size, parse_frame,
    TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED,
    ParseComplete, FrameAssembler
)

# ═══════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════

# Agent-specific parameter names
AGENT_PARAMS = {
    "zalo":  {"mensaje": "mensaje", "session": "session_id"},
    "lisa":  {"mensaje": "message", "session": "session_id"},
    "angi":  {"mensaje": "mensaje", "session": "session_id"},
    "tom":   {"mensaje": "text",     "session": "session_id"},
    "campo": {"mensaje": "mensaje",  "session": "session_id"},
    "gon":   {"mensaje": "mensaje",  "session": "session_id"},
}
    "zalo":    "https://workers.dev.internal/chat",
    "lisa":    "https://workers.dev.internal/chat",
    "angi":    "https://workers.dev.internal/chat",
    "tom":     "https://workers.dev.internal/chat",
    "campo":   "https://workers.dev.internal/chat",
    "gon":     "https://workers.dev.internal/chat",
}

SECRET = os.environ.get("LUMEN_SECRET", "zalo_dev_7f3a9c1e")
USER_AGENT = "Hermes-LUMEN-Proxy/2.0"
TIMEOUT = 30  # seconds per agent call
MUX_MAX_CONCURRENT = 3

# ═══════════════════════════════════════════════════════
# Macaroon
# ═══════════════════════════════════════════════════════

def make_macaroon(agent="hermes", ttl=3600):
    exp = int(time.time()) + ttl
    sig = hmac.new(SECRET.encode(), f"{agent}:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{agent}:{exp}:{sig}"

# ═══════════════════════════════════════════════════════
# HTTP forwarder
# ═══════════════════════════════════════════════════════

def forward_json(agent: str, mensaje: str, session_id: str = "", **kwargs) -> dict:
    """Forward a message to a CF worker via JSON HTTP."""
    url = WORKERS.get(agent)
    if not url:
        return {"ok": False, "error": f"unknown agent: {agent}", "agent": agent}

    params = AGENT_PARAMS.get(agent, {"mensaje": "mensaje", "session": "session_id"})
    body = json.dumps({
        params["mensaje"]: mensaje,
        params["session"]: session_id or f"proxy_{agent}_{int(time.time())}",
    }).encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", USER_AGENT)

    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        data = json.loads(resp.read())
        data["agent"] = agent
        return data
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")[:300]
        return {"ok": False, "error": f"HTTP {e.code}: {body}", "agent": agent}
    except Exception as e:
        return {"ok": False, "error": str(e), "agent": agent}

# ═══════════════════════════════════════════════════════
# LUMEN frame I/O (stdio mode)
# ═══════════════════════════════════════════════════════

class LumenProxy:
    """Read LUMEN frames from stdin, forward to workers, write LUMEN to stdout."""

    def __init__(self):
        self.assembler = FrameAssembler()

    def read_frame(self) -> dict | None:
        """Read one LUMEN frame from stdin. Returns parsed dict or None on EOF."""
        while True:
            chunk = sys.stdin.buffer.read(65536)
            if not chunk:
                return None
            result = self.assembler.push(chunk)
            if result is not None:
                frame = result.frame
                payload = frame.payload
                if frame.flags & FLAG_COMPRESSED:
                    payload = decompress_value(payload)
                return payload

    def write_frame(self, data: dict):
        """Write one LUMEN frame to stdout."""
        payload = compress_value(data)
        size = build_size(len(payload))
        buf = bytearray(size)
        build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()

    def handle(self, msg: dict) -> dict:
        """Process one message: extract agent + mensaje, forward, return result."""
        agent = msg.get("agent", "zalo")
        mensaje = msg.get("mensaje", "")
        session_id = msg.get("session_id", "")

        if not mensaje:
            # Check for MUX channels
            mux = msg.get("mux_channels")
            if mux and isinstance(mux, list):
                return self._handle_mux(mux)

        if not mensaje:
            return {"ok": False, "error": "mensaje required"}

        return forward_json(agent, mensaje, session_id)

    def _handle_mux(self, channels: list) -> dict:
        """Fan out MUX channels sequentially (simpler than async)."""
        results = []
        for ch in channels:
            agent = ch.get("agent", "zalo")
            mensaje = ch.get("mensaje", "")
            sid = ch.get("session_id", "")
            results.append(forward_json(agent, mensaje, sid))
        return {
            "ok": True,
            "respuesta": f"MUX: {len(results)} channels",
            "mux_results": results,
        }

    def run(self):
        """Main loop: read frame, process, write response."""
        while True:
            msg = self.read_frame()
            if msg is None:
                break
            try:
                result = self.handle(msg)
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            self.write_frame(result)

# ═══════════════════════════════════════════════════════
# HTTP server mode (for testing)
# ═══════════════════════════════════════════════════════

def run_http_server(port: int, default_agent: str | None = None):
    """Run as HTTP server: POST /v1/chat with LUMEN body → forward → LUMEN response."""
    import http.server

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            if self.path not in ("/v1/chat", "/chat", "/"):
                self.send_error(404)
                return

            ct = self.headers.get("Content-Type", "")
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length) if length > 0 else b""

            # Parse LUMEN or JSON
            if "application/lumen" in ct:
                result = parse_frame(body, 0)
                if isinstance(result, ParseComplete):
                    payload = result.frame.payload
                    if result.frame.flags & FLAG_COMPRESSED:
                        payload = decompress_value(payload)
                    msg = payload
                else:
                    self.send_error(400, f"Invalid LUMEN frame: {result.kind}")
                    return
            else:
                try:
                    msg = json.loads(body)
                except json.JSONDecodeError:
                    self.send_error(400, "Invalid JSON")
                    return

            # Inject agent if default
            if default_agent and "agent" not in msg:
                msg["agent"] = default_agent

            # Forward
            proxy = LumenProxy()
            result = proxy.handle(msg)

            # Encode as LUMEN
            payload = compress_value(result)
            size = build_size(len(payload))
            frame = bytearray(size)
            build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, frame, 0)

            self.send_response(200)
            self.send_header("Content-Type", "application/lumen")
            self.send_header("Content-Length", str(len(frame)))
            self.end_headers()
            self.wfile.write(bytes(frame))

        def log_message(self, format, *args):
            pass  # silent

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    print(f"🌐 LUMEN Proxy HTTP on http://127.0.0.1:{port}")
    if default_agent:
        print(f"   Default agent: {default_agent}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Shutting down")

# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description="LUMEN → HTTP Proxy for Cadences Lab agents")
    p.add_argument("--http", type=int, help="Run as HTTP server on PORT")
    p.add_argument("--agent", type=str, help="Default agent for single-agent proxy")
    args = p.parse_args()

    if args.http:
        run_http_server(args.http, args.agent)
    else:
        # stdio mode (for Hermes MCP)
        proxy = LumenProxy()
        proxy.run()
