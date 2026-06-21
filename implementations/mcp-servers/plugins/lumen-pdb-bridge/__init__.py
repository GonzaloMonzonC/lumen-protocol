"""
PDBM-Lumen Plugin for Hermes Agent.

Spawns PDBM-Lumen server via persistent subprocess (JSON-RPC stdio).
The server_shm.py variant is available for MCP config direct connection.

10 tools: pdb_set/get/order/data/kill/incr/merge/query/schema/backup.

Usage:
  Place in ~/.hermes/plugins/ and add to config.yaml:
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
# Persistent subprocess connection
# ═══════════════════════════════════════════════════════════════════════════

_server: subprocess.Popen[str] | None = None
_server_lock = threading.RLock()
_request_id = 0
_request_id_lock = threading.Lock()

_HERMES_VENV_PYTHON = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
    "hermes", "hermes-agent", "venv", "Scripts", "python.exe",
)


def _find_server() -> str:
    candidates = [
        os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
                os.path.abspath(__file__))))),
            "Documents", "GitHub", "lumen-protocol",
            "implementations", "mcp-servers", "pdb", "server.py",
        ),
        os.path.join(os.path.expanduser("~"),
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
                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, bufsize=1,
                cwd=os.path.dirname(server_path),
            )
            # Init handshake
            _rpc({"method": "initialize", "params": {}})
    return _server


def _rpc(msg: dict) -> dict:
    """Send JSON-RPC call, return result dict."""
    server = _get_server()
    with _request_id_lock:
        global _request_id
        _request_id += 1
        msg_id = msg.get("id", _request_id)
    payload = json.dumps({"jsonrpc": "2.0", "id": msg_id, **msg}, ensure_ascii=False)
    with _server_lock:
        server.stdin.write(payload + "\n")
        server.stdin.flush()
        line = server.stdout.readline()
    if not line:
        raise ConnectionError("PDB server closed")
    resp = json.loads(line.strip())
    if "error" in resp:
        raise RuntimeError(f"PDB error: {resp['error']}")
    return resp.get("result", {})


def _call_tool(name: str, args: dict) -> dict:
    result = _rpc({"method": "tools/call", "params": {"name": name, "arguments": args}})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        return json.loads(content[0]["text"])
    return result


# ═══════════════════════════════════════════════════════════════════════════
# Handlers
# ═══════════════════════════════════════════════════════════════════════════

def _h_set(a, **kw): return _call_tool("pdb_set", a)
def _h_get(a, **kw): return _call_tool("pdb_get", a)
def _h_order(a, **kw): return _call_tool("pdb_order", a)
def _h_data(a, **kw): return _call_tool("pdb_data", a)
def _h_kill(a, **kw): return _call_tool("pdb_kill", a)
def _h_incr(a, **kw): return _call_tool("pdb_incr", a)
def _h_merge(a, **kw): return _call_tool("pdb_merge", a)
def _h_query(a, **kw): return _call_tool("pdb_query", a)
def _h_schema(a, **kw): return _call_tool("pdb_schema", a)
def _h_backup(a, **kw): return _call_tool("pdb_backup", a)


# ═══════════════════════════════════════════════════════════════════════════
# Tool schemas
# ═══════════════════════════════════════════════════════════════════════════

def _s(name, desc, props, required=None):
    return {"name": name, "description": desc, "parameters": {
        "type": "object", "properties": props, "required": required or []}}

_S = [
    _s("pdb_set","MUMPS SET ^ns(subs)=value. Hierarchical path.",
       {"ns":{"type":"string"},"subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}},
        "value":{"description":"Value to store. JSON-serializable."}},["ns","subs","value"]),
    _s("pdb_get","MUMPS $GET(^ns(subs),default). Returns null if not found.",
       {"ns":{"type":"string"},"subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}},
        "default":{"description":"Default value"}},["ns","subs"]),
    _s("pdb_order","MUMPS $ORDER(^ns(subs),direction). Last sub '' = first/last. Returns null when done.",
       {"ns":{"type":"string"},"subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}},
        "direction":{"type":"integer","default":1}},["ns","subs"]),
    _s("pdb_data","MUMPS $DATA(). Returns 0/1/10/11.",
       {"ns":{"type":"string"},"subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}}},["ns","subs"]),
    _s("pdb_kill","MUMPS KILL ^ns(subs). Deletes node+subtree.",
       {"ns":{"type":"string"},"subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}}},["ns","subs"]),
    _s("pdb_incr","MUMPS $INCREMENT(). Atomic. Creates at 0 if missing.",
       {"ns":{"type":"string"},"subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}},
        "increment":{"type":"number","default":1}},["ns","subs"]),
    _s("pdb_merge","MUMPS MERGE. Copy subtree.",
       {"target_ns":{"type":"string"},"target_subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}},
        "source_ns":{"type":"string"},"source_subs":{"type":"array","items":{"oneOf":[{"type":"string"},{"type":"number"}]}}},
       ["target_ns","target_subs","source_ns","source_subs"]),
    _s("pdb_query","SQL SELECT/WITH on _globals table. Aggregations, analytics.",
       {"sql":{"type":"string"},"params":{"type":"array"},"limit":{"type":"integer","default":100}},["sql"]),
    _s("pdb_schema","Describe DB: namespaces, node counts, size.", {}),
    _s("pdb_backup","Backup DB file or show stats.",
       {"path":{"type":"string"}}),
]

_H = {
    "pdb_set":_h_set,"pdb_get":_h_get,"pdb_order":_h_order,
    "pdb_data":_h_data,"pdb_kill":_h_kill,"pdb_incr":_h_incr,
    "pdb_merge":_h_merge,"pdb_query":_h_query,
    "pdb_schema":_h_schema,"pdb_backup":_h_backup,
}


# ═══════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════

def register(ctx) -> None:
    for s in _S:
        h = _H.get(s["name"])
        if h:
            ctx.register_tool(name=s["name"], toolset="lumen-pdb", schema=s, handler=h)
