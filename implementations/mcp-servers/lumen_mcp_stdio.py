"""lumen_mcp_stdio.py — framing MCP estándar (Content-Length) para los servers lumen.

Por qué existe:
- Los servers lumen usaban sys.stdin.readline() (newline-delimited), que en
  Windows con pipes BLOQUEA hasta acumular ~8 KB (read() del MSVCRT): los
  mensajes pequeños (pings/keepalives de Hermes) nunca se leían → timeout →
  reconnect loop (bug endémico).
- El cliente de Hermes usa el SDK MCP oficial (anyio + ReadFile OVERLAPPED),
  que SÍ devuelve lo disponible → habla Content-Length estándar.
- Solución: leer con ReadFile nativo (ctypes) + framing Content-Length.

Uso:
    from lumen_mcp_stdio import read_message, write_message
    msg = read_message()
    write_message({"jsonrpc": "2.0", "id": 1, "result": {...}})
"""
import ctypes
import json
import msvcrt
import sys

_k32 = ctypes.windll.kernel32
_STDIN_H = msvcrt.get_osfhandle(0)

def _read_available(max_bytes: int = 4096) -> bytes:
    """ReadFile nativo: devuelve lo disponible (sin bloqueo de 8 KB)."""
    buf = ctypes.create_string_buffer(max_bytes)
    n = ctypes.c_ulong(0)
    ok = _k32.ReadFile(_STDIN_H, buf, max_bytes, ctypes.byref(n), None)
    if not ok or n.value == 0:
        raise EOFError("stdin cerrado")
    return buf.raw[:n.value]

def read_message(timeout: float = None) -> dict:
    """Lee un mensaje MCP con framing Content-Length. None en EOF."""
    import time as _t
    deadline = _t.time() + timeout if timeout else None
    header = b""
    while b"\r\n\r\n" not in header:
        if deadline and _t.time() > deadline:
            raise TimeoutError("timeout leyendo cabeceras MCP")
        try:
            header += _read_available(4096)
        except EOFError:
            if not header:
                return None
            raise
        if len(header) > 65536:
            raise ValueError("cabeceras MCP demasiado largas")
    head, rest = header.split(b"\r\n\r\n", 1)
    length = 0
    for line in head.split(b"\r\n"):
        if line.lower().startswith(b"content-length:"):
            length = int(line.split(b":", 1)[1].strip())
    body = rest
    while len(body) < length:
        try:
            body += _read_available(4096)
        except EOFError:
            return None
    return json.loads(body[:length].decode("utf-8"))

def write_message(msg: dict) -> None:
    """Envía un mensaje MCP con framing Content-Length."""
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    out = f"Content-Length: {len(data)}\r\n\r\n".encode("ascii") + data
    sys.stdout.buffer.write(out)
    sys.stdout.buffer.flush()
