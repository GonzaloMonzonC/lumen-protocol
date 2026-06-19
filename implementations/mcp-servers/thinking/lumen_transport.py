"""
LUMEN Transport — WebSocket + wire format for dashboards, agents, and web apps.

Extends the LUMEN binary protocol (magic LUM\\x01 + u32 length + zlib payload)
beyond MCP — making LUMEN a universal protocol for all Cadences Lab tooling.

Usage:
    from lumen_transport import LumenWS, encode_frame, decode_frame

    # Server side (Python)
    ws = LumenWS(port=9877)
    ws.broadcast_metrics(build_metrics())  # push to all connected dashboards

    # Client side (browser)
    new LumenClient('ws://localhost:9877', (data) => render(data))
"""

from __future__ import annotations
import struct, zlib, json, time, threading, hashlib, base64
import socketserver, http.server as _http
from typing import Callable

LUMEN_MAGIC = b"LUM\x01"

def encode_frame(payload: bytes, compress: bool = True) -> bytes:
    """LUMEN wire format: magic(4) + flags(1) + length(4) + payload.
    flags: bit0 = compressed (zlib)."""
    flags = 0x01 if compress else 0x00
    if compress:
        payload = zlib.compress(payload, 6)
    return LUMEN_MAGIC + bytes([flags]) + struct.pack("<I", len(payload)) + payload

def decode_frame(data: bytes) -> bytes:
    """Decode LUMEN wire format, decompress if needed."""
    if data[:4] != LUMEN_MAGIC:
        return data  # passthrough for legacy JSON
    flags = data[4]
    length = struct.unpack("<I", data[5:9])[0]
    payload = data[9:9 + length]
    if flags & 0x01:
        payload = zlib.decompress(payload)
    return payload

# ═══ WebSocket Server ═══

class _WSConnection:
    """Single WebSocket connection."""
    def __init__(self, sock):
        self.sock = sock
        self.alive = True

    def send_frame(self, payload: bytes):
        """Send binary WebSocket frame."""
        if not self.alive:
            return
        try:
            length = len(payload)
            header = bytearray()
            header.append(0x82)  # FIN + binary opcode
            if length < 126:
                header.append(length)
            elif length < 65536:
                header.append(126)
                header.extend(length.to_bytes(2, "big"))
            else:
                header.append(127)
                header.extend(length.to_bytes(8, "big"))
            self.sock.sendall(bytes(header) + payload)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.alive = False

    def recv_frame(self) -> bytes | None:
        """Receive WebSocket frame (text or binary)."""
        try:
            b1 = self.sock.recv(1)
            if not b1:
                self.alive = False
                return None
            opcode = b1[0] & 0x0F
            b2 = self.sock.recv(1)[0]
            masked = b2 & 0x80
            plen = b2 & 0x7F
            if plen == 126:
                plen = int.from_bytes(self.sock.recv(2), "big")
            elif plen == 127:
                plen = int.from_bytes(self.sock.recv(8), "big")
            mask_key = self.sock.recv(4) if masked else None
            payload = bytearray(self.sock.recv(plen))
            if masked:
                for i in range(len(payload)):
                    payload[i] ^= mask_key[i % 4]
            if opcode == 0x08:  # close
                self.alive = False
                return None
            if opcode == 0x09:  # ping → pong
                pong = bytearray([0x8A, 0x00])
                self.sock.sendall(bytes(pong))
                return None
            return bytes(payload)
        except (BrokenPipeError, ConnectionResetError, OSError, TimeoutError):
            self.alive = False
            return None


class LumenWS:
    """
    WebSocket server that pushes LUMEN-framed data to connected clients.

    Clients = dashboards, monitoring tools, other agents.
    """
    def __init__(self, host: str = "127.0.0.1", port: int = 9877):
        self.host = host
        self.port = port
        self._clients: list[_WSConnection] = []
        self._lock = threading.Lock()
        self._server: socketserver.TCPServer | None = None
        self._thread: threading.Thread | None = None

    def start(self):
        """Start WebSocket server in a daemon thread."""
        class _Handler(socketserver.BaseRequestHandler):
            def handle(inner_self):
                ws = _WSConnection(inner_self.request)
                # Read HTTP upgrade request
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = inner_self.request.recv(4096)
                    if not chunk:
                        return
                    data += chunk
                    if len(data) > 8192:
                        return
                request_text = data.decode("utf-8", errors="replace")
                key = None
                for line in request_text.split("\r\n"):
                    if line.lower().startswith("sec-websocket-key:"):
                        key = line.split(":", 1)[1].strip()
                        break
                if not key:
                    inner_self.request.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")
                    return
                accept = base64.b64encode(
                    hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()
                ).decode()
                response = (
                    "HTTP/1.1 101 Switching Protocols\r\n"
                    "Upgrade: websocket\r\n"
                    "Connection: Upgrade\r\n"
                    f"Sec-WebSocket-Accept: {accept}\r\n\r\n"
                )
                inner_self.request.sendall(response.encode())
                # Handshake complete — add client
                with self._lock:
                    self._clients.append(ws)
                try:
                    while ws.alive:
                        msg = ws.recv_frame()
                        if msg is None and not ws.alive:
                            break
                finally:
                    with self._lock:
                        if ws in self._clients:
                            self._clients.remove(ws)
                    ws.alive = False

        self._server = socketserver.ThreadingTCPServer(
            (self.host, self.port), _Handler, bind_and_activate=True
        )
        self._server.allow_reuse_address = True
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def broadcast(self, data: dict | bytes | str):
        """Push data to all connected clients, LUMEN-framed."""
        if isinstance(data, dict):
            payload = json.dumps(data, default=str).encode("utf-8")
        elif isinstance(data, str):
            payload = data.encode("utf-8")
        else:
            payload = data
        frame = encode_frame(payload)
        with self._lock:
            dead = []
            for ws in self._clients:
                ws.send_frame(frame)
                if not ws.alive:
                    dead.append(ws)
            for ws in dead:
                self._clients.remove(ws)

    def stop(self):
        """Shutdown WebSocket server."""
        if self._server:
            self._server.shutdown()
        with self._lock:
            for ws in self._clients:
                ws.alive = False
            self._clients.clear()
