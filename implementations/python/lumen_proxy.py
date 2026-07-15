"""
LUMEN→HTTP Proxy — Grupo 2
Traduce LUMEN binary frames a HTTP/JSON para workers que aún no hablan LUMEN.
Workers: Lisa, Tom, Angi, Campo, Gon (Zalo ya habla LUMEN nativo).

Uso: python lumen_proxy.py [--port 19876]
"""
import sys, os, json, time, urllib.request, threading
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, r"C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\python\src")
from lumen import compress_value, decompress_value, build_frame, build_size, parse_frame
from lumen import TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED, ParseComplete

PORT = int(sys.argv[2]) if len(sys.argv) > 2 else 19876

# Agent → Worker URL mapping
AGENTS = {
    "lisa":  "https://workers.dev.internal/chat",
    "tom":   "https://workers.dev.internal/chat",
    "angi":  "https://workers.dev.internal/chat",
    "campo": "https://workers.dev.internal/chat",
    "gon":   "https://workers.dev.internal/chat",
}

# Auth keys (same as what agents expect)
AGENT_KEYS = json.loads(os.environ.get("AGENT_KEYS", "{}"))

UA = "Hermes-LUMEN-Proxy/2.0"

# Metrics
proxied_requests = 0
lumen_requests = 0
start_time = time.time()

def proxy_to_worker(agent: str, mensaje: str, session_id: str = "proxy") -> dict:
    """Send a JSON request to a worker and return the parsed response."""
    url = AGENTS.get(agent)
    if not url:
        return {"ok": False, "error": f"unknown agent: {agent}"}

    body = json.dumps({"mensaje": mensaje, "session_id": session_id}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", UA)

    # Add API key if available
    api_key = AGENT_KEYS.get(agent, "")
    if api_key:
        req.add_header("x-api-key", api_key)

    try:
        resp = urllib.request.urlopen(req, timeout=30)
        return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.reason}"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


class LumenProxyHandler(BaseHTTPRequestHandler):
    """Handles LUMEN binary requests, proxies to workers, returns LUMEN binary."""

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            uptime = int(time.time() - start_time)
            self.wfile.write(json.dumps({
                "ok": True, "proxy": "lumen-proxy", "port": PORT,
                "uptime_s": uptime, "proxied": proxied_requests,
                "agents": list(AGENTS.keys()),
            }).encode())
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        global proxied_requests, lumen_requests

        # Only handle /v1/chat
        if self.path != "/v1/chat":
            self.send_response(404)
            self.end_headers()
            return

        content_type = self.headers.get("Content-Type", "")

        # ── LUMEN binary path ──
        if "application/lumen" in content_type:
            lumen_requests += 1
            try:
                # Read LUMEN frame
                content_len = int(self.headers.get("Content-Length", "0"))
                body = self.rfile.read(content_len)

                # Parse frame
                result = parse_frame(body, 0)
                if result.kind != "complete":
                    raise ValueError(f"Invalid frame: {result.kind}")

                frame = result.frame
                if frame.frameType != TYPE_REQUEST:
                    raise ValueError(f"Expected TYPE_REQUEST")

                # Decompress payload
                data = decompress_value(frame.payload) if frame.flags & FLAG_COMPRESSED else frame.payload
                if not isinstance(data, dict):
                    raise ValueError("Payload not a dict")

                # Extract target agent + message
                target_agent = data.get("target_agent", data.get("agent_id", "lisa"))
                mensaje = data.get("mensaje", "")
                session_id = data.get("session_id", "proxy")

                if not mensaje:
                    raise ValueError("No mensaje in payload")

                print(f"[proxy] → {target_agent}: {mensaje[:60]}...")

                # Proxy to worker
                worker_response = proxy_to_worker(target_agent, mensaje, session_id)
                proxied_requests += 1

                # Encode as LUMEN response
                resp_payload = compress_value(worker_response)
                resp_frame = bytearray(build_size(len(resp_payload)))
                build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, resp_payload, resp_frame, 0)

                self.send_response(200)
                self.send_header("Content-Type", "application/lumen")
                self.send_header("Content-Length", str(len(resp_frame)))
                self.end_headers()
                self.wfile.write(resp_frame)
                return

            except Exception as e:
                print(f"[proxy] ERROR: {e}")
                self.send_response(400)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"ok": False, "error": str(e)}).encode())
                return

        # ── JSON passthrough (for testing) ──
        elif "application/json" in content_type:
            content_len = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(content_len))
            target_agent = body.get("target_agent", body.get("agent_id", "lisa"))
            mensaje = body.get("mensaje", "")
            session_id = body.get("session_id", "proxy")

            worker_response = proxy_to_worker(target_agent, mensaje, session_id)
            proxied_requests += 1

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(worker_response).encode())
            return

        else:
            self.send_response(415)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "ok": False,
                "error": "Unsupported Content-Type. Use application/lumen or application/json"
            }).encode())

    def log_message(self, format, *args):
        """Quiet logging."""
        pass


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), LumenProxyHandler)
    print(f"🔌 LUMEN Proxy running on http://127.0.0.1:{PORT}")
    print(f"   Agents: {', '.join(AGENTS.keys())}")
    print(f"   Health: http://127.0.0.1:{PORT}/health")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Proxy stopped")
        server.shutdown()
