"""
PDBM-Lumen Plugin for Hermes Agent.

Spawns PDBM-Lumen server via persistent subprocess (JSON-RPC stdio).
The server_shm.py variant is available for MCP config direct connection.

43 tools: pdb_set/get/order/data/kill/incr/merge/query/schema/backup + batch/scratch/fts + lock/unlock + index_define/list/drop + trigger_define/list/drop/trigger + map_set/get/list/drop + partition_define/list/drop + m_eval/m_repl + dbfix + mvm_spawn/tick/list/kill/mailbox_send/mailbox_read.

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


def _call_tool(name: str, args: dict) -> str:
    """Call tool and return serialized JSON string for Hermes content field."""
    result = _rpc({"method": "tools/call", "params": {"name": name, "arguments": args}})
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        return content[0]["text"]  # raw JSON string — Hermes needs str, not dict
    return json.dumps(result)


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
    # ── Batch & Scratch ──
    _s("pdb_batch_set","Atomic batch insert. Multiple records in one transaction.",
       {"items":{"type":"array","items":{"type":"object","properties":{"ns":{"type":"string"},"subs":{"type":"array"},"value":{}}}}},["items"]),
    _s("pdb_scratch_set","Set scratchpad value (LLM working memory).",
       {"key":{"type":"string"},"value":{}},["key","value"]),
    _s("pdb_scratch_get","Get scratchpad value by key.",{"key":{"type":"string"}},["key"]),
    _s("pdb_scratch_del","Delete scratchpad key.",{"key":{"type":"string"}},["key"]),
    _s("pdb_fts_search","Full-text search across stored values (SQLite FTS5).",
       {"query":{"type":"string"},"limit":{"type":"integer","default":10},"ns":{"type":"string"}},["query"]),
    # ── Locks ──
    _s("pdb_lock","Acquire named lock with optional timeout.",
       {"ns":{"type":"string"},"timeout":{"type":"integer"},"owner":{"type":"string"}},["ns"]),
    _s("pdb_unlock","Release named lock.",{"ns":{"type":"string"}},["ns"]),
    # ── Indices ──
    _s("pdb_index_define","Define auto-index for a namespace.",
       {"ns":{"type":"string"},"idx_name":{"type":"string"},"sub_pos":{"type":"integer"}},["ns","idx_name"]),
    _s("pdb_index_list","List indices for namespace.",{"ns":{"type":"string"}}),
    _s("pdb_index_drop","Drop an index.",{"ns":{"type":"string"},"idx_name":{"type":"string"}},["ns","idx_name"]),
    # ── Triggers ──
    _s("pdb_trigger_define","Create trigger ON SET/ON KILL.",
       {"ns":{"type":"string"},"event":{"type":"string"},"action":{"type":"string"},"trigger_id":{"type":"string"},"params":{"type":"object"}},["ns","event","action"]),
    _s("pdb_trigger_list","List triggers for namespace.",{"ns":{"type":"string"}}),
    _s("pdb_trigger_drop","Drop a trigger.",{"ns":{"type":"string"},"trigger_id":{"type":"string"}},["ns","trigger_id"]),
    _s("pdb_trigger","Evaluate trigger manually.",{}),
    # ── Global Mapping ──
    _s("pdb_map_set","Map ^GLOBAL to a different DB file.",
       {"ns":{"type":"string"},"path":{"type":"string"}},["ns","path"]),
    _s("pdb_map_get","Get mapping for namespace.",{"ns":{"type":"string"}},["ns"]),
    _s("pdb_map_list","List all mappings.",{}),
    _s("pdb_map_drop","Remove namespace mapping.",{"ns":{"type":"string"}},["ns"]),
    # ── Partitioning ──
    _s("pdb_partition_define","Partition namespace into N files by key range.",
       {"ns":{"type":"string"},"ranges":{"type":"array"}},["ns"]),
    _s("pdb_partition_list","List partitions.",{}),
    _s("pdb_partition_drop","Drop partition config.",{"ns":{"type":"string"}},["ns"]),
    # ── M-Light ──
    _s("pdb_m_eval","Evaluate MUMPS expression via M-Light. Supports $GET, $DATA, $PIECE, etc.",
       {"expression":{"type":"string"}},["expression"]),
    _s("pdb_m_repl","Start M-Light REPL. Returns REPL handle.",{}),
    # ── Maintenance ──
    _s("pdb_dbfix","Repair/verify database.",{}),
    # ── MVM ──
    _s("pdb_mvm_spawn","Spawn a new MVM process.",
       {"code":{"type":"string"},"name":{"type":"string"}},["code"]),
    _s("pdb_mvm_tick","Run one tick of MVM scheduler.",{}),
    _s("pdb_mvm_list","List all MVM processes.",{}),
    _s("pdb_mvm_kill","Kill an MVM process by PID.",{"pid":{"type":"string"}},["pid"]),
    _s("pdb_mvm_mailbox_send","Send message to MVM mailbox.",
       {"pid":{"type":"string"},"message":{"type":"string"}},["pid","message"]),
    _s("pdb_mvm_mailbox_read","Read MVM mailbox messages.",
       {"pid":{"type":"string"}},["pid"]),
    # ── Embedding / RAG ──
    _s("pdb_embed","Generate embeddings for text(s) and store in PDB. Uses all-MiniLM-L6-v2 (384 dims).",
       {"texts":{"type":"array","items":{"type":"string"}},"source":{"type":"string"}},["texts"]),
    _s("pdb_embed_search","Search indexed texts by cosine similarity. Returns top-N with scores.",
       {"query":{"type":"string"},"limit":{"type":"integer","default":5}},["query"]),
]

_H = {
    "pdb_set":_h_set,"pdb_get":_h_get,"pdb_order":_h_order,
    "pdb_data":_h_data,"pdb_kill":_h_kill,"pdb_incr":_h_incr,
    "pdb_merge":_h_merge,"pdb_query":_h_query,
    "pdb_schema":_h_schema,"pdb_backup":_h_backup,
    # Additional tools — generic handler
    "pdb_batch_set": lambda a,**kw: _call_tool("pdb_batch_set",a),
    "pdb_scratch_set": lambda a,**kw: _call_tool("pdb_scratch_set",a),
    "pdb_scratch_get": lambda a,**kw: _call_tool("pdb_scratch_get",a),
    "pdb_scratch_del": lambda a,**kw: _call_tool("pdb_scratch_del",a),
    "pdb_fts_search": lambda a,**kw: _call_tool("pdb_fts_search",a),
    "pdb_lock": lambda a,**kw: _call_tool("pdb_lock",a),
    "pdb_unlock": lambda a,**kw: _call_tool("pdb_unlock",a),
    "pdb_index_define": lambda a,**kw: _call_tool("pdb_index_define",a),
    "pdb_index_list": lambda a,**kw: _call_tool("pdb_index_list",a),
    "pdb_index_drop": lambda a,**kw: _call_tool("pdb_index_drop",a),
    "pdb_trigger_define": lambda a,**kw: _call_tool("pdb_trigger_define",a),
    "pdb_trigger_list": lambda a,**kw: _call_tool("pdb_trigger_list",a),
    "pdb_trigger_drop": lambda a,**kw: _call_tool("pdb_trigger_drop",a),
    "pdb_trigger": lambda a,**kw: _call_tool("pdb_trigger",a),
    "pdb_map_set": lambda a,**kw: _call_tool("pdb_map_set",a),
    "pdb_map_get": lambda a,**kw: _call_tool("pdb_map_get",a),
    "pdb_map_list": lambda a,**kw: _call_tool("pdb_map_list",a),
    "pdb_map_drop": lambda a,**kw: _call_tool("pdb_map_drop",a),
    "pdb_partition_define": lambda a,**kw: _call_tool("pdb_partition_define",a),
    "pdb_partition_list": lambda a,**kw: _call_tool("pdb_partition_list",a),
    "pdb_partition_drop": lambda a,**kw: _call_tool("pdb_partition_drop",a),
    "pdb_m_eval": lambda a,**kw: _call_tool("pdb_m_eval",a),
    "pdb_m_repl": lambda a,**kw: _call_tool("pdb_m_repl",a),
    "pdb_dbfix": lambda a,**kw: _call_tool("pdb_dbfix",a),
    "pdb_mvm_spawn": lambda a,**kw: _call_tool("pdb_mvm_spawn",a),
    "pdb_mvm_tick": lambda a,**kw: _call_tool("pdb_mvm_tick",a),
    "pdb_mvm_list": lambda a,**kw: _call_tool("pdb_mvm_list",a),
    "pdb_mvm_kill": lambda a,**kw: _call_tool("pdb_mvm_kill",a),
    "pdb_mvm_mailbox_send": lambda a,**kw: _call_tool("pdb_mvm_mailbox_send",a),
    "pdb_mvm_mailbox_read": lambda a,**kw: _call_tool("pdb_mvm_mailbox_read",a),
    "pdb_embed": lambda a,**kw: _call_tool("pdb_embed",a),
    "pdb_embed_search": lambda a,**kw: _call_tool("pdb_embed_search",a),
}


# ═══════════════════════════════════════════════════════════════════════════
# Registration
# ═══════════════════════════════════════════════════════════════════════════

def register(ctx) -> None:
    for s in _S:
        h = _H.get(s["name"])
        if h:
            ctx.register_tool(name=s["name"], toolset="lumen-pdb", schema=s, handler=h)
