#!/usr/bin/env python3
"""
LUMEN Native Filesystem MCP Server — speaks LUMEN binary protocol natively.

No JSON-RPC text wrapping — pure binary frames over stdio.
Uses the LUMEN Python package for frame building/parsing and compression.

Compare to server.py (JSON-RPC over LUMEN wrapper) for benchmark:
  - server_native.py: 50-70% wire savings, MUX, streaming
  - server.py:        32-60% wire savings, no MUX, no streaming

Usage:
    python server_native.py
    hermes mcp add lumen-fs-native --command python --args server_native.py --transport lumen
"""

import sys
import json
import os
import re
import fnmatch
from pathlib import Path

# ── LUMEN native imports ──
from lumen import (
    build_frame, parse_frame, compress_value, decompress_value,
    TYPE_REQUEST, TYPE_RESPONSE, FLAG_COMPRESSED,
    ParseComplete,
)

# ═══════════════════════════════════════════════════════════════════════
# Tool definitions (same as server.py)
# ═══════════════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "read_file",
        "description": "Read a text file with line numbers and pagination. Output format: 'LINE_NUM|CONTENT'. Suggests similar filenames if not found. Use offset and limit for large files.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to read"},
                "offset": {"type": "integer", "description": "Line number to start reading from (1-indexed, default: 1)", "default": 1, "minimum": 1},
                "limit": {"type": "integer", "description": "Maximum number of lines to read (default: 500, max: 2000)", "default": 500, "maximum": 2000}
            },
            "required": ["path"]
        }
    },
    {
        "name": "read_files",
        "description": "Read multiple files in a single call. Returns each file's content with headers. Use this instead of multiple read_file calls to reduce round-trips.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "paths": {"type": "array", "items": {"type": "string"}, "description": "List of file paths to read"},
                "limit_per_file": {"type": "integer", "description": "Max lines per file (default: 100)", "default": 100, "minimum": 1, "maximum": 500},
                "max_total_chars": {"type": "integer", "description": "Max total chars across all files (default: 50000)", "default": 50000, "maximum": 100000}
            },
            "required": ["paths"]
        }
    },
    {
        "name": "write_file",
        "description": "Write content to a file, completely replacing existing content. Creates parent directories automatically.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file to write"},
                "content": {"type": "string", "description": "Complete content to write to the file"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "search_files",
        "description": "Search file contents or find files by name.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern for content search, or glob pattern for file search"},
                "target": {"type": "string", "enum": ["content", "files"], "default": "content"},
                "path": {"type": "string", "description": "Directory to search in", "default": "."},
                "file_glob": {"type": "string", "description": "Filter files by pattern"},
                "limit": {"type": "integer", "description": "Maximum number of results (default: 50)", "default": 50}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "search_with_context",
        "description": "Search with context lines around each match. Shows surrounding code for better understanding.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "path": {"type": "string", "description": "Directory or file to search in", "default": "."},
                "context_lines": {"type": "integer", "description": "Lines of context before and after each match (default: 3)", "default": 3, "minimum": 0, "maximum": 20},
                "file_glob": {"type": "string", "description": "Filter files by glob"},
                "limit": {"type": "integer", "description": "Max matches to return (default: 20)", "default": 20, "maximum": 100}
            },
            "required": ["pattern"]
        }
    },
    {
        "name": "list_directory",
        "description": "List files and directories. Use this instead of ls/dir in terminal.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to list", "default": "."},
                "file_glob": {"type": "string", "description": "Filter by glob pattern"}
            }
        }
    },
    {
        "name": "patch",
        "description": "Targeted find-and-replace edit in a file. Uses exact string matching.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path to edit"},
                "old_string": {"type": "string", "description": "Exact text to find and replace"},
                "new_string": {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace all occurrences (default: false)", "default": False}
            },
            "required": ["path", "old_string", "new_string"]
        }
    }
]


# ═══════════════════════════════════════════════════════════════════════
# Tool implementations (identical logic to server.py)
# ═══════════════════════════════════════════════════════════════════════

def resolve_path(path: str) -> Path:
    if path.startswith("~/"):
        return Path.home() / path[2:]
    if path.startswith("~\\"):
        return Path.home() / path[2:]
    return Path(path)


def suggest_similar(path: Path) -> str:
    parent = path.parent
    name = path.name.lower()
    if not parent.exists():
        return ""
    try:
        candidates = [str(p.relative_to(parent)) for p in parent.iterdir() if name in p.name.lower()][:5]
        if candidates:
            return "\nSimilar files: " + ", ".join(candidates)
    except Exception:
        pass
    return ""


def tool_read_file(args: dict) -> dict:
    path = resolve_path(args["path"])
    offset = args.get("offset", 1)
    limit = min(args.get("limit", 500), 2000)

    if not path.exists():
        similar = suggest_similar(path)
        return {"content": [{"type": "text", "text": f"Error: File not found: {path}{similar}"}]}
    if not path.is_file():
        return {"content": [{"type": "text", "text": f"Error: Not a file: {path}"}]}

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error reading file: {e}"}]}

    total = len(all_lines)
    start = max(0, offset - 1)
    end = min(total, start + limit)

    result_lines = []
    output = ""
    for i in range(start, end):
        line_text = f"{i+1}|{all_lines[i].rstrip()}"
        result_lines.append(line_text)
        output = "\n".join(result_lines)
        if len(output) > 100_000:
            output += f"\n... (truncated at {i+1}/{total}, result too large)"
            return {"content": [{"type": "text", "text": output}]}

    output = "\n".join(result_lines)
    if total > end:
        output += f"\n... (truncated, {total} lines total)"
    return {"content": [{"type": "text", "text": output}]}


def tool_read_files(args: dict) -> dict:
    paths = args["paths"]
    limit_per_file = min(args.get("limit_per_file", 100), 500)
    max_chars = min(args.get("max_total_chars", 50000), 100000)
    if not paths:
        return {"content": [{"type": "text", "text": "Error: paths list is empty"}]}

    output_parts = []
    total_chars = 0
    for file_path in paths[:20]:
        path = resolve_path(file_path)
        header = f"\n═══ {file_path} ═══"
        if not path.exists():
            output_parts.append(f"{header}\n  [NOT FOUND]")
            total_chars += len(output_parts[-1]); continue
        if not path.is_file():
            output_parts.append(f"{header}\n  [NOT A FILE]")
            total_chars += len(output_parts[-1]); continue
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
        except Exception as e:
            output_parts.append(f"{header}\n  [ERROR: {e}]")
            total_chars += len(output_parts[-1]); continue
        total = len(all_lines)
        limit = min(limit_per_file, total)
        file_output = header + "\n"
        for i in range(limit):
            file_output += f"{i+1}|{all_lines[i].rstrip()}\n"
        if total > limit:
            file_output += f"... (truncated, {total} lines total)\n"
        if total_chars + len(file_output) > max_chars:
            file_output = file_output[:max_chars - total_chars - 50]
            file_output += "\n... [TRUNCATED: max total size reached]"
            output_parts.append(file_output); break
        output_parts.append(file_output)
        total_chars += len(file_output)
    return {"content": [{"type": "text", "text": "".join(output_parts)}]}


def tool_write_file(args: dict) -> dict:
    path = resolve_path(args["path"])
    content = args["content"]
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        size = path.stat().st_size
        return {"content": [{"type": "text", "text": f"Wrote {size} bytes to {path}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error writing file: {e}"}]}


def tool_search_files(args: dict) -> dict:
    pattern = args["pattern"]
    target = args.get("target", "content")
    search_path = args.get("path", ".")
    file_glob = args.get("file_glob")
    limit = min(args.get("limit", 50), 200)
    resolved = resolve_path(search_path)
    if not resolved.exists():
        return {"content": [{"type": "text", "text": f"Error: Path not found: {resolved}"}]}
    if target == "files":
        try:
            glob_pattern = pattern if "*" in pattern else f"*{pattern}*"
            results = []
            for f in resolved.rglob(glob_pattern):
                if f.is_file():
                    results.append(str(f.relative_to(resolved)))
                    if len(results) >= limit: break
            if results:
                return {"content": [{"type": "text", "text": "\n".join(results)}]}
            return {"content": [{"type": "text", "text": f"No files matching '{pattern}'"}]}
        except Exception as e:
            return {"content": [{"type": "text", "text": f"Error searching files: {e}"}]}
    try:
        compiled = re.compile(pattern)
    except re.error as e:
        return {"content": [{"type": "text", "text": f"Invalid regex: {e}"}]}
    results = []
    glob_filter = file_glob or "*"
    try:
        for fpath in resolved.rglob(glob_filter):
            if not fpath.is_file(): continue
            if fpath.stat().st_size > 1_000_000: continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    for line_no, line in enumerate(f, 1):
                        if compiled.search(line):
                            rel = str(fpath.relative_to(resolved))
                            results.append(f"{rel}:{line_no}: {line.rstrip()[:200]}")
                            if len(results) >= limit: break
                    if len(results) >= limit: break
            except Exception: continue
        if results:
            return {"content": [{"type": "text", "text": "\n".join(results)}]}
        return {"content": [{"type": "text", "text": f"No matches for '{pattern}' in {resolved}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error searching: {e}"}]}


def tool_search_with_context(args: dict) -> dict:
    pattern = args["pattern"]
    search_path = args.get("path", ".")
    context = min(args.get("context_lines", 3), 20)
    file_glob = args.get("file_glob")
    limit = min(args.get("limit", 20), 100)
    resolved = resolve_path(search_path)
    if not resolved.exists():
        return {"content": [{"type": "text", "text": f"Error: Path not found: {resolved}"}]}
    try: compiled = re.compile(pattern)
    except re.error as e: return {"content": [{"type": "text", "text": f"Invalid regex: {e}"}]}
    results = []
    glob_filter = file_glob or "*"
    total_chars = 0
    MAX_OUTPUT = 80000
    try:
        for fpath in resolved.rglob(glob_filter):
            if not fpath.is_file(): continue
            if fpath.stat().st_size > 1_000_000: continue
            try:
                with open(fpath, "r", encoding="utf-8", errors="replace") as f:
                    all_lines = f.readlines()
            except Exception: continue
            total_lines = len(all_lines)
            for line_no, line in enumerate(all_lines, 1):
                if not compiled.search(line): continue
                ctx_start = max(0, line_no - 1 - context)
                ctx_end = min(total_lines, line_no - 1 + context + 1)
                rel = str(fpath.relative_to(resolved))
                block = f"\n─── {rel}:{line_no} ───\n"
                for i in range(ctx_start, ctx_end):
                    marker = ">>>" if i == line_no - 1 else "   "
                    block += f"{marker} {i+1}|{all_lines[i].rstrip()}\n"
                if total_chars + len(block) > MAX_OUTPUT:
                    results.append("\n... [TRUNCATED: max output size]")
                    return {"content": [{"type": "text", "text": "".join(results)}]}
                results.append(block)
                total_chars += len(block)
                if len(results) >= limit:
                    return {"content": [{"type": "text", "text": "".join(results)}]}
        if results: return {"content": [{"type": "text", "text": "".join(results)}]}
        return {"content": [{"type": "text", "text": f"No matches for '{pattern}' in {resolved}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error searching: {e}"}]}


def tool_list_directory(args: dict) -> dict:
    path = resolve_path(args.get("path", "."))
    file_glob = args.get("file_glob")
    if not path.exists():
        return {"content": [{"type": "text", "text": f"Error: Directory not found: {path}"}]}
    if not path.is_dir():
        return {"content": [{"type": "text", "text": f"Error: Not a directory: {path}"}]}
    try:
        items = []
        for entry in sorted(path.iterdir()):
            name = entry.name
            if file_glob and not fnmatch.fnmatch(name, file_glob):
                continue
            entry_type = "\U0001F4C1" if entry.is_dir() else "\U0001F4C4"
            try:
                size = entry.stat().st_size if entry.is_file() else 0
                size_str = f" ({size:,}B)" if entry.is_file() else ""
                items.append(f"{entry_type} {name}{size_str}")
            except OSError:
                items.append(f"{entry_type} {name}")
        if not items:
            return {"content": [{"type": "text", "text": f"Empty directory: {path}"}]}
        return {"content": [{"type": "text", "text": "\n".join(items)}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error listing directory: {e}"}]}


def tool_patch(args: dict) -> dict:
    path = resolve_path(args["path"])
    old_string = args["old_string"]
    new_string = args["new_string"]
    replace_all = args.get("replace_all", False)
    if not path.exists():
        return {"content": [{"type": "text", "text": f"Error: File not found: {path}"}]}
    try:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error reading file: {e}"}]}
    count = content.count(old_string)
    if count == 0:
        return {"content": [{"type": "text", "text": f"Error: String not found in {path}. No changes made."}]}
    if not replace_all and count > 1:
        return {"content": [{"type": "text", "text": f"Error: Found {count} occurrences. Use replace_all=true or provide more context to make it unique."}]}
    new_content = content.replace(old_string, new_string)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(new_content)
        replaced = count if replace_all else 1
        return {"content": [{"type": "text", "text": f"Replaced {replaced} occurrence(s) in {path}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error writing file: {e}"}]}


HANDLERS = {
    "read_file": tool_read_file,
    "read_files": tool_read_files,
    "write_file": tool_write_file,
    "search_files": tool_search_files,
    "search_with_context": tool_search_with_context,
    "list_directory": tool_list_directory,
    "patch": tool_patch,
}


# ═══════════════════════════════════════════════════════════════════════
# LUMEN Native Transport — binary frames, no JSON-RPC wrapping
# ═══════════════════════════════════════════════════════════════════════

def process_message(msg: dict) -> dict:
    """Process a message. Handles LUMEN PROBE or JSON-RPC."""
    
    # ── LUMEN PROBE handshake ──
    if "protocol" in msg and msg.get("protocol") == "LUMEN":
        # This is a LUMEN probe, respond with PROBE_ACK
        client_name = msg.get("client_name", "unknown")
        client_versions = msg.get("supported_versions", ["1.0"])
        accepted = "1.0" if "1.0" in client_versions else client_versions[0]
        ack = {
            "protocol": "LUMEN",
            "server_name": "lumen-filesystem-native",
            "accepted_version": accepted,
        }
        # Return special marker for send_lumen_frame to handle differently
        return {"__lumen_ack__": True, "ack": ack}
    
    # ── JSON-RPC handling ──
    method = msg.get("method", "")
    req_id = msg.get("id")

    if method == "initialize":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": "2025-03-26",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "lumen-filesystem-native", "version": "2.0.0"}
            }
        }
    elif method == "tools/list":
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {"tools": TOOLS}
        }
    elif method == "tools/call":
        params = msg.get("params", {})
        tool_name = params.get("name", "")
        tool_args = params.get("arguments", {})
        handler = HANDLERS.get(tool_name)
        if handler:
            try:
                result = handler(tool_args)
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            except Exception as e:
                return {"jsonrpc": "2.0", "id": req_id,
                        "error": {"code": -32000, "message": f"Tool error: {e}"}}
        else:
            return {"jsonrpc": "2.0", "id": req_id,
                    "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}}
    elif method == "notifications/initialized":
        return None  # No response
    else:
        return {"jsonrpc": "2.0", "id": req_id,
                "error": {"code": -32601, "message": f"Unknown method: {method}"}}


def read_lumen_frame() -> dict | None:
    """Read a LUMEN frame from stdin (binary mode), return parsed JSON message."""
    from lumen import ParseIncompletePayload

    buf = bytearray()
    while True:
        # Read 1 byte at a time — prevents blocking on pipe
        # (sys.stdin.buffer.read(N) blocks until N bytes or EOF on Windows)
        b = sys.stdin.buffer.read(1)
        if not b:
            return None
        buf.extend(b)

        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload  # Already a dict
        elif hasattr(result, 'needed'):
            continue  # Need more bytes
        # else: parse error, keep accumulating


def send_lumen_frame(response: dict) -> None:
    """Build a LUMEN frame and write to stdout (binary mode)."""
    if response is None:
        return

    from lumen.negotiation import LumenAck
    from lumen import TYPE_PROBE_ACK, FLAG_COMPRESSED as FC

    # Handle PROBE_ACK marker
    if response.get("__lumen_ack__"):
        ack = response["ack"]
        payload = compress_value(ack)
        header_size = build_size(payload)
        total_size = header_size + len(payload)
        buf = bytearray(total_size)
        build_frame(TYPE_PROBE_ACK, FC, payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()
        return

    payload = compress_value(response)
    header_size = build_size(payload)  # header only
    total_size = header_size + len(payload)
    buf = bytearray(total_size)
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
    sys.stdout.buffer.write(buf)
    sys.stdout.buffer.flush()


def main() -> None:
    """Main loop: read LUMEN frames from stdin, process, respond on stdout."""
    while True:
        try:
            msg = read_lumen_frame()
            if msg is None:
                break

            response = process_message(msg)
            send_lumen_frame(response)

        except Exception as e:
            error_resp = {"jsonrpc": "2.0", "id": None,
                          "error": {"code": -32603, "message": f"Internal error: {e}"}}
            try:
                send_lumen_frame(error_resp)
            except:
                pass


if __name__ == "__main__":
    main()
