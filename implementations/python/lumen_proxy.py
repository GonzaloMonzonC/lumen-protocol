#!/usr/bin/env python3
"""
LUMEN → HTTP Proxy — versión canónica consolidada.

Traduce LUMEN binary frames a HTTP/JSON para los workers de Cloudflare que
aún no hablan LUMEN nativo, y devuelve la respuesta como frame LUMEN.

(Consolida los antiguos examples/lumen_proxy.py,
implementations/mcp-servers/proxy/lumen_proxy.py e
implementations/python/proxy.py — un único proxy, ruta de import
repo-relativa, sin rutas absolutas.)

Modos:
  python3 lumen_proxy.py [--port 9090]        # servidor HTTP
  python3 lumen_proxy.py --stdio              # stdio (para Hermes MCP)

Endpoints HTTP:
  POST /v1/chat            body LUMEN (application/lumen) o JSON
  POST /v1/chat/{agent}    idem, con agente en la ruta
  GET  /health             estado + métricas básicas
  GET  /metrics            métricas detalladas

Payload de entrada: {agent, mensaje, session_id, [stream], [mux_channels]}
  - stream=true (o header X-Stream: true) → passthrough SSE en tiempo real
  - mux_channels=[{agent,mensaje,session_id},...] → fan-out multi-agente
"""
import sys, os, json, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler

# LUMEN Python lib: repo-relativo (este fichero vive en implementations/python/)
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from lumen import (
    compress_value, decompress_value,
    build_frame, build_size, parse_frame,
    TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED,
    ParseComplete, FrameAssembler,
)

# ═══════════════════════════════════════════════════════
# Config
# ═══════════════════════════════════════════════════════

# Agent URLs loaded from env var or config
AGENT_URLS = json.loads(os.environ.get("AGENT_URLS", "{}"))

AGENT_ALIASES = {"g": "gon", "z": "zalo"}

# Nombre del parámetro de mensaje/sesión que espera cada worker
AGENT_PARAMS = {
    "zalo":  {"mensaje": "mensaje", "session": "session_id"},
    "lisa":  {"mensaje": "message", "session": "session_id"},
    "angi":  {"mensaje": "mensaje", "session": "session_id"},
    "tom":   {"mensaje": "text",    "session": "session_id"},
    "campo": {"mensaje": "mensaje", "session": "session_id"},
    "gon":   {"mensaje": "mensaje", "session": "session_id"},
}

# API keys opcionales por agente: AGENT_KEYS='{"lisa": "..."}'
AGENT_KEYS = json.loads(os.environ.get("AGENT_KEYS", "{}"))

USER_AGENT = "Hermes-LUMEN-Proxy/3.0"
TIMEOUT = 30  # segundos por llamada a worker

METRICS = {"lumen_requests": 0, "json_requests": 0, "errors": 0,
           "proxied": 0, "agents": {}}
START_TIME = time.time()

# ═══════════════════════════════════════════════════════
# LUMEN ↔ JSON
# ═══════════════════════════════════════════════════════

def parse_lumen(body: bytes) -> dict:
    result = parse_frame(body, 0)
    if not isinstance(result, ParseComplete):
        raise ValueError(f"Invalid LUMEN frame: {result.kind}")
    frame = result.frame
    if frame.frame_type != TYPE_REQUEST:
        raise ValueError(f"Expected TYPE_REQUEST, got {frame.frame_type}")
    payload = frame.payload
    if frame.flags & FLAG_COMPRESSED:
        payload = decompress_value(payload)
    if isinstance(payload, (bytes, bytearray)):
        payload = json.loads(payload)
    if not isinstance(payload, dict):
        raise ValueError(f"Payload not a dict: {type(payload)}")
    return payload


def encode_lumen(data: dict) -> bytes:
    payload = compress_value(data)
    buf = bytearray(build_size(len(payload)))
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
    return bytes(buf)

# ═══════════════════════════════════════════════════════
# Forwarders
# ═══════════════════════════════════════════════════════

def resolve_agent(name: str) -> str:
    name = (name or "").strip().lower()
    return AGENT_ALIASES.get(name, name)


def forward_json(agent: str, mensaje: str, session_id: str = "", **_) -> dict:
    """Reenvía un mensaje a un worker vía JSON HTTP (no streaming)."""
    agent = resolve_agent(agent)
    url = AGENT_URLS.get(agent)
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
    api_key = AGENT_KEYS.get(agent, "")
    if api_key:
        req.add_header("x-api-key", api_key)

    try:
        resp = urllib.request.urlopen(req, timeout=TIMEOUT)
        data = json.loads(resp.read())
        if isinstance(data, dict):
            data["agent"] = agent
            return data
        return {"ok": True, "respuesta": data, "agent": agent}
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:300]
        return {"ok": False, "error": f"HTTP {e.code}: {detail}", "agent": agent}
    except Exception as e:
        return {"ok": False, "error": str(e), "agent": agent}


def forward_stream(agent: str, msg: dict, handler: BaseHTTPRequestHandler):
    """Reenvía y transmite el SSE del worker en tiempo real."""
    import http.client
    agent = resolve_agent(agent)
    url = AGENT_URLS.get(agent)
    if not url:
        raise ValueError(f"unknown agent: {agent}")
    parsed = urllib.parse.urlparse(url)
    params = AGENT_PARAMS.get(agent, {"mensaje": "mensaje", "session": "session_id"})
    body = json.dumps({
        params["mensaje"]: msg.get("mensaje", ""),
        params["session"]: msg.get("session_id", f"proxy_{agent}_{int(time.time())}"),
        "stream": True,
    }).encode()

    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    api_key = AGENT_KEYS.get(agent, "")
    if api_key:
        headers["x-api-key"] = api_key

    conn = http.client.HTTPSConnection(parsed.netloc, timeout=TIMEOUT)
    try:
        conn.request("POST", parsed.path, body, headers)
        resp = conn.getresponse()

        handler.send_response(resp.status)
        handler.send_header("Content-Type", "text/event-stream")
        handler.send_header("Cache-Control", "no-cache")
        handler.end_headers()
        while True:
            chunk = resp.read(4096)
            if not chunk:
                break
            handler.wfile.write(chunk)
            handler.wfile.flush()
    finally:
        conn.close()


def handle_message(msg: dict) -> dict:
    """Procesa un mensaje: single o MUX fan-out."""
    mux = msg.get("mux_channels")
    if mux and isinstance(mux, list):
        results = [forward_json(ch.get("agent", "zalo"), ch.get("mensaje", ""),
                                ch.get("session_id", ""))
                   for ch in mux]
        return {"ok": True, "respuesta": f"MUX: {len(results)} channels",
                "mux_results": results}

    mensaje = msg.get("mensaje", "")
    if not mensaje:
        return {"ok": False, "error": "mensaje required"}
    return forward_json(msg.get("agent", "zalo"), mensaje,
                        msg.get("session_id", ""))

# ═══════════════════════════════════════════════════════
# HTTP server
# ═══════════════════════════════════════════════════════

class LumenProxyHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        if self.path in ("/health", "/metrics"):
            payload = {
                "ok": True,
                "proxy": "lumen-proxy",
                "version": "3.0.0",
                "uptime_s": int(time.time() - START_TIME),
                "agents": list(AGENT_URLS.keys()),
                **(METRICS if self.path == "/metrics" else
                   {"proxied": METRICS["proxied"]}),
            }
            self._send_json(200, payload)
            return
        self._send_json(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        parts = [p for p in self.path.strip("/").split("/") if p]
        # Rutas: /, /chat, /v1/chat, /v1/chat/{agent}
        agent_in_path = None
        if len(parts) == 3 and parts[:2] == ["v1", "chat"]:
            agent_in_path = parts[2]
        elif parts not in ([], ["chat"], ["v1", "chat"]):
            self._send_json(404, {"ok": False, "error": "not found"})
            return

        ct = self.headers.get("Content-Type", "")
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length) if length else b""

        try:
            if "application/lumen" in ct:
                METRICS["lumen_requests"] += 1
                msg = parse_lumen(body)
                lumen_out = True
            elif "application/json" in ct:
                METRICS["json_requests"] += 1
                msg = json.loads(body)
                lumen_out = False
            else:
                self._send_json(415, {
                    "ok": False,
                    "error": "Unsupported Content-Type. Use application/lumen o application/json",
                })
                return

            if agent_in_path and "agent" not in msg:
                msg["agent"] = agent_in_path
            msg.pop("macaroon", None)  # no se reenvía al worker

            agent = resolve_agent(msg.get("agent", "zalo"))
            METRICS["agents"][agent] = METRICS["agents"].get(agent, 0) + 1

            if msg.pop("stream", False) or self.headers.get("X-Stream") == "true":
                forward_stream(agent, msg, self)  # respuesta ya enviada (SSE)
                METRICS["proxied"] += 1
                return

            result = handle_message(msg)
            METRICS["proxied"] += 1

            if lumen_out:
                out = encode_lumen(result)
                self.send_response(200)
                self.send_header("Content-Type", "application/lumen")
                self.send_header("Content-Length", str(len(out)))
                self.send_header("X-Agent", agent)
                self.end_headers()
                self.wfile.write(out)
            else:
                self._send_json(200, result)

        except Exception as e:
            METRICS["errors"] += 1
            self._send_json(400, {"ok": False, "error": str(e)})

    def _send_json(self, status: int, data: dict):
        out = json.dumps(data).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, format, *args):
        sys.stderr.write(f"[lumen-proxy] {args[0]} {args[1]} {args[2]}\n")

# ═══════════════════════════════════════════════════════
# stdio mode (para Hermes MCP)
# ═══════════════════════════════════════════════════════

def run_stdio():
    """Lee frames LUMEN de stdin, reenvía, escribe frames LUMEN a stdout."""
    assembler = FrameAssembler()
    while True:
        chunk = sys.stdin.buffer.read(65536)
        if not chunk:
            break
        for frame in assembler.push(chunk):
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            if isinstance(payload, (bytes, bytearray)):
                payload = json.loads(payload)
            try:
                result = handle_message(payload if isinstance(payload, dict) else {})
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            sys.stdout.buffer.write(encode_lumen(result))
            sys.stdout.buffer.flush()

# ═══════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════

def main():
    import argparse
    p = argparse.ArgumentParser(description="LUMEN → HTTP Proxy (canónico)")
    p.add_argument("--port", type=int, default=9090, help="Puerto HTTP (default 9090)")
    p.add_argument("--host", default="127.0.0.1", help="Bind address (default 127.0.0.1)")
    p.add_argument("--stdio", action="store_true", help="Modo stdio (Hermes MCP)")
    args = p.parse_args()

    if args.stdio:
        run_stdio()
        return

    server = HTTPServer((args.host, args.port), LumenProxyHandler)
    print(f"🌐 LUMEN Proxy v3.0.0 en http://{args.host}:{args.port}")
    print(f"   Agents: {', '.join(AGENT_URLS.keys())}")
    print(f"   POST /v1/chat[/{{agent}}]  (application/lumen | application/json)")
    print(f"   GET  /health, /metrics")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Proxy cerrado.")
        server.server_close()


if __name__ == "__main__":
    main()
