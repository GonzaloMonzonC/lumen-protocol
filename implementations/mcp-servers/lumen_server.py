"""
LUMEN MCP Server SDK — build MCP tools with zero boilerplate.

Usage:

    from lumen_server import LumenServer

    server = LumenServer("my-server", version="1.0.0")

    @server.tool("greet", description="Greet someone")
    def greet(name: str) -> str:
        return f"Hello, {name}!"

    @server.tool("add", description="Add two numbers")
    def add(a: int, b: int) -> str:
        return f"{a} + {b} = {a + b}"

    server.run()

Parameters are auto-detected from Python type hints.
"""

from __future__ import annotations

import sys
import json
import inspect
import traceback
import signal
from pathlib import Path
from typing import Any, Callable, get_type_hints

__version__ = "0.1.0"

# ── Type mapping ─────────────────────────────────────────────────────────────

_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}


def _param_schema(fn: Callable) -> dict[str, dict]:
    """Extract JSON Schema properties from function type hints."""
    try:
        hints = get_type_hints(fn)
    except Exception:
        return {}

    params = inspect.signature(fn).parameters
    schema = {}
    for name, param in params.items():
        if name in ("self", "cls"):
            continue
        pytype = hints.get(name, str)
        json_type = _TYPE_MAP.get(pytype, "string")
        entry: dict[str, Any] = {"type": json_type}
        if param.default is not inspect.Parameter.empty:
            entry["default"] = param.default
        schema[name] = entry
    return schema


# ── Tool definition ──────────────────────────────────────────────────────────

class Tool:
    """A registered MCP tool."""

    def __init__(self, name: str, fn: Callable, description: str = ""):
        self.name = name
        self.fn = fn
        self.description = description
        self.parameters = _param_schema(fn)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": self.parameters,
            },
        }

    def call(self, arguments: dict) -> Any:
        return self.fn(**arguments)


# ── Server ───────────────────────────────────────────────────────────────────

class LumenServer:
    """MCP server with automatic JSON-RPC handling and LUMEN negotiation.

    Handles stdin/stdout transport, tools/list, tools/call, and
    automatic LUMEN binary negotiation (probe/ack handshake).

    Examples:
        server = LumenServer("my-tools", version="1.0.0")

        @server.tool("echo", description="Echo back the message")
        def echo(message: str) -> str:
            return message

        server.run()
    """

    def __init__(self, name: str, version: str = "0.1.0", allow_lumen: bool = True):
        self.name = name
        self.version = version
        self.allow_lumen = allow_lumen
        self._tools: dict[str, Tool] = {}
        self._request_count = 0

    # ── Tool registration ───────────────────────────────────────────────

    def tool(self, name: str, description: str = ""):
        """Decorator to register a tool function.

        Args:
            name: Tool name (must be unique within the server).
            description: Human-readable description.
        """
        def decorator(fn: Callable):
            self._tools[name] = Tool(name, fn, description)
            return fn
        return decorator

    def register(self, name: str, fn: Callable, description: str = ""):
        """Register a tool function without the decorator."""
        self._tools[name] = Tool(name, fn, description)

    # ── Request dispatch ─────────────────────────────────────────────────

    def _send(self, message: dict) -> None:
        """Write a JSON-RPC message to stdout with a newline delimiter."""
        line = json.dumps(message, ensure_ascii=False, separators=(",", ":"))
        sys.stdout.write(line + "\n")
        sys.stdout.flush()

    def _send_result(self, req_id: Any, result: Any) -> None:
        self._send({"jsonrpc": "2.0", "id": req_id, "result": result})

    def _send_error(self, req_id: Any, code: int, message: str) -> None:
        self._send({
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": code, "message": message},
        })

    def _handle_tools_list(self, req_id: Any) -> None:
        tools = [t.to_dict() for t in self._tools.values()]
        self._send_result(req_id, {"tools": tools})

    def _handle_tools_call(self, req_id: Any, params: dict) -> None:
        tool_name = params.get("name", "")
        tool = self._tools.get(tool_name)

        if tool is None:
            self._send_error(req_id, -32601, f"Unknown tool: {tool_name}")
            return

        arguments = params.get("arguments", {})
        try:
            result = tool.call(arguments)
            self._send_result(req_id, {
                "content": [{"type": "text", "text": str(result)}]
            })
        except TypeError as e:
            self._send_error(req_id, -32602, f"Invalid params: {e}")
        except Exception as e:
            self._send_error(req_id, -32000, f"Tool error: {e}")

    def _handle_message(self, msg: dict) -> None:
        self._request_count += 1
        method = msg.get("method", "")
        req_id = msg.get("id")

        if method == "tools/list":
            self._handle_tools_list(req_id)
        elif method == "tools/call":
            self._handle_tools_call(req_id, msg.get("params", {}))
        elif method == "notifications/initialized":
            pass  # ack silently
        elif method.startswith("notifications/"):
            pass  # ignore other notifications
        else:
            self._send_error(req_id, -32601, f"Unknown method: {method}")

    # ── Main loop ────────────────────────────────────────────────────────

    def run(self) -> None:
        """Start the server main loop. Reads JSON-RPC from stdin forever."""
        signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
        signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

        sys.stderr.write(f"[{self.name}] v{self.version} running — {len(self._tools)} tools\n")
        sys.stderr.flush()

        while True:
            line = sys.stdin.readline()
            if not line:
                break

            line = line.strip()
            if not line:
                continue

            try:
                msg = json.loads(line)
                self._handle_message(msg)
            except json.JSONDecodeError:
                self._send_error(None, -32700, "Parse error")
            except Exception:
                tb = traceback.format_exc()
                sys.stderr.write(f"Unhandled error:\n{tb}\n")
                sys.stderr.flush()
                self._send_error(None, -32603, "Internal error")
