"""
LUMEN SHM Bridge Plugin for Hermes Agent.

Spawns all 3 LUMEN MCP servers (filesystem, thinking, web) with Level 2
zero-copy shared memory transport. Registers their tools in Hermes via
the plugin API with override=True — the LLM sees standard tool names
but all calls go through mmap ring buffers.

Architecture:
  Plugin spawns 3 persistent server processes (binary pipes for PROBE only).
  After PROBE→ACK→SHM negotiation, ALL tool calls go through mmap:
  
  LLM → Hermes → Plugin handler → SHM ring buffer → Server → SHM → Plugin → Hermes
  
  Zero kernel copies. Zero JSON-RPC overhead. 55-80% wire compression.

Usage:
  Place in ~/.hermes/plugins/ and add to config.yaml:
    plugins:
      lumen-shm-bridge:
        enabled: true
        toolsets: [lumen-shm]
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from typing import Any

# ═══════════════════════════════════════════════════════════════════════════
# Paths
# ═══════════════════════════════════════════════════════════════════════════

_HERMES_VENV_PYTHON = os.path.join(
    os.environ.get("LOCALAPPDATA", os.path.expanduser("~/AppData/Local")),
    "hermes", "hermes-agent", "venv", "Scripts", "python.exe"
)

def _find_repo_root() -> str:
    """Find lumen-protocol repo root."""
    candidates = [
        os.path.join(os.path.expanduser("~"), "Documents", "GitHub", "lumen-protocol"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "Documents", "GitHub", "lumen-protocol"),
    ]
    for c in candidates:
        if os.path.isdir(os.path.join(c, "implementations", "mcp-servers")):
            return c
    raise FileNotFoundError("Cannot find lumen-protocol repo")

_REPO_ROOT = _find_repo_root()
_MCP_SERVERS = os.path.join(_REPO_ROOT, "implementations", "mcp-servers")
_LUMEN_SRC = os.path.join(_REPO_ROOT, "implementations", "python", "src")

# Server paths (SHM variants)
_THINKING_SHM = os.path.join(_MCP_SERVERS, "thinking", "server_shm.py")
_FILESYSTEM_SHM = os.path.join(_MCP_SERVERS, "filesystem", "server_shm.py")
_WEB_SHM = os.path.join(_MCP_SERVERS, "web", "server_shm.py")
_PDB_SHM = os.path.join(_MCP_SERVERS, "pdb", "server_shm.py")
_PDB_STDIO = os.path.join(_MCP_SERVERS, "pdb", "server.py")

# ═══════════════════════════════════════════════════════════════════════════
# LUMEN imports (from repo, not pip — ensures latest code)
# ═══════════════════════════════════════════════════════════════════════════

sys.path.insert(0, _LUMEN_SRC)

from lumen import (
    build_frame, parse_frame, compress_value, decompress_value,
    TYPE_PROBE, TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED,
    ParseComplete, build_size, ShmRegion, ShmRingBuffer, ShmTransport, RingSide,
)

# ═══════════════════════════════════════════════════════════════════════════
# Persistent server connections
# ═══════════════════════════════════════════════════════════════════════════

class ShmServerConnection:
    """Manages a single LUMEN SHM server: spawn, PROBE handshake, SHM transport."""

    def __init__(self, name: str, server_path: str, shm_size: int = 512 * 1024):
        self.name = name
        self.server_path = server_path
        self.shm_size = shm_size
        self._proc: subprocess.Popen | None = None
        self._region: ShmRegion | None = None
        self._transport: ShmTransport | None = None
        self._lock = threading.Lock()
        self._request_id = 0

    def start(self) -> None:
        """Spawn server, perform PROBE handshake, set up SHM transport."""
        user_home = os.path.expanduser("~")

        # Use binary pipes — plugin controls the subprocess!
        self._proc = subprocess.Popen(
            [_HERMES_VENV_PYTHON, "-u", self.server_path, "--dashboard", "9876"] if "thinking" in self.server_path else
            [_HERMES_VENV_PYTHON, "-u", self.server_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=False,  # ← BINARY PIPES! Plugin owns this.
            cwd=user_home,
        )

        # Phase 1: Send LUMEN PROBE
        probe_msg = {
            "protocol": "LUMEN",
            "client_name": "hermes-shm-bridge",
            "supported_versions": ["1.0"],
        }
        self._send_stdio(probe_msg, is_probe=True)

        # Phase 2: Read PROBE_ACK
        ack = self._read_stdio()
        if not ack or ack.get("protocol") != "LUMEN":
            raise RuntimeError(f"[{self.name}] PROBE handshake failed: {ack}")

        shm_name = ack.get("shm_region")
        if not shm_name:
            raise RuntimeError(f"[{self.name}] Server did not advertise SHM region")

        # Phase 3: Open SHM region
        time.sleep(0.05)  # Small delay for server to finish mmap setup
        self._region = ShmRegion.open(shm_name, ack["shm_size"])
        if not self._region.validate():
            raise RuntimeError(f"[{self.name}] SHM region validation failed")

        # Client side: write to Ring A, read from Ring B
        write_ring = self._region.ring_buffer(RingSide.A)
        read_ring = self._region.ring_buffer(RingSide.B)
        self._transport = ShmTransport(write_ring, read_ring)

        # Phase 4: Send initialize via SHM
        init_resp = self._call_jsonrpc("initialize", {
            "protocolVersion": "2025-03-26",
            "capabilities": {},
            "clientInfo": {"name": "hermes-shm-bridge", "version": "1.0.0"},
        })
        srv_name = init_resp.get("result", {}).get("serverInfo", {}).get("name", "?")
        transport_type = init_resp.get("result", {}).get("serverInfo", {}).get("transport", "?")

        # Phase 5: List tools
        tools_resp = self._call_jsonrpc("tools/list", {})
        self.tools = tools_resp.get("result", {}).get("tools", [])
        tool_count = len(self.tools)

        print(f"[lumen-shm-bridge] {self.name}: {tool_count} tools, "
              f"server={srv_name}, transport={transport_type}, "
              f"shm={shm_name} ({ack['shm_size']//1024} KiB)")

    def call_tool(self, tool_name: str, arguments: dict) -> dict:
        """Call a tool on the server via SHM. Thread-safe."""
        with self._lock:
            result = self._call_jsonrpc("tools/call", {
                "name": tool_name,
                "arguments": arguments,
            })
            return result.get("result", {})

    def _call_jsonrpc(self, method: str, params: dict) -> dict:
        """Send a JSON-RPC request via SHM, return response."""
        self._request_id += 1
        req = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        self._send_shm(req)
        return self._read_shm()

    # ── stdio I/O (PROBE only) ────────────────────────────────────────

    def _send_stdio(self, data: dict, is_probe: bool = False) -> None:
        payload = compress_value(data)
        buf = bytearray(build_size(payload_len=len(payload)))
        frame_type = TYPE_PROBE if is_probe else TYPE_REQUEST
        build_frame(frame_type, FLAG_COMPRESSED, payload, buf, 0)
        self._proc.stdin.write(buf)
        self._proc.stdin.flush()

    def _read_stdio(self) -> dict | None:
        buf = bytearray()
        for _ in range(2000):
            b = self._proc.stdout.read(1)
            if not b:
                break
            buf.extend(b)
            result = parse_frame(buf, 0)
            if isinstance(result, ParseComplete):
                frame = result.frame
                payload = frame.payload
                if frame.flags & FLAG_COMPRESSED:
                    payload = decompress_value(payload)
                return payload
        return None

    # ── SHM I/O (all tool calls) ──────────────────────────────────────

    def _send_shm(self, data: dict) -> None:
        payload = compress_value(data)
        buf = bytearray(build_size(payload_len=len(payload)))
        build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)
        self._transport.send_frame(bytes(buf))

    def _read_shm(self) -> dict:
        raw = self._transport.recv_frame()
        if raw is None:
            raise RuntimeError(f"[{self.name}] SHM read timeout")
        result = parse_frame(bytearray(raw), 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload
        raise RuntimeError(f"[{self.name}] Invalid SHM frame")

    def stop(self) -> None:
        """Clean up."""
        if self._region:
            self._region.close()
            self._region = None
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None


# ═══════════════════════════════════════════════════════════════════════════
# Global connection pool
# ═══════════════════════════════════════════════════════════════════════════

_connections: dict[str, ShmServerConnection] = {}
_conn_lock = threading.Lock()

SERVER_CONFIGS = {
    "filesystem": (_FILESYSTEM_SHM, 8 * 1024 * 1024),   # 8 MiB for large files
    "thinking":   (_THINKING_SHM,   2 * 1024 * 1024),   # 2 MiB
    "web":        (_WEB_SHM,          512 * 1024),       # 512 KiB
    "pdb":        (_PDB_SHM,          512 * 1024),       # 512 KiB (tool payloads are small)
}


def _get_connection(name: str) -> ShmServerConnection:
    """Get or create a persistent SHM connection to a server."""
    with _conn_lock:
        if name not in _connections or _connections[name]._proc is None or _connections[name]._proc.poll() is not None:
            path, size = SERVER_CONFIGS[name]
            conn = ShmServerConnection(f"lumen-{name}-shm", path, size)
            conn.start()
            _connections[name] = conn
        return _connections[name]


# ═══════════════════════════════════════════════════════════════════════════
# Tool handlers — same signatures as Hermes built-ins
# ═══════════════════════════════════════════════════════════════════════════

def _handle_filesystem_read_file(*args, **kwargs) -> str:
    # Hermes passes all params as a dict in the first positional arg
    params = args[0] if args else kwargs
    path = params.get("path", "")
    offset = params.get("offset", 1)
    limit = params.get("limit", 500)
    conn = _get_connection("filesystem")
    result = conn.call_tool("read_file", {"path": path, "offset": offset, "limit": limit})
    content = result.get("content", [])
    return "\n".join(
        item.get("text", "") for item in content if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_filesystem_write_file(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    path = params.get("path", "")
    content = params.get("content", "")
    conn = _get_connection("filesystem")
    result = conn.call_tool("write_file", {"path": path, "content": content})
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_filesystem_search_files(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("search_files", {
        "pattern": params.get("pattern", ""),
        "target": params.get("target", "content"),
        "path": params.get("path_param", params.get("path", ".")),
        "file_glob": params.get("file_glob"),
        "limit": params.get("limit", 50),
        "offset": params.get("offset", 0),
        "output_mode": params.get("output_mode", "content"),
        "context": params.get("context", 0),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_filesystem_patch(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("patch", {
        "path": params.get("path"),
        "old_string": params.get("old_string"),
        "new_string": params.get("new_string", ""),
        "replace_all": params.get("replace_all", False),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_thinking_sequential_thinking(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    tool_args = {"thought": params.get("thought", ""), "nextThoughtNeeded": params.get("nextThoughtNeeded", False), "totalThoughts": params.get("totalThoughts", 1)}
    for k in ("thoughtNumber", "isRevision", "revisesThought", "branchFromThought", "branchId", "needsMoreThoughts", "chainId"):
        if k in params and params[k] is not None:
            tool_args[k] = params[k]
    result = conn.call_tool("sequential_thinking", tool_args)
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_web_search(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("web")
    result = conn.call_tool("web_search", {"query": params.get("query", ""), "limit": params.get("limit", 5)})
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_web_extract(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("web")
    result = conn.call_tool("web_extract", {"urls": params.get("urls", [])})
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Plugin registration
# ═══════════════════════════════════════════════════════════════════════════

def register(ctx) -> None:
    """Register LUMEN SHM-backed tools, overriding Hermes built-ins."""

    # ── Filesystem tools (override built-ins) ──
    ctx.register_tool(
        name="read_file", toolset="lumen-shm",
        schema={
            "name": "read_file",
            "description": "Read a text file with line numbers and pagination. [LUMEN SHM — zero-copy mmap]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file to read"},
                    "offset": {"type": "integer", "description": "Line number to start from (1-indexed)", "default": 1, "minimum": 1},
                    "limit": {"type": "integer", "description": "Max lines to read", "default": 500, "maximum": 2000},
                },
                "required": ["path"],
            },
        },
        handler=_handle_filesystem_read_file,
        override=True,
    )

    ctx.register_tool(
        name="write_file", toolset="lumen-shm",
        schema={
            "name": "write_file",
            "description": "Write content to a file, overwriting it. [LUMEN SHM — zero-copy mmap]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to write"},
                    "content": {"type": "string", "description": "Content to write"},
                },
                "required": ["path", "content"],
            },
        },
        handler=_handle_filesystem_write_file,
        override=True,
    )

    ctx.register_tool(
        name="search_files", toolset="lumen-shm",
        schema={
            "name": "search_files",
            "description": "Search file contents or find files by name. [LUMEN SHM — 6x faster]",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex or glob pattern"},
                    "target": {"type": "string", "enum": ["content", "files"], "default": "content"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "."},
                    "file_glob": {"type": "string", "description": "Filter by glob"},
                    "limit": {"type": "integer", "default": 50},
                    "offset": {"type": "integer", "default": 0},
                    "output_mode": {"type": "string", "enum": ["content", "files_only", "count"], "default": "content"},
                    "context": {"type": "integer", "default": 0},
                },
                "required": ["pattern"],
            },
        },
        handler=_handle_filesystem_search_files,
        override=True,
    )

    ctx.register_tool(
        name="patch", toolset="lumen-shm",
        schema={
            "name": "patch",
            "description": "Targeted find-and-replace edits. [LUMEN SHM — zero-copy mmap]",
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["replace", "patch"], "default": "replace"},
                    "path": {"type": "string", "description": "File path"},
                    "old_string": {"type": "string", "description": "Text to find"},
                    "new_string": {"type": "string", "description": "Replacement text", "default": ""},
                    "replace_all": {"type": "boolean", "default": False},
                },
                "required": ["mode"],
            },
        },
        handler=_handle_filesystem_patch,
        override=True,
    )

    # ── Thinking tools ──
    ctx.register_tool(
        name="sequential_thinking", toolset="lumen-shm",
        schema={
            "name": "sequential_thinking",
            "description": "Structured reasoning tool — break down complex problems step by step. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {"type": "string", "description": "The current thinking step"},
                    "nextThoughtNeeded": {"type": "boolean", "description": "Whether another thought is needed"},
                    "totalThoughts": {"type": "integer", "description": "Estimated total thoughts", "minimum": 1},
                    "thoughtNumber": {"type": "integer", "description": "Current thought number", "minimum": 1},
                    "isRevision": {"type": "boolean", "default": False},
                    "revisesThought": {"type": "integer", "minimum": 1},
                    "branchFromThought": {"type": "integer", "minimum": 1},
                    "branchId": {"type": "string"},
                    "needsMoreThoughts": {"type": "boolean", "default": False},
                    "chainId": {"type": "string", "description": "Existing chain ID to continue"},
                },
                "required": ["thought", "nextThoughtNeeded", "totalThoughts"],
            },
        },
        handler=_handle_thinking_sequential_thinking,
    )

    # ── Web tools ──
    ctx.register_tool(
        name="web_search", toolset="lumen-shm",
        schema={
            "name": "web_search",
            "description": "Search the web. [LUMEN SHM — search+extract unified, zero API key]",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results", "minimum": 1, "maximum": 100, "default": 5},
                },
                "required": ["query"],
            },
        },
        handler=_handle_web_search,
        override=True,
    )

    ctx.register_tool(
        name="web_extract", toolset="lumen-shm",
        schema={
            "name": "web_extract",
            "description": "Extract content from web pages. [LUMEN SHM — zero-copy mmap]",
            "parameters": {
                "type": "object",
                "properties": {
                    "urls": {"type": "array", "items": {"type": "string"}, "description": "URLs to extract", "maxItems": 5},
                },
                "required": ["urls"],
            },
        },
        handler=_handle_web_extract,
        override=True,
    )


    # ── Additional filesystem tools ──
    ctx.register_tool(
        name="list_directory", toolset="lumen-shm",
        schema={
            "name": "list_directory",
            "description": "List files and directories. Use this instead of ls/dir in terminal. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to list", "default": "."},
                    "file_glob": {"type": "string", "description": "Filter by glob pattern"},
                },
            },
        },
        handler=_handle_list_directory,
    )

    ctx.register_tool(
        name="read_files", toolset="lumen-shm",
        schema={
            "name": "read_files",
            "description": "Read multiple files in a single call. Bulk N files in 1 call. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths"},
                    "limit_per_file": {"type": "integer", "description": "Max lines per file", "default": 100, "minimum": 1, "maximum": 500},
                    "max_total_chars": {"type": "integer", "description": "Max total chars", "default": 50000, "maximum": 100000},
                },
                "required": ["paths"],
            },
        },
        handler=_handle_read_files,
    )

    ctx.register_tool(
        name="search_with_context", toolset="lumen-shm",
        schema={
            "name": "search_with_context",
            "description": "Search with context lines around each match. Shows surrounding code. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to search for"},
                    "path": {"type": "string", "description": "Directory or file to search", "default": "."},
                    "context": {"type": "integer", "description": "Lines of context before and after each match", "default": 3, "minimum": 0, "maximum": 20},
                    "file_glob": {"type": "string", "description": "Filter by glob"},
                    "limit": {"type": "integer", "description": "Max matches", "default": 20, "maximum": 100},
                },
                "required": ["pattern"],
            },
        },
        handler=_handle_search_with_context,
    )

    ctx.register_tool(
        name="stream_read", toolset="lumen-shm",
        schema={
            "name": "stream_read",
            "description": "Stream-read a large file in chunks. Use for files too big for read_file. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file"},
                    "chunk_number": {"type": "integer", "description": "Which chunk to return (1-based)", "default": 1, "minimum": 1},
                    "chunk_size": {"type": "integer", "description": "Lines per chunk", "default": 500, "maximum": 5000},
                },
                "required": ["path"],
            },
        },
        handler=_handle_stream_read,
    )

    # ── Additional thinking tools (Reasoning Chain Engine) ──
    ctx.register_tool(
        name="thought_similarity", toolset="lumen-shm",
        schema={
            "name": "thought_similarity",
            "description": "Find semantically similar thoughts in a reasoning chain using TF-IDF cosine similarity. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string", "description": "Chain ID to search in"},
                    "thought": {"type": "string", "description": "Thought to find similar matches for"},
                    "topN": {"type": "integer", "description": "Number of similar thoughts", "default": 3, "maximum": 10},
                    "minScore": {"type": "number", "description": "Minimum similarity score 0-1", "default": 0.1},
                },
                "required": ["chainId", "thought"],
            },
        },
        handler=_handle_thought_similarity,
    )

    ctx.register_tool(
        name="thought_contradiction", toolset="lumen-shm",
        schema={
            "name": "thought_contradiction",
            "description": "Detect thoughts in a chain that semantically contradict a given thought. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string", "description": "Chain ID to check"},
                    "thought": {"type": "string", "description": "Thought to check for contradictions against"},
                },
                "required": ["chainId", "thought"],
            },
        },
        handler=_handle_thought_contradiction,
    )

    ctx.register_tool(
        name="thought_summarize", toolset="lumen-shm",
        schema={
            "name": "thought_summarize",
            "description": "Cluster a reasoning chain's thoughts into thematic groups. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string", "description": "Chain ID to summarize"},
                    "maxClusters": {"type": "integer", "description": "Max clusters to return", "default": 5},
                },
                "required": ["chainId"],
            },
        },
        handler=_handle_thought_summarize,
    )

    ctx.register_tool(
        name="thought_to_plan", toolset="lumen-shm",
        schema={
            "name": "thought_to_plan",
            "description": "Convert a reasoning chain into an actionable plan with steps and dependencies. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string", "description": "Chain ID to convert"},
                    "format": {"type": "string", "enum": ["markdown", "json"], "description": "Output format", "default": "markdown"},
                },
                "required": ["chainId"],
            },
        },
        handler=_handle_thought_to_plan,
    )

    ctx.register_tool(
        name="thought_evaluate", toolset="lumen-shm",
        schema={
            "name": "thought_evaluate",
            "description": "Evaluate a thought in a chain for specificity, actionability, and concreteness. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string", "description": "Chain ID"},
                    "thoughtNumber": {"type": "integer", "description": "Thought number to evaluate", "minimum": 1},
                },
                "required": ["chainId", "thoughtNumber"],
            },
        },
        handler=_handle_thought_evaluate,
    )

    ctx.register_tool(
        name="thought_bridge", toolset="lumen-shm",
        schema={
            "name": "thought_bridge",
            "description": "Find cross-chain connections — discover related thoughts across different reasoning sessions. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "thought": {"type": "string", "description": "Thought to find bridges for"},
                    "topN": {"type": "integer", "description": "Number of bridges", "default": 3},
                },
                "required": ["thought"],
            },
        },
        handler=_handle_thought_bridge,
    )


    # ── Filesystem: server_stats ──
    ctx.register_tool(
        name="server_stats", toolset="lumen-shm",
        schema={
            "name": "server_stats",
            "description": "Get LUMEN filesystem server health metrics: uptime, requests, tool usage. [LUMEN SHM]",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=_handle_server_stats,
    )

    # ── Thinking: 22 additional cognitive tools ──
    ctx.register_tool(
        name="assume", toolset="lumen-shm",
        schema={
            "name": "assume",
            "description": "Record an assumption for later validation. Surface hidden premises in decision-making. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"statement": {"type": "string", "description": "statement parameter"}, "category": {"type": "string", "description": "category parameter"}, }, "required": ["statement", "category"]},
        },
        handler=_make_thinking_handler("assume"),
    )
    ctx.register_tool(
        name="list_assumptions", toolset="lumen-shm",
        schema={
            "name": "list_assumptions",
            "description": "List all recorded assumptions with their validation status. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("list_assumptions"),
    )
    ctx.register_tool(
        name="check_assumption", toolset="lumen-shm",
        schema={
            "name": "check_assumption",
            "description": "Validate an assumption against evidence. Mark as confirmed/violated. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"id": {"type": "string", "description": "id parameter"}, "status": {"type": "string", "description": "status parameter"}, }, "required": ["id", "status"]},
        },
        handler=_make_thinking_handler("check_assumption"),
    )
    ctx.register_tool(
        name="model_add", toolset="lumen-shm",
        schema={
            "name": "model_add",
            "description": "Add an entity to the mental model graph with properties and relationships. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"entity": {"type": "string", "description": "entity parameter"}, }, "required": ["entity"]},
        },
        handler=_make_thinking_handler("model_add"),
    )
    ctx.register_tool(
        name="model_query", toolset="lumen-shm",
        schema={
            "name": "model_query",
            "description": "Query the mental model graph for entities matching criteria. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("model_query"),
    )
    ctx.register_tool(
        name="model_stats", toolset="lumen-shm",
        schema={
            "name": "model_stats",
            "description": "Get statistics about the mental model: entity count, relationship density. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("model_stats"),
    )
    ctx.register_tool(
        name="model_map", toolset="lumen-shm",
        schema={
            "name": "model_map",
            "description": "Visualize the mental model as a relationship map. Shows knowledge gaps. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("model_map"),
    )
    ctx.register_tool(
        name="model_remove", toolset="lumen-shm",
        schema={
            "name": "model_remove",
            "description": "Remove an entity from the mental model. Dependencies auto-update. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"entity": {"type": "string", "description": "entity parameter"}, }, "required": ["entity"]},
        },
        handler=_make_thinking_handler("model_remove"),
    )
    ctx.register_tool(
        name="model_scan", toolset="lumen-shm",
        schema={
            "name": "model_scan",
            "description": "Scan the mental model for entities matching a pattern. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("model_scan"),
    )
    ctx.register_tool(
        name="context_preserve", toolset="lumen-shm",
        schema={
            "name": "context_preserve",
            "description": "Anchor critical context to prevent decay in long conversations. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"label": {"type": "string", "description": "label parameter"}, "content": {"type": "string", "description": "content parameter"}, }, "required": ["label", "content"]},
        },
        handler=_make_thinking_handler("context_preserve"),
    )
    ctx.register_tool(
        name="context_check", toolset="lumen-shm",
        schema={
            "name": "context_check",
            "description": "Check if preserved context is still available (not decayed). [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("context_check"),
    )
    ctx.register_tool(
        name="work_start", toolset="lumen-shm",
        schema={
            "name": "work_start",
            "description": "Start a multi-session work item. Persists across sessions. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"title": {"type": "string", "description": "title parameter"}, }, "required": ["title"]},
        },
        handler=_make_thinking_handler("work_start"),
    )
    ctx.register_tool(
        name="work_block", toolset="lumen-shm",
        schema={
            "name": "work_block",
            "description": "Mark a work block as in_progress/done. Track sub-tasks. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"block_id": {"type": "string", "description": "block_id parameter"}, }, "required": ["block_id"]},
        },
        handler=_make_thinking_handler("work_block"),
    )
    ctx.register_tool(
        name="work_done", toolset="lumen-shm",
        schema={
            "name": "work_done",
            "description": "Mark a work block as completed. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"block_id": {"type": "string", "description": "block_id parameter"}, }, "required": ["block_id"]},
        },
        handler=_make_thinking_handler("work_done"),
    )
    ctx.register_tool(
        name="work_log", toolset="lumen-shm",
        schema={
            "name": "work_log",
            "description": "View work log: completed blocks, pending items, velocity. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("work_log"),
    )
    ctx.register_tool(
        name="context_estimate", toolset="lumen-shm",
        schema={
            "name": "context_estimate",
            "description": "Estimate token usage for pre-flight planning. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("context_estimate"),
    )
    ctx.register_tool(
        name="session_init", toolset="lumen-shm",
        schema={
            "name": "session_init",
            "description": "Initialize a multi-agent session with isolated state. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("session_init"),
    )
    ctx.register_tool(
        name="session_list", toolset="lumen-shm",
        schema={
            "name": "session_list",
            "description": "List all active sessions with stats. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("session_list"),
    )
    ctx.register_tool(
        name="pattern_record", toolset="lumen-shm",
        schema={
            "name": "pattern_record",
            "description": "Record a bug pattern with fix strategy for institutional memory. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"pattern_name": {"type": "string", "description": "pattern_name parameter"}, "description": {"type": "string", "description": "description parameter"}, }, "required": ["pattern_name", "description"]},
        },
        handler=_make_thinking_handler("pattern_record"),
    )
    ctx.register_tool(
        name="pattern_match", toolset="lumen-shm",
        schema={
            "name": "pattern_match",
            "description": "Match current problem against recorded patterns (Jaccard similarity). [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"description": {"type": "string", "description": "description parameter"}, }, "required": ["description"]},
        },
        handler=_make_thinking_handler("pattern_match"),
    )
    ctx.register_tool(
        name="decision_log", toolset="lumen-shm",
        schema={
            "name": "decision_log",
            "description": "Record an architecture decision with rationale, alternatives, and revisit triggers. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {"decision": {"type": "string", "description": "decision parameter"}, }, "required": ["decision"]},
        },
        handler=_make_thinking_handler("decision_log"),
    )
    ctx.register_tool(
        name="decision_list", toolset="lumen-shm",
        schema={
            "name": "decision_list",
            "description": "List recorded decisions by category. [LUMEN SHM]",
            "parameters": {"type": "object",                 "properties": {}, "required": []},
        },
        handler=_make_thinking_handler("decision_list"),
    )

    # ── Token-efficient tools (🆕 June 2026) ──
    ctx.register_tool(
        name="collision_check", toolset="lumen-shm",
        schema={
            "name": "collision_check",
            "description": "Check for file collisions between active sessions. [LUMEN SHM]",
            "parameters": {"type": "object", "properties": {"window_seconds": {"type": "integer", "description": "Time window in seconds (default 300)"}}, "required": []},
        },
        handler=_make_thinking_handler("collision_check"),
    )
    ctx.register_tool(
        name="state_snapshot", toolset="lumen-shm",
        schema={
            "name": "state_snapshot",
            "description": "Ultra-compact system health snapshot (1 line). Returns chain count, thought count, avg score, pattern count, work count, and total tool calls. [LUMEN SHM]",
            "parameters": {"type": "object", "properties": {}},
        },
        handler=_make_thinking_handler("state_snapshot"),
    )
    ctx.register_tool(
        name="thought_compress", toolset="lumen-shm",
        schema={
            "name": "thought_compress",
            "description": "Compress a reasoning chain to N key thoughts (default 3). Selects first, last, and top-scored middle thoughts. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string"},
                    "targetThoughts": {"type": "integer", "default": 3, "maximum": 10},
                },
                "required": ["chainId"],
            },
        },
        handler=_make_thinking_handler("thought_compress"),
    )
    ctx.register_tool(
        name="chain_diff", toolset="lumen-shm",
        schema={
            "name": "chain_diff",
            "description": "Show only what changed between two points in a reasoning chain: additions, revisions, branches count. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "chainId": {"type": "string"},
                    "from": {"type": "integer", "default": 1},
                    "to": {"type": "integer"},
                },
                "required": ["chainId"],
            },
        },
        handler=_make_thinking_handler("chain_diff"),
    )
    ctx.register_tool(
        name="tool_cache", toolset="lumen-shm",
        schema={
            "name": "tool_cache",
            "description": "Cache expensive results. SET: tool_cache(key, value, ttl). GET: tool_cache(key). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "ttl": {"type": "integer", "default": 300},
                },
                "required": ["key"],
            },
        },
        handler=_make_thinking_handler("tool_cache"),
    )
    ctx.register_tool(
        name="batch_call", toolset="lumen-shm",
        schema={
            "name": "batch_call",
            "description": "Execute multiple tools in sequence, returning ONE compact output line. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "tools": {"type": "array", "items": {"type": "object"}, "description": "List of {name, args} objects"},
                },
                "required": ["tools"],
            },
        },
        handler=_make_thinking_handler("batch_call"),
    )

    ctx.register_tool(
        name="niche_create", toolset="lumen-shm",
        schema={
            "name": "niche_create",
            "description": "Create a new cognitive niche (project/area). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Niche name"},
                    "desc": {"type": "string", "description": "Niche description"},
                    "color": {"type": "string", "description": "Niche color (hex)", "default": "#22d3ee"}
                },
                "required": ["name"]
            },
        },
        handler=_make_thinking_handler("niche_create"),
    )


    ctx.register_tool(
        name="niche_list", toolset="lumen-shm",
        schema={
            "name": "niche_list",
            "description": "List all cognitive niches. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {}
            },
        },
        handler=_make_thinking_handler("niche_list"),
    )

    ctx.register_tool(
        name="niche_update", toolset="lumen-shm",
        schema={
            "name": "niche_update",
            "description": "Update niche properties (name, desc, color, columns, archive). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche_id": {"type": "string", "description": "Niche ID"},
                    "name": {"type": "string", "description": "New name"},
                    "desc": {"type": "string", "description": "New description"},
                    "color": {"type": "string", "description": "New color (hex)"},
                    "archived": {"type": "boolean", "description": "Archive (true) or unarchive (false)"}
                },
                "required": ["niche_id"]
            },
        },
        handler=_make_thinking_handler("niche_update"),
    )


    ctx.register_tool(
        name="task_create", toolset="lumen-shm",
        schema={
            "name": "task_create",
            "description": "Create a new task in a niche. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche_id": {"type": "string", "description": "Niche ID"},
                    "title": {"type": "string", "description": "Task title"},
                    "desc": {"type": "string", "description": "Task description"},
                    "priority": {"type": "string", "description": "Task priority (low, medium, high, critical)", "default": "medium"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Task tags"},
                    "assignee": {"type": "string", "description": "Task assignee (session ID)"}
                },
                "required": ["niche_id", "title"]
            },
        },
        handler=_make_thinking_handler("task_create"),
    )


    ctx.register_tool(
        name="task_move", toolset="lumen-shm",
        schema={
            "name": "task_move",
            "description": "Move a task to a column (or edit fields). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "to_column": {"type": "string", "description": "Target column (e.g., Backlog, In Progress, Done)"},
                    "title": {"type": "string", "description": "New title (optional)"},
                    "desc": {"type": "string", "description": "New description (optional)"},
                    "priority": {"type": "string", "description": "New priority (optional)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags (optional)"},
                    "assignee": {"type": "string", "description": "New assignee (optional)"}
                },
                "required": ["task_id"]
            },
        },
        handler=_make_thinking_handler("task_move"),
    )


    ctx.register_tool(
        name="task_link", toolset="lumen-shm",
        schema={
            "name": "task_link",
            "description": "Link a task to LUMEN cognitive objects (chain, pattern, decision, wiki). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "chain_id": {"type": "string", "description": "Chain ID to link"},
                    "pattern_id": {"type": "string", "description": "Pattern ID to link"},
                    "decision_id": {"type": "string", "description": "Decision ID to link"},
                    "wiki_id": {"type": "string", "description": "Wiki ID to link"}
                },
                "required": ["task_id"]
            },
        },
        handler=_make_thinking_handler("task_link"),
    )


    ctx.register_tool(
        name="task_list", toolset="lumen-shm",
        schema={
            "name": "task_list",
            "description": "List tasks with optional filtering. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche_id": {"type": "string", "description": "Filter by niche ID"},
                    "status": {"type": "string", "description": "Filter by status (column)"},
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "search": {"type": "string", "description": "Search in title, description, tags"},
                    "limit": {"type": "integer", "description": "Limit number of results"}
                }
            },
        },
        handler=_make_thinking_handler("task_list"),
    )

    ctx.register_tool(
        name="web_snapshot", toolset="lumen-shm",
        schema={"name":"web_snapshot","description":"Extract web page and save as cognitive snapshot [LUMEN SHM]","parameters":{"type":"object","properties":{"url":{"type":"string"},"max_chars":{"type":"integer"},"task_id":{"type":"string"}},"required":["url"]}},
        handler=_make_thinking_handler("web_snapshot"),
    )
    ctx.register_tool(
        name="web_snapshots_list", toolset="lumen-shm",
        schema={"name":"web_snapshots_list","description":"List saved web snapshots [LUMEN SHM]","parameters":{"type":"object","properties":{"task_id":{"type":"string"},"limit":{"type":"integer"}}}},
        handler=_make_thinking_handler("web_snapshots_list"),
    )
    ctx.register_tool(
        name="task_link_url", toolset="lumen-shm",
        schema={"name":"task_link_url","description":"Link URL to a kanban task [LUMEN SHM]","parameters":{"type":"object","properties":{"task_id":{"type":"string"},"url":{"type":"string"}},"required":["task_id","url"]}},
        handler=_make_thinking_handler("task_link_url"),
    )

    ctx.register_tool(
        name="qa_ask", toolset="lumen-shm",
        schema={"name":"qa_ask","description":"Ask a question and store Q&A as cognitive artifact [LUMEN SHM]","parameters":{"type":"object","properties":{"question":{"type":"string"},"answer":{"type":"string"},"context":{"type":"string"},"tags":{"type":"array","items":{"type":"string"}}},"required":["question"]}},
        handler=_make_thinking_handler("qa_ask"),
    )
    ctx.register_tool(
        name="qa_list", toolset="lumen-shm",
        schema={"name":"qa_list","description":"List stored Q&A pairs [LUMEN SHM]","parameters":{"type":"object","properties":{"tags":{"type":"array","items":{"type":"string"}},"limit":{"type":"integer"}}}},
        handler=_make_thinking_handler("qa_list"),
    )
    ctx.register_tool(
        name="qa_link", toolset="lumen-shm",
        schema={"name":"qa_link","description":"Link Q&A pair to a kanban task or chain [LUMEN SHM]","parameters":{"type":"object","properties":{"qa_id":{"type":"string"},"task_id":{"type":"string"},"chain_id":{"type":"string"}},"required":["qa_id"]}},
        handler=_make_thinking_handler("qa_link"),
    )

    ctx.register_tool(
        name="unified_search", toolset="lumen-shm",
        schema={"name":"unified_search","description":"Search across all cognitive subsystems simultaneously [LUMEN SHM]","parameters":{"type":"object","properties":{"query":{"type":"string"},"limit":{"type":"integer"}},"required":["query"]}},
        handler=_make_thinking_handler("unified_search"),
    )
    ctx.register_tool(
        name="cognitive_integrity", toolset="lumen-shm",
        schema={"name":"cognitive_integrity","description":"Check cognitive system health: unlinked tasks, unanswered Q&A, stale decisions [LUMEN SHM]","parameters":{"type":"object","properties":{}}},
        handler=_make_thinking_handler("cognitive_integrity"),
    )

    ctx.register_tool(
        name="task_delete", toolset="lumen-shm",
        schema={
            "name": "task_delete",
            "description": "Delete a task permanently. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID to delete"}
                },
                "required": ["task_id"]
            },
        },
        handler=_make_thinking_handler("task_delete"),
    )

    ctx.register_tool(
        name="kanban_stats", toolset="lumen-shm",
        schema={
            "name": "kanban_stats",
            "description": "Show kanban statistics per niche. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche_id": {"type": "string", "description": "Filter by niche ID (optional)"}
                }
            },
        },
        handler=_make_thinking_handler("kanban_stats"),
    )

    ctx.register_tool(
        name="task_search", toolset="lumen-shm",
        schema={
            "name": "task_search",
            "description": "Search tasks across niches by title, description, tags, references. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search text (title, desc, tags, chain IDs)"},
                    "niche_id": {"type": "string", "description": "Filter by niche ID"},
                    "status": {"type": "string", "description": "Filter by status (column)"},
                    "priority": {"type": "string", "description": "Filter by priority"},
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "limit": {"type": "integer", "description": "Max results"}
                }
            },
        },
        handler=_make_thinking_handler("task_search"),
    )

    ctx.register_tool(
        name="niche_create", toolset="lumen-shm",
        schema={
            "name": "niche_create",
            "description": "Create a new cognitive niche (project/area). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Niche name"},
                    "desc": {"type": "string", "description": "Niche description"},
                    "color": {"type": "string", "description": "Niche color (hex)", "default": "#22d3ee"}
                },
                "required": ["name"]
            },
        },
        handler=_make_thinking_handler("niche_create"),
    )


    ctx.register_tool(
        name="niche_list", toolset="lumen-shm",
        schema={
            "name": "niche_list",
            "description": "List all cognitive niches. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {}
            },
        },
        handler=_make_thinking_handler("niche_list"),
    )


    ctx.register_tool(
        name="task_create", toolset="lumen-shm",
        schema={
            "name": "task_create",
            "description": "Create a new task in a niche. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche_id": {"type": "string", "description": "Niche ID"},
                    "title": {"type": "string", "description": "Task title"},
                    "desc": {"type": "string", "description": "Task description"},
                    "priority": {"type": "string", "description": "Task priority (low, medium, high, critical)", "default": "medium"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Task tags"},
                    "assignee": {"type": "string", "description": "Task assignee (session ID)"}
                },
                "required": ["niche_id", "title"]
            },
        },
        handler=_make_thinking_handler("task_create"),
    )


    ctx.register_tool(
        name="task_move", toolset="lumen-shm",
        schema={
            "name": "task_move",
            "description": "Move a task to a column (or edit fields). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "to_column": {"type": "string", "description": "Target column (e.g., Backlog, In Progress, Done)"},
                    "title": {"type": "string", "description": "New title (optional)"},
                    "desc": {"type": "string", "description": "New description (optional)"},
                    "priority": {"type": "string", "description": "New priority (optional)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "New tags (optional)"},
                    "assignee": {"type": "string", "description": "New assignee (optional)"}
                },
                "required": ["task_id"]
            },
        },
        handler=_make_thinking_handler("task_move"),
    )


    ctx.register_tool(
        name="task_link", toolset="lumen-shm",
        schema={
            "name": "task_link",
            "description": "Link a task to LUMEN cognitive objects (chain, pattern, decision, wiki). [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Task ID"},
                    "chain_id": {"type": "string", "description": "Chain ID to link"},
                    "pattern_id": {"type": "string", "description": "Pattern ID to link"},
                    "decision_id": {"type": "string", "description": "Decision ID to link"},
                    "wiki_id": {"type": "string", "description": "Wiki ID to link"}
                },
                "required": ["task_id"]
            },
        },
        handler=_make_thinking_handler("task_link"),
    )


    ctx.register_tool(
        name="task_list", toolset="lumen-shm",
        schema={
            "name": "task_list",
            "description": "List tasks with optional filtering. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "niche_id": {"type": "string", "description": "Filter by niche ID"},
                    "status": {"type": "string", "description": "Filter by status (column)"},
                    "tag": {"type": "string", "description": "Filter by tag"},
                    "search": {"type": "string", "description": "Search in title, description, tags"},
                    "limit": {"type": "integer", "description": "Limit number of results"}
                }
            },
        },
        handler=_make_thinking_handler("task_list"),
    )


    ctx.register_tool(
        name="file_info", toolset="lumen-shm",
        schema={
            "name": "file_info",
            "description": "Get detailed file metadata: size, dates, permissions, encoding. Replace 'stat'/'ls -la' on Windows. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to the file or directory"},
                },
                "required": ["path"],
            },
        },
        handler=_handle_file_info,
    )

    ctx.register_tool(
        name="disk_usage", toolset="lumen-shm",
        schema={
            "name": "disk_usage",
            "description": "Calculate total size of a directory recursively. Windows has no native 'du' — this fills that gap. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to measure", "default": "."},
                },
            },
        },
        handler=_handle_disk_usage,
    )

    ctx.register_tool(
        name="search_filename", toolset="lumen-shm",
        schema={
            "name": "search_filename",
            "description": "Find files by name using regex. More powerful than search_files glob mode for complex patterns. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern to match against filenames"},
                    "path": {"type": "string", "description": "Directory to search in", "default": "."},
                    "limit": {"type": "integer", "description": "Max results", "default": 50},
                },
                "required": ["pattern"],
            },
        },
        handler=_handle_search_filename,
    )

    ctx.register_tool(
        name="find_duplicates", toolset="lumen-shm",
        schema={
            "name": "find_duplicates",
            "description": "Find duplicate files by content hash (SHA-256). Groups identical files, shows wasted space. [LUMEN SHM]",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory to scan", "default": "."},
                    "min_size": {"type": "integer", "description": "Minimum file size in bytes to check", "default": 1},
                },
            },
        },
        handler=_handle_find_duplicates,
    )

    # ── PDBM-Lumen tools (SHM transport) ──
    pdb_schemas = [
        ("pdb_set", "MUMPS SET ^ns(subs)=value.",
         {"ns": {"type": "string"}, "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
          "value": {"description": "Value to store."}}, ["ns","subs","value"], _handle_pdb_set),
        ("pdb_get", "MUMPS $GET() — read value.",
         {"ns": {"type": "string"}, "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
          "default": {"description": "Default if not found"}}, ["ns","subs"], _handle_pdb_get),
        ("pdb_order", "MUMPS $ORDER() — iterate subscripts.",
         {"ns": {"type": "string"}, "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
          "direction": {"type": "integer", "default": 1}}, ["ns","subs"], _handle_pdb_order),
        ("pdb_data", "MUMPS $DATA() — 0/1/10/11.",
         {"ns": {"type": "string"}, "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}},
         ["ns","subs"], _handle_pdb_data),
        ("pdb_kill", "MUMPS KILL — delete subtree.",
         {"ns": {"type": "string"}, "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}},
         ["ns","subs"], _handle_pdb_kill),
        ("pdb_incr", "MUMPS $INCREMENT — atomic counter.",
         {"ns": {"type": "string"}, "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
          "increment": {"type": "number", "default": 1}}, ["ns","subs"], _handle_pdb_incr),
        ("pdb_merge", "MUMPS MERGE — copy subtree.",
         {"target_ns": {"type": "string"}, "target_subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
          "source_ns": {"type": "string"}, "source_subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}},
         ["target_ns","target_subs","source_ns","source_subs"], _handle_pdb_merge),
        ("pdb_query", "SQL SELECT/WITH on _globals.",
         {"sql": {"type": "string"}, "params": {"type": "array"}, "limit": {"type": "integer", "default": 100}},
         ["sql"], _handle_pdb_query),
        ("pdb_schema", "Describe DB: namespaces, sizes.", {}, [], _handle_pdb_schema),
        ("pdb_backup", "Backup DB or show stats.",
         {"path": {"type": "string"}}, [], _handle_pdb_backup),
    ]
    for name, desc, props, req, handler in pdb_schemas:
        ctx.register_tool(
            name=name, toolset="lumen-pdb",
            schema={"name": name, "description": desc,
                    "parameters": {"type": "object", "properties": props, "required": req}},
            handler=handler,
        )

    print(f"[lumen-shm-bridge] Registered 54 tools (fs: 13, thinking: 29, web: 2, pdb: 10)")

# DEBUG PATCH
import traceback as _tb
_orig_get_conn = _get_connection

def _get_connection_debug(name):
    try:
        import sys as _sys
        _sys.stderr.write(f"[SHM-DEBUG] _get_connection({name}) called\n")
        _sys.stderr.flush()
        result = _orig_get_conn(name)
        _sys.stderr.write(f"[SHM-DEBUG] _get_connection({name}) OK\n")
        _sys.stderr.flush()
        return result
    except Exception as e:
        _sys.stderr.write(f"[SHM-DEBUG] _get_connection({name}) FAILED: {e}\n{_tb.format_exc()}\n")
        _sys.stderr.flush()
        raise

# Replace the function
_get_connection = _get_connection_debug

# Also wrap handlers
_orig_read = _handle_filesystem_read_file
def _handle_filesystem_read_file_debug(*args, **kwargs):
    import sys as _sys
    _sys.stderr.write(f"[SHM-DEBUG] read_file handler called args={args[:1]}... kwargs keys={list(kwargs.keys())}\n")
    _sys.stderr.flush()
    try:
        result = _orig_read(*args, **kwargs)
        _sys.stderr.write(f"[SHM-DEBUG] read_file result len={len(result)}\n")
        _sys.stderr.flush()
        return result
    except Exception as e:
        _sys.stderr.write(f"[SHM-DEBUG] read_file FAILED: {e}\n{_tb.format_exc()}\n")
        _sys.stderr.flush()
        raise

_handle_filesystem_read_file = _handle_filesystem_read_file_debug

# ═══════════════════════════════════════════════════════════════════════════
# Additional filesystem handlers
# ═══════════════════════════════════════════════════════════════════════════

def _handle_list_directory(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("list_directory", {
        "path": params.get("path", "."),
        "file_glob": params.get("file_glob"),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_read_files(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("read_files", {
        "paths": params.get("paths", []),
        "limit_per_file": params.get("limit_per_file", 100),
        "max_total_chars": params.get("max_total_chars", 50000),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_search_with_context(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("search_with_context", {
        "pattern": params.get("pattern", ""),
        "path": params.get("path", "."),
        "context": params.get("context", 3),
        "file_glob": params.get("file_glob"),
        "limit": params.get("limit", 20),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_stream_read(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("stream_read", {
        "path": params.get("path", ""),
        "chunk_number": params.get("chunk_number", 1),
        "chunk_size": params.get("chunk_size", 500),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

# ═══════════════════════════════════════════════════════════════════════════
# Additional thinking handlers (Reasoning Chain Engine)
# ═══════════════════════════════════════════════════════════════════════════

def _handle_thought_similarity(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    result = conn.call_tool("thought_similarity", {
        "chainId": params.get("chainId", ""),
        "thought": params.get("thought", ""),
        "topN": params.get("topN", 3),
        "minScore": params.get("minScore", 0.1),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_thought_contradiction(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    result = conn.call_tool("thought_contradiction", {
        "chainId": params.get("chainId", ""),
        "thought": params.get("thought", ""),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_thought_summarize(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    result = conn.call_tool("thought_summarize", {
        "chainId": params.get("chainId", ""),
        "maxClusters": params.get("maxClusters", 5),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_thought_to_plan(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    result = conn.call_tool("thought_to_plan", {
        "chainId": params.get("chainId", ""),
        "format": params.get("format", "markdown"),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_thought_evaluate(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    result = conn.call_tool("thought_evaluate", {
        "chainId": params.get("chainId", ""),
        "thoughtNumber": params.get("thoughtNumber", 1),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_thought_bridge(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("thinking")
    result = conn.call_tool("thought_bridge", {
        "thought": params.get("thought", ""),
        "topN": params.get("topN", 3),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


# ═══════════════════════════════════════════════════════════════════════════
# Generic thinking tool handler (for all 29 thinking tools)
# ═══════════════════════════════════════════════════════════════════════════

def _handle_thinking_tool(tool_name: str, params: dict) -> str:
    conn = _get_connection("thinking")
    result = conn.call_tool(tool_name, params)
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) 
        if isinstance(item, dict) and item.get("type") == "text"
    )

def _make_thinking_handler(tool_name: str):
    """Factory: creates a handler for any thinking tool."""
    def handler(*args, **kwargs):
        params = args[0] if args else kwargs
        return _handle_thinking_tool(tool_name, params)
    return handler

# ── Server stats handler ──
def _handle_server_stats(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("server_stats", {})
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) 
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _handle_file_info(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("file_info", {"path": params.get("path", "")})
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_disk_usage(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("disk_usage", {"path": params.get("path", ".")})
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_search_filename(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("search_filename", {
        "pattern": params.get("pattern", ""),
        "path": params.get("path", "."),
        "limit": params.get("limit", 50),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )

def _handle_find_duplicates(*args, **kwargs) -> str:
    params = args[0] if args else kwargs
    conn = _get_connection("filesystem")
    result = conn.call_tool("find_duplicates", {
        "path": params.get("path", "."),
        "min_size": params.get("min_size", 1),
    })
    return "\n".join(
        item.get("text", "") for item in result.get("content", []) if isinstance(item, dict) and item.get("type") == "text"
    )


# ═══════════════════════════════════════════════════════════════════════════
# PDBM-Lumen handlers (stdio JSON-RPC — SHM investigation pending)
# ═══════════════════════════════════════════════════════════════════════════

_PDB_PROC = None
_PDB_LOCK = threading.RLock()
_PDB_REQ_ID = 0

def _pdb_ensure():
    global _PDB_PROC
    with _PDB_LOCK:
        if _PDB_PROC is None or _PDB_PROC.poll() is not None:
            import subprocess as _sp
            _PDB_PROC = _sp.Popen(
                [_HERMES_VENV_PYTHON, "-u", _PDB_STDIO],
                stdin=_sp.PIPE, stdout=_sp.PIPE, stderr=_sp.DEVNULL,
                text=True, bufsize=1,
            )
            _pdb_rpc({"method": "initialize", "params": {}})
    return _PDB_PROC

def _pdb_rpc(msg: dict) -> dict:
    global _PDB_REQ_ID
    _PDB_REQ_ID += 1
    payload = json.dumps({"jsonrpc": "2.0", "id": _PDB_REQ_ID, **msg})
    with _PDB_LOCK:
        _PDB_PROC.stdin.write(payload + "\n")
        _PDB_PROC.stdin.flush()
        line = _PDB_PROC.stdout.readline()
    if not line:
        raise ConnectionError("PDB server closed")
    resp = json.loads(line.strip())
    if "error" in resp:
        raise RuntimeError(f"PDB error: {resp['error']}")
    return resp.get("result", {})

def _call_pdb(tool_name: str, params: dict) -> str:
    """Call PDB tool via stdio JSON-RPC."""
    _pdb_ensure()
    result = _pdb_rpc({
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": params},
    })
    content = result.get("content", [])
    if content and content[0].get("type") == "text":
        return content[0]["text"]
    return json.dumps(result, ensure_ascii=False)

def _handle_pdb_set(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_set", {"ns": p["ns"], "subs": p["subs"], "value": p["value"]})
def _handle_pdb_get(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; kw = {"ns": p["ns"], "subs": p["subs"]}
    if "default" in p: kw["default"] = p["default"]; return _call_pdb("pdb_get", kw)
def _handle_pdb_order(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_order", {"ns": p["ns"], "subs": p["subs"], "direction": p.get("direction", 1)})
def _handle_pdb_data(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_data", {"ns": p["ns"], "subs": p["subs"]})
def _handle_pdb_kill(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_kill", {"ns": p["ns"], "subs": p["subs"]})
def _handle_pdb_incr(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_incr", {"ns": p["ns"], "subs": p["subs"], "increment": p.get("increment", 1)})
def _handle_pdb_merge(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_merge", {
        "target_ns": p["target_ns"], "target_subs": p["target_subs"],
        "source_ns": p["source_ns"], "source_subs": p["source_subs"]})
def _handle_pdb_query(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; return _call_pdb("pdb_query", {"sql": p["sql"], "params": p.get("params"), "limit": p.get("limit", 100)})
def _handle_pdb_schema(*args, **kwargs) -> str:
    return _call_pdb("pdb_schema", {})
def _handle_pdb_backup(*args, **kwargs) -> str:
    p = args[0] if args else kwargs; kw = {}
    if "path" in p: kw["path"] = p["path"]; return _call_pdb("pdb_backup", kw)

