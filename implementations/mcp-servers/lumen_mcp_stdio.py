"""lumen_mcp_stdio.py — framing MCP para los servers lumen (auto-detección).

Historia y por qué existe:
- Los servers lumen usaban sys.stdin.readline() (newline-delimited), que en
  Windows con pipes BLOQUEA hasta acumular ~8 KB (read() del MSVCRT): los
  mensajes pequeños (pings/keepalives de Hermes) nunca se leían → timeout →
  reconnect loop (bug endémico).
- Solución de lectura: ReadFile nativo (ctypes), que devuelve lo disponible
  sin el bloqueo de 8KB. ESO sí era correcto y se conserva.
- ERROR histórico corregido (2026-08-26): se asumió que el cliente oficial
  MCP hablaba framing Content-Length estilo LSP. FALSO — verificado contra
  site-packages/mcp/client/stdio/__init__.py: escribe `(json + "\\n").encode()`
  y lee con `buffer.split("\\n")`. Es decir: JSON delimitado por newlines.
  Con framing CL el handshake nunca cuadraba → CancelledError ~32s.
- Comportamiento final:
  * Lectura: auto-detección — acepta JSON por newlines (estándar SDK) Y
    framing Content-Length (compatibilidad con clientes legacy/tests).
  * Escritura: JSON por newlines (lo que el SDK sabe parsear).

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

# Buffer persistente entre llamadas: un chunk puede traer varios mensajes
# (p.ej. initialize + notification seguidos) o un mensaje incompleto.
_buffer = bytearray()

_NEED_MORE = object()


def _read_available(max_bytes: int = 4096) -> bytes:
    """ReadFile nativo: devuelve lo disponible (sin bloqueo de 8 KB)."""
    buf = ctypes.create_string_buffer(max_bytes)
    n = ctypes.c_ulong(0)
    ok = _k32.ReadFile(_STDIN_H, buf, max_bytes, ctypes.byref(n), None)
    if not ok or n.value == 0:
        raise EOFError("stdin cerrado")
    return buf.raw[:n.value]


def _try_consume():
    """Intenta extraer UN mensaje del buffer. _NEED_MORE si falta data."""
    global _buffer
    # Descarta blancos iniciales (tolera \n entre mensajes)
    i = 0
    while i < len(_buffer) and _buffer[i] in b" \r\n\t":
        i += 1
    del _buffer[:i]
    if not _buffer:
        return _NEED_MORE

    # Modo 1: JSON delimitado por newline (estándar del SDK MCP)
    if _buffer[0:1] == b"{":
        nl = _buffer.find(b"\n")
        if nl == -1:
            return _NEED_MORE
        line = bytes(_buffer[:nl])
        del _buffer[: nl + 1]
        return json.loads(line)

    # Modo 2: framing Content-Length estilo LSP (legacy)
    marker = b"content-length:"
    if bytes(_buffer[: len(marker)]).lower() == marker:
        end = bytes(_buffer).find(b"\r\n\r\n")
        if end == -1:
            return _NEED_MORE
        header = bytes(_buffer[:end])
        length = 0
        for hline in header.split(b"\r\n"):
            if hline.lower().startswith(marker):
                length = int(hline.split(b":", 1)[1].strip())
        body_start = end + 4
        if len(_buffer) - body_start < length:
            return _NEED_MORE
        body = bytes(_buffer[body_start : body_start + length])
        del _buffer[: body_start + length]
        return json.loads(body)

    raise ValueError("framing MCP desconocido")


def read_message(timeout: float = None) -> dict:
    """Lee un mensaje MCP con auto-detección de framing. None en EOF."""
    import time as _t
    deadline = _t.time() + timeout if timeout else None
    while True:
        msg = _try_consume()
        if msg is not _NEED_MORE:
            return msg
        if deadline and _t.time() > deadline:
            raise TimeoutError("timeout leyendo mensaje MCP")
        try:
            _buffer.extend(_read_available(4096))
        except EOFError:
            # EOF con buffer residual no parseable
            return None


def write_message(msg: dict) -> None:
    """Envía un mensaje MCP como JSON + newline (formato que parsea el SDK)."""
    data = json.dumps(msg, ensure_ascii=False).encode("utf-8")
    sys.stdout.buffer.write(data + b"\n")
    sys.stdout.buffer.flush()
