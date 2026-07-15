"""
LUMEN Gateway Proxy — traduit frames LUMEN a HTTP/JSON para Cloudflare Workers.
Escucha en localhost:9090, acepta LUMEN binary frames, los reenvía como JSON
a los workers que aún no tienen LUMEN nativo.

Uso:
  python lumen_proxy.py
  # POST http://localhost:9090/v1/chat/lisa
  # Content-Type: application/lumen
  # Body: [LUMEN frame con {mensaje, macaroon, target}]
"""
import sys, os, json, hmac, hashlib, time, urllib.request, urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

sys.path.insert(0, r"C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\python\src")
from lumen import compress_value, decompress_value, build_frame, build_size, parse_frame
from lumen import TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED, ParseComplete

# ── Config ──
HOST = "127.0.0.1"
PORT = 9090
AGENT_URLS = {
    "zalo":  "https://workers.dev.internal/chat",
    "lisa":  "https://workers.dev.internal/chat",
    "tom":   "https://workers.dev.internal/chat",
    "angi":  "https://workers.dev.internal/chat",
    "campo": "https://workers.dev.internal/chat",
    "gon":   "https://workers.dev.internal/chat",
}

# ── Helpers ──
def create_macaroon(agent="hermes", secret=None, ttl=3600):
    secret = secret or os.environ.get("LUMEN_PROXY_SECRET", "lumen-proxy-dev")
    exp = int(time.time()) + ttl
    sig = hmac.new(secret.encode(), f"{agent}:{exp}".encode(), hashlib.sha256).hexdigest()
    return f"{agent}:{exp}:{sig}"

def parse_lumen(body: bytes) -> dict:
    result = parse_frame(body, 0)
    if not isinstance(result, ParseComplete):
        raise ValueError(f"Invalid LUMEN frame: {result.kind}")
    f = result.frame
    payload = decompress_value(f.payload) if (f.flags & FLAG_COMPRESSED) else f.payload
    if isinstance(payload, bytes):
        payload = json.loads(payload)
    return payload  # dict

def encode_lumen(data: dict) -> bytes:
    payload = compress_value(data)
    frame = bytearray(build_size(len(payload)))
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, frame, 0)
    return bytes(frame)

def forward_json(url: str, msg: dict) -> dict:
    """Forward as JSON to the target worker (non-streaming)."""
    req = urllib.request.Request(url, data=json.dumps(msg).encode(), method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("User-Agent", "LUMEN-Proxy/1.0")
    resp = urllib.request.urlopen(req, timeout=30)
    return json.loads(resp.read())

def forward_stream(url: str, msg: dict, handler: BaseHTTPRequestHandler):
    """Forward as JSON, read SSE stream, write chunks in real time."""
    import http.client
    parsed = urllib.parse.urlparse(url)
    body = json.dumps(msg).encode()
    
    conn = http.client.HTTPSConnection(parsed.netloc, timeout=30)
    conn.request("POST", parsed.path, body, {
        "Content-Type": "application/json",
        "User-Agent": "LUMEN-Proxy/1.0",
    })
    resp = conn.getresponse()
    
    # Stream chunks as they arrive
    handler.send_response(resp.status)
    handler.send_header("Content-Type", "text/event-stream")
    handler.send_header("Cache-Control", "no-cache")
    handler.send_header("Connection", "keep-alive")
    handler.end_headers()
    
    while True:
        chunk = resp.read(4096)
        if not chunk:
            break
        handler.wfile.write(chunk)
        handler.wfile.flush()
    
    conn.close()

# ── HTTP Handler ──
class LumenProxyHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        path = self.path.strip("/")
        parts = path.split("/")
        
        # /v1/chat/{agent} or /v1/{agent}/chat
        agent = None
        if len(parts) >= 2 and parts[0] == "v1":
            if parts[1] == "chat" and len(parts) >= 3:
                agent = parts[2]
            elif len(parts) >= 2:
                agent = parts[1]
        elif len(parts) >= 1:
            agent = parts[0]
        
        ct = self.headers.get("Content-Type", "")
        
        # Read body
        body_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(body_len)
        
        try:
            if "application/lumen" in ct:
                # ── LUMEN path ──
                data = parse_lumen(body)
                target = data.pop("target", agent) or agent
                target_url = AGENT_URLS.get(target)
                if not target_url:
                    raise ValueError(f"Unknown agent: {target}")
                
                # Strip LUMEN-specific fields before forwarding
                macaroon = data.pop("macaroon", None)
                is_stream = data.pop("stream", False) or self.headers.get("X-Stream") == "true"
                
                if is_stream:
                    # Streaming path — forward and stream SSE back
                    forward_stream(target_url, data, self)
                    return  # response already sent by forward_stream
                else:
                    # Normal path — forward as JSON
                    result = forward_json(target_url, data)
                
                # Encode response as LUMEN
                response = encode_lumen({"ok": True, "proxy": target, "response": result})
                self.send_response(200)
                self.send_header("Content-Type", "application/lumen")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
                
            elif "application/json" in ct:
                # ── JSON passthrough ──
                data = json.loads(body)
                target = data.pop("target", agent) or agent
                target_url = AGENT_URLS.get(target)
                if not target_url:
                    raise ValueError(f"Unknown agent: {target}")
                
                is_stream = data.pop("stream", False) or self.headers.get("X-Stream") == "true"
                if is_stream:
                    forward_stream(target_url, data, self)
                    return
                
                result = forward_json(target_url, data)
                response = json.dumps({"ok": True, "proxy": target, "response": result}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            else:
                raise ValueError(f"Unsupported Content-Type: {ct}")
                
        except Exception as e:
            err = {"ok": False, "error": str(e)}
            body = json.dumps(err).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def log_message(self, format, *args):
        sys.stderr.write(f"[lumen-proxy] {args[0]} {args[1]} {args[2]}\n")

# ── Main ──
def main():
    server = HTTPServer((HOST, PORT), LumenProxyHandler)
    print(f"🌐 LUMEN Proxy escuchando en http://{HOST}:{PORT}")
    print(f"   Endpoints: POST /v1/chat/{{agent}} (LUMEN) → traduce a JSON worker")
    print(f"   Agents: {', '.join(AGENT_URLS.keys())}")
    print(f"   Ej: curl -X POST http://localhost:9090/v1/chat/lisa -H 'Content-Type: application/lumen' -d @frame.bin")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n🛑 Proxy cerrado.")
        server.server_close()

if __name__ == "__main__":
    main()
