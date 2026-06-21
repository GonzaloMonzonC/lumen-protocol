"""
PDBM-Lumen Plugin for Hermes Agent.

Registers 10 PDBM-Lumen tools (pdb_set/get/order/data/kill/incr/merge/query/
schema/backup) via persistent subprocess connection to the PDB server.

Usage:
  Place this directory in ~/.hermes/plugins/ and add to config.yaml:
    plugins:
      lumen-pdb-bridge:
        enabled: true

  Then /reset.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# Persistent connection to PDBM-Lumen server
# ═══════════════════════════════════════════════════════════════════════════

_server: subprocess.Popen[str] | None = None
_server_lock = threading.Lock()
_request_id = 0
_request_id_lock = threading.Lock()

# Paths
_HERMES_VENV_PYTHON = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
    "hermes", "hermes-agent", "venv", "Scripts", "python.exe",
)

# Try multiple candidates for the server path
def _find_server() -> str:
    candidates = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))),
            "Documents", "GitHub", "lumen-protocol",
            "implementations", "mcp-servers", "pdb", "server.py",
        ),
        os.path.join(
            os.path.expanduser("~"),
            "Documents", "GitHub", "lumen-protocol",
            "implementations", "mcp-servers", "pdb", "server.py",
        ),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    raise FileNotFoundError(
        "Cannot find PDBM-Lumen server. Expected at: "
        "~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/server.py"
    )


def _get_server() -> subprocess.Popen[str]:
    global _server
    with _server_lock:
        if _server is None or _server.poll() is not None:
            server_path = _find_server()
            _server = subprocess.Popen(
                [_HERMES_VENV_PYTHON, "-u", server_path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1,
            )
            # Initialize MCP handshake
            _rpc({"method": "initialize", "params": {}})
    return _server


def _rpc(msg: dict) -> dict:
    """Send JSON-RPC message to PDB server, return response."""
    server = _get_server()
    with _request_id_lock:
        global _request_id
        _request_id += 1
        msg_id = msg.get("id", _request_id)
        _request_id = msg_id

    payload = json.dumps(
        {"jsonrpc": "2.0", "id": msg_id, **msg}, ensure_ascii=False
    )

    with _server_lock:
        server.stdin.write(payload + "\n")
        server.stdin.flush()
        line = server.stdout.readline()

    if not line:
        raise ConnectionError("PDB server closed connection")

    resp = json.loads(line.strip())
    if "error" in resp:
        raise RuntimeError(f"PDB error: {resp['error']}")
    return resp.get("result", {})


def _call_tool(name: str, args: dict) -> dict:
    """Call a PDBM-Lumen tool and return its result."""
    result = _rpc({"method": "tools/call", "params": {"name": name, "arguments": args}})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════════════════════

def _handle_pdb_set(args: dict) -> dict:
    return _call_tool("pdb_set", args)

def _handle_pdb_get(args: dict) -> dict:
    return _call_tool("pdb_get", args)

def _handle_pdb_order(args: dict) -> dict:
    return _call_tool("pdb_order", args)

def _handle_pdb_data(args: dict) -> dict:
    return _call_tool("pdb_data", args)

def _handle_pdb_kill(args: dict) -> dict:
    return _call_tool("pdb_kill", args)

def _handle_pdb_incr(args: dict) -> dict:
    return _call_tool("pdb_incr", args)

def _handle_pdb_merge(args: dict) -> dict:
    return _call_tool("pdb_merge", args)

def _handle_pdb_query(args: dict) -> dict:
    return _call_tool("pdb_query", args)

def _handle_pdb_schema(args: dict) -> dict:
    return _call_tool("pdb_schema", args)

def _handle_pdb_backup(args: dict) -> dict:
    return _call_tool("pdb_backup", args)


# ═══════════════════════════════════════════════════════════════════════════
# Tool schemas
# ═══════════════════════════════════════════════════════════════════════════

def _pdb_schema(name: str, desc: str, properties: dict, required: list = None) -> dict:
    return {
        "name": name,
        "description": desc,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required or [],
        },
    }

_TOOL_SCHEMAS = [
    _pdb_schema(
        "pdb_set",
        "SET a value at a hierarchical path. Creates node if missing. "
        "Analogous to MUMPS SET ^global(subs)=value. Value can be string, number, boolean, array, object, or null.",
        {
            "ns": {"type": "string", "description": "Namespace (global name)"},
            "subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
                "description": "Subscript path, e.g. [42, 'name'] for ^GLOBAL(42,'name')",
            },
            "value": {"description": "Value to store. JSON-serializable."},
        },
        required=["ns", "subs", "value"],
    ),
    _pdb_schema(
        "pdb_get",
        "GET value at a hierarchical path. Returns null if not found. "
        "Analogous to MUMPS $GET(^global(subs), default).",
        {
            "ns": {"type": "string"},
            "subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
            },
            "default": {"description": "Default value if key not found"},
        },
        required=["ns", "subs"],
    ),
    _pdb_schema(
        "pdb_order",
        "Find the next/previous subscript at the current level. Pass '' as "
        "the LAST subscript to get first/last. Returns null when none left. "
        "Analogous to MUMPS $ORDER(^global(subs), direction).",
        {
            "ns": {"type": "string"},
            "subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
                "description": "Last element is current position; '' means before first.",
            },
            "direction": {"type": "integer", "default": 1, "description": "1=forward, -1=backward"},
        },
        required=["ns", "subs"],
    ),
    _pdb_schema(
        "pdb_data",
        "Check node existence: 0=not exists, 1=value only, 10=children only, 11=both. "
        "Analogous to MUMPS $DATA(^global(subs)).",
        {
            "ns": {"type": "string"},
            "subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
            },
        },
        required=["ns", "subs"],
    ),
    _pdb_schema(
        "pdb_kill",
        "Delete a node and its entire subtree. "
        "Analogous to MUMPS KILL ^global(subs).",
        {
            "ns": {"type": "string"},
            "subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
            },
        },
        required=["ns", "subs"],
    ),
    _pdb_schema(
        "pdb_incr",
        "Atomic increment. Creates node with 0 if missing. Returns new value. "
        "Analogous to MUMPS $INCREMENT(^global(subs), increment).",
        {
            "ns": {"type": "string"},
            "subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
            },
            "increment": {"type": "number", "default": 1},
        },
        required=["ns", "subs"],
    ),
    _pdb_schema(
        "pdb_merge",
        "Copy a subtree from source to target. "
        "Analogous to MUMPS MERGE ^target(t_subs)=^source(s_subs).",
        {
            "target_ns": {"type": "string"},
            "target_subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
            },
            "source_ns": {"type": "string"},
            "source_subs": {
                "type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
            },
        },
        required=["target_ns", "target_subs", "source_ns", "source_subs"],
    ),
    _pdb_schema(
        "pdb_query",
        "Execute a SQL query (SELECT/WITH only) on the database. "
        "Use for aggregations, JOINs, analytics. The _globals table stores "
        "all KV data with columns: ns, subkey, value.",
        {
            "sql": {"type": "string", "description": "SQL query (SELECT/WITH only)"},
            "params": {"type": "array", "items": {"type": ["string", "number", "null"]}},
            "limit": {"type": "integer", "default": 100},
        },
        required=["sql"],
    ),
    _pdb_schema(
        "pdb_schema",
        "Describe the database: list namespaces, node counts, app tables, DB size.",
        {},
    ),
    _pdb_schema(
        "pdb_backup",
        "Backup the database to a file, or show DB stats.",
        {"path": {"type": "string", "description": "Backup path. Omit for stats."}},
    ),
]

_HANDLERS = {
    "pdb_set": _handle_pdb_set,
    "pdb_get": _handle_pdb_get,
    "pdb_order": _handle_pdb_order,
    "pdb_data": _handle_pdb_data,
    "pdb_kill": _handle_pdb_kill,
    "pdb_incr": _handle_pdb_incr,
    "pdb_merge": _handle_pdb_merge,
    "pdb_query": _handle_pdb_query,
    "pdb_schema": _handle_pdb_schema,
    "pdb_backup": _handle_pdb_backup,
}


# ═══════════════════════════════════════════════════════════════════════════
# Plugin registration
# ═══════════════════════════════════════════════════════════════════════════

def register(ctx) -> None:
    """Register all 10 PDBM-Lumen tools with Hermes."""
    for schema in _TOOL_SCHEMAS:
        name = schema["name"]
        handler = _HANDLERS.get(name)
        if handler:
            ctx.register_tool(
                name=name,
                toolset="lumen-pdb",
                schema=schema,
                handler=handler,
            )
