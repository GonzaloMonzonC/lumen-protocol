#!/usr/bin/env python3
"""Minimal MCP server exposing only embed/embed_search with short names."""
from __future__ import annotations
import sys, json, logging, os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pdb_tools import tool_embed as _tool_embed, tool_embed_search as _tool_search

if sys.platform == "win32":
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
logger = logging.getLogger(__name__)

TOOLS = [
    {
        "name": "embed",
        "description": "Generate embeddings for text(s) and store in PDB. Uses fastembed (all-MiniLM-L6-v2, 384 dims). First call downloads model (~80MB).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "texts": {"type": "array", "items": {"type": "string"}, "description": "Texts to embed"},
                "source": {"type": "string", "description": "Optional source label"}
            },
            "required": ["texts"]
        }
    },
    {
        "name": "embed_search",
        "description": "Search indexed texts by cosine similarity. Returns top-N results with scores.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "limit": {"type": "integer", "description": "Max results", "default": 5}
            },
            "required": ["query"]
        }
    },
]

HANDLERS = {"embed": _tool_embed, "embed_search": _tool_search}

def send(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()

def handle(msg):
    mid = msg.get("id")
    method = msg.get("method", "")
    if method == "initialize":
        send({"jsonrpc":"2.0","id":mid,"result":{"protocolVersion":"2024-11-05","capabilities":{"tools":{"listChanged":False,"toolCount":len(TOOLS)}},"serverInfo":{"name":"embed-server","version":"0.1.0"}}})
    elif method == "tools/list":
        send({"jsonrpc":"2.0","id":mid,"result":{"tools":TOOLS}})
    elif method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name", "")
        args = params.get("arguments", {})
        handler = HANDLERS.get(name)
        if handler:
            try:
                result = handler(args)
                send({"jsonrpc":"2.0","id":mid,"result":{"content":[{"type":"text","text":json.dumps(result, ensure_ascii=False)}]}})
            except Exception as e:
                send({"jsonrpc":"2.0","id":mid,"error":{"code":-32603,"message":str(e)}})
        else:
            send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"Unknown tool: {name}"}})
    elif method == "notifications/initialized":
        pass
    else:
        send({"jsonrpc":"2.0","id":mid,"error":{"code":-32601,"message":f"Unknown method: {method}"}})

def main():
    while True:
        line = sys.stdin.readline()
        if not line: break
        line = line.strip()
        if not line: continue
        try:
            handle(json.loads(line))
        except json.JSONDecodeError as e:
            send({"jsonrpc":"2.0","error":{"code":-32700,"message":f"Parse error: {e}"}})

if __name__ == "__main__":
    main()
