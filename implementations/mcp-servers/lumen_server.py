"""
LUMEN MCP Server SDK v0.2.0 — build MCP tools with zero boilerplate.

Dual-transport: auto-detects LUMEN binary protocol, falls back to JSON-RPC.
One decorator, one `server.run()`, and you're done.

Usage:
    from lumen_server import LumenServer

    server = LumenServer("my-server", version="1.0.0")

    @server.tool("greet", description="Greet someone")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    server.run()   # ← handles LUMEN negotiation, JSON-RPC, errors, signals
"""

from __future__ import annotations

import sys
import json
import struct
import inspect
import traceback
import signal
from typing import Any, Callable, get_type_hints

__version__ = "0.2.0"

# ── Type mapping ─────────────────────────────────────────────────────────────

_TYPE_MAP: dict[type, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _python_to_json_type(pytype: type) -> str:
    """Map a Python type to JSON Schema type string."""
    origin = getattr(pytype, "__origin__", None)
    if origin is list:
        return "array"
    if origin is dict:
        return "object"
    return _TYPE_MAP.get(pytype, "string")


def _param_schema(fn: Callable) -> dict[str, dict]:
    """Extract JSON Schema properties from function type hints."""
    try:
        hints = get_type_hints(fn)
    except Exception:
        return {}

    params = inspect.signature(fn).parameters
    schema: dict[str, dict] = {}
    required: list[str] = []

    for name, param in params.items():
        if name in ("self", "cls"):
            continue
        pytype = hints.get(name, str)
        json_type = _python_to_json_type(pytype)
        entry: dict[str, Any] = {"type": json_type, "description": f"Parameter: {name}"}
        if param.default is not inspect.Parameter.empty:
            entry["default"] = param.default
        else:
            required.append(name)
        schema[name] = entry

    return schema


# ── Tool definition ──────────────────────────────────────────────────────────

class Tool:
    """A registered MCP tool with schema extracted from type hints."""

    def __init__(
        self,
        name: str,
        fn: Callable,
        description: str = "",
        input_schema: dict | None = None,
    ):
        self.name = name
        self.fn = fn
        self.description = description
        if input_schema:
            self.schema = input_schema
        else:
            props = _param_schema(fn)
            required = [k for k, v in props.items() if "default" not in v]
            self.schema = {"type": "object", "properties": props}
            if required:
                self.schema["required"] = required

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": self.schema,
        }

    def validate(self, arguments: dict) -> tuple[dict, str | None]:
        """Validate arguments against the schema.

        Returns (cleaned_args, error_message_or_None).
        """
        props = self.schema.get("properties", {})
        required = self.schema.get("required", [])
        cleaned: dict[str, Any] = {}

        # Check required params
        for key in required:
            if key not in arguments:
                return {}, f"Missing required parameter '{key}' for tool '{self.name}'"

        # Validate each provided param
        for key, value in arguments.items():
            if key not in props:
                return {}, f"Unknown parameter '{key}' for tool '{self.name}'"
            expected = props[key].get("type", "string")
            if not _check_type(value, expected):
                return {}, (
                    f"Invalid type for '{key}': expected {expected}, "
                    f"got {type(value).__name__}"
                )
            cleaned[key] = value

        # Fill defaults for missing optional params
        for key, prop in props.items():
            if key not in cleaned and "default" in prop:
                cleaned[key] = prop["default"]

        return cleaned, None

    def call(self, arguments: dict) -> Any:
        """Call the tool function with validated arguments."""
        return self.fn(**arguments)


def _check_type(value: Any, expected: str) -> bool:
    """Check if a value matches a JSON Schema type."""
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "array":
        return isinstance(value, list)
    if expected == "object":
        return isinstance(value, dict)
    return True


# ── LUMEN binary transport ───────────────────────────────────────────────────

# Frame constants (must match protocol spec)
_FRAME_PROBE = 0x0F
_FRAME_PROBE_ACK = 0x10
_FRAME_REQUEST = 0x01
_FRAME_RESPONSE = 0x02
_FLAG_COMPRESSED = 0x01

# Hyb128: up to 63 fits in 1 byte
def _hyb128_encode(value: int) -> bytes:
    """Encode a u32 as Hyb128 variable-length integer."""
    if value <= 63:
        return bytes([value])
    if value <= 16383:
        return bytes([0x80 | (value & 0x3F), (value >> 6) & 0xFF])
    if value <= 0xFFFFFFFF:
        return bytes(
            [
                0xC0 | (value & 0x0F),
                (value >> 4) & 0xFF,
                (value >> 12) & 0xFF,
                (value >> 20) & 0xFF,
                (value >> 28) & 0xFF,
            ]
        )
    # LEB128 fallback for values > 4GB (shouldn't happen for MCP frames)
    result = bytearray()
    while value > 0x7F:
        result.append(0x80 | (value & 0x7F))
        value >>= 7
    result.append(value & 0x7F)
    return bytes([0xE0 | (len(result) - 1)]) + bytes(result)


def _build_lumen_frame(frame_type: int, flags: int, payload: bytes) -> bytes:
    """Build a complete LUMEN frame: Hyb128 length + type + flags + payload."""
    total_len = 2 + len(payload)  # type byte + flags byte + payload
    return _hyb128_encode(total_len) + bytes([frame_type, flags]) + payload


def _build_probe_response() -> bytes:
    """Build a LUMEN PROBE_ACK frame."""
    caps = json.dumps({"v": 1, "caps": ["compression"]}, separators=(",", ":"))
    return _build_lumen_frame(_FRAME_PROBE_ACK, 0, caps.encode())


def _build_lumen_response(req_id: Any, result: Any) -> bytes:
    """Build a LUMEN RESPONSE frame with actual LUMEN-compressed payload."""
    from lumen.compress import compress_value
    response = {"jsonrpc": "2.0", "id": req_id, "result": result}
    payload = compress_value(response)
    return _build_lumen_frame(_FRAME_RESPONSE, _FLAG_COMPRESSED, payload)


def _detect_lumen_probe(line: bytes) -> bool:
    """Check if an incoming line looks like a LUMEN binary probe frame."""
    if len(line) < 3:
        return False
    # LUMEN probe frame: Hyb128(len) + TYPE(0x0F) + FLAGS + JSON payload
    # Hyb128 first byte: mode bits tell us the length encoding
    first_byte = line[0]
    # Short mode (0x00-0x3F): first byte IS the length
    if first_byte <= 0x3F:
        hlen = 1
    # Medium mode (0x80-0xBF): 2 bytes
    elif 0x80 <= first_byte <= 0xBF:
        hlen = 2
    # Long mode (0xC0-0xDF): 5 bytes
    elif 0xC0 <= first_byte <= 0xDF:
        hlen = 5
    else:
        return False

    if len(line) < hlen + 2:
        return False
    frame_type = line[hlen]
    return frame_type == _FRAME_PROBE


# ── Server ───────────────────────────────────────────────────────────────────


class LumenServer:
    """MCP server with automatic LUMEN binary negotiation.

    Features:
    - Auto-detect LUMEN probe → negotiate binary transport
    - Fall back to JSON-RPC if client doesn't speak LUMEN
    - Type hints → JSON Schema auto-generation
    - Parameter validation with clear error messages
    - initialize / tools/list / tools/call / notifications handling
    - SIGINT/SIGTERM graceful shutdown

    Examples:
        server = LumenServer("my-tools", version="1.0.0")

        @server.tool("echo", description="Echo back the message")
        def echo(message: str) -> str:
            return message

        server.run()
    """

    def __init__(
        self,
        name: str,
        version: str = "0.1.0",
        allow_lumen: bool = True,
        allow_jsonrpc: bool = True,
    ):
        self.name = name
        self.version = version
        self.allow_lumen = allow_lumen
        self.allow_jsonrpc = allow_jsonrpc
        self._tools: dict[str, Tool] = {}
        self._request_count = 0
        self._lumen_active = False

    # ── Tool registration ───────────────────────────────────────────────

    def tool(
        self,
        name: str,
        description: str = "",
        input_schema: dict | None = None,
    ):
        """Decorator to register a tool function.

        Args:
            name: Tool name (must be unique within the server).
            description: Human-readable description.
            input_schema: Manual JSON Schema (overrides auto-detection from type hints).
        """

        def decorator(fn: Callable):
            self._tools[name] = Tool(name, fn, description, input_schema)
            return fn

        return decorator

    def register(
        self,
        name: str,
        fn: Callable,
        description: str = "",
        input_schema: dict | None = None,
    ):
        """Register a tool function without the decorator."""
        self._tools[name] = Tool(name, fn, description, input_schema)

    # ── Transport ────────────────────────────────────────────────────────

    def _write(self, data: bytes) -> None:
        """Write raw bytes to stdout. Override for custom transports."""
        sys.stdout.buffer.write(data)
        sys.stdout.buffer.flush()

    def _send_jsonrpc(self, message: dict) -> None:
        """Send a JSON-RPC message (newline-delimited)."""
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        self._write((line + "\n").encode())

    def _send_lumen(self, req_id: Any, result: Any) -> None:
        """Send a LUMEN binary response frame."""
        try:
            frame = _build_lumen_response(req_id, result)
            self._write(frame)
        except Exception:
            # Fallback to JSON-RPC on encoding error
            self._send_jsonrpc(
                {"jsonrpc": "2.0", "id": req_id, "result": result}
            )

    def _send_result(self, req_id: Any, result: Any) -> None:
        if self._lumen_active:
            self._send_lumen(req_id, result)
        else:
            self._send_jsonrpc(
                {"jsonrpc": "2.0", "id": req_id, "result": result}
            )

    def _send_error(
        self, req_id: Any, code: int, message: str, data: Any = None
    ) -> None:
        err: dict[str, Any] = {"code": code, "message": message}
        if data:
            err["data"] = data
        self._send_jsonrpc({"jsonrpc": "2.0", "id": req_id, "error": err})

    # ── Request dispatch ─────────────────────────────────────────────────

    def _handle_initialize(self, req_id: Any) -> None:
        self._send_result(req_id, {
            "protocolVersion": "2025-03-26",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": self.name, "version": self.version},
        })

    def _handle_tools_list(self, req_id: Any) -> None:
        tools = [t.to_dict() for t in self._tools.values()]
        self._send_result(req_id, {"tools": tools})

    def _handle_tools_call(self, req_id: Any, params: dict) -> None:
        tool_name = params.get("name", "")
        tool = self._tools.get(tool_name)

        if tool is None:
            self._send_error(
                req_id, -32601,
                f"Unknown tool: '{tool_name}'. "
                f"Available: {', '.join(self._tools.keys())}"
            )
            return

        arguments = params.get("arguments", {})
        validated, err = tool.validate(arguments)
        if err:
            self._send_error(req_id, -32602, f"Invalid params: {err}")
            return

        try:
            result = tool.call(validated)
            self._send_result(req_id, {
                "content": [{"type": "text", "text": str(result)}]
            })
        except TypeError as e:
            self._send_error(req_id, -32602, f"Invalid params: {e}")
        except ValueError as e:
            self._send_error(req_id, -32602, f"Invalid params: {e}")
        except Exception as e:
            self._send_error(
                req_id, -32000,
                f"Tool '{tool_name}' failed: {e}",
                _trace_for_debug(),
            )

    def _dispatch(self, msg: dict) -> None:
        self._request_count += 1
        method = msg.get("method", "")
        req_id = msg.get("id")

        handlers = {
            "initialize": lambda: self._handle_initialize(req_id),
            "tools/list": lambda: self._handle_tools_list(req_id),
            "tools/call": lambda: self._handle_tools_call(req_id, msg.get("params", {})),
        }

        handler = handlers.get(method)
        if handler:
            handler()
        elif method.startswith("notifications/"):
            pass  # ack silently
        else:
            self._send_error(req_id, -32601, f"Unknown method: '{method}'")

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the server main loop. Reads from stdin, auto-negotiates LUMEN."""
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

        sys.stderr.write(
            f"[{self.name}] v{self.version} — {len(self._tools)} tools, "
            f"LUMEN={'on' if self.allow_lumen else 'off'}\n"
        )
        sys.stderr.flush()

        buf = bytearray()
        while True:
            try:
                chunk = sys.stdin.buffer.read1(65536)
            except Exception:
                break
            if not chunk:
                break

            buf.extend(chunk)

            # Process all complete lines from buffer
            while True:
                nl = buf.find(b"\n")
                if nl == -1:
                    break
                line = bytes(buf[:nl])
                del buf[: nl + 1]

                if not line:
                    continue

                # Detect LUMEN binary probe
                if self.allow_lumen and not self._lumen_active and _detect_lumen_probe(line):
                    sys.stderr.write(f"[{self.name}] LUMEN probe detected → activating binary transport\n")
                    sys.stderr.flush()
                    self._write(_build_probe_response())
                    self._lumen_active = True
                    continue

                # Try JSON decode
                try:
                    msg = json.loads(line)
                    self._dispatch(msg)
                except json.JSONDecodeError:
                    if not self._lumen_active:
                        self._send_error(None, -32700, "Parse error")
                except Exception:
                    tb = traceback.format_exc()
                    sys.stderr.write(f"[{self.name}] Unhandled error:\n{tb}\n")
                    sys.stderr.flush()
                    self._send_error(
                        None, -32603,
                        "Internal error",
                        _trace_for_debug(),
                    )


def _trace_for_debug() -> str | None:
    """Return traceback string if stderr is a TTY (debug mode)."""
    if sys.stderr.isatty():
        return traceback.format_exc()
    return None
