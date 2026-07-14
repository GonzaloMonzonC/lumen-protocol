#!/usr/bin/env python3
"""
file_tools.py — File snapshot & diff tools for LLM agents.

Stores file snapshots in PDB (^FILE_SNAPSHOTS namespace).
Provides tools: file_snapshot, file_diff, file_snapshots_list.

PDB schema:
  ns='FILE_SNAPSHOTS'
  subkey=f'{normalized_path}:v{version}'
  value=json.dumps({'path': path, 'content': content, 'timestamp': ts, 'version': v, 'size': len(content)})
"""

import json
import os
import sqlite3
import time
import difflib
from pathlib import Path
from typing import Optional

import _pdb

HERE = Path(__file__).parent
_PDB_PATH = Path(_pdb.PDB_PATH)
MAX_VERSIONS = 5


def _normalize_path(path: str) -> str:
    p = Path(path).resolve()
    return p.as_posix()


def _get_pdb_connection():
    return _pdb.pdb_connect()


def _all_versions(path: str) -> list[dict]:
    npath = _normalize_path(path)
    conn = _get_pdb_connection()
    try:
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? AND subkey LIKE ? ORDER BY subkey DESC",
            ('FILE_SNAPSHOTS', f'{npath}:v%'.encode())
        ).fetchall()
        result = []
        for subkey, val_bytes in rows:
            try:
                data = json.loads(val_bytes.decode())
                result.append(data)
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
        return result
    finally:
        conn.close()


def tool_file_snapshot(path: str) -> dict:
    npath = _normalize_path(path)
    try:
        with open(npath, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return {"content": [{"type": "text", "text": f"File not found: {path}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error reading {path}: {e}"}]}
    versions = _all_versions(path)
    next_version = (versions[0]['version'] + 1) if versions else 1
    conn = _get_pdb_connection()
    try:
        existing = conn.execute(
            "SELECT subkey FROM _globals WHERE ns=? AND subkey LIKE ?",
            ('FILE_SNAPSHOTS', f'{npath}:v%'.encode())
        ).fetchall()
        if len(existing) >= MAX_VERSIONS:
            oldest = sorted(existing, key=lambda r: r[0])[0]
            conn.execute("DELETE FROM _globals WHERE ns=? AND subkey=?",
                        ('FILE_SNAPSHOTS', oldest[0]))
        val = json.dumps({
            'path': npath, 'content': content, 'timestamp': time.time(),
            'version': next_version, 'size': len(content), 'lines': content.count('\n') + 1
        }).encode()
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            ('FILE_SNAPSHOTS', f'{npath}:v{next_version}'.encode(), val)
        )
        conn.commit()
    finally:
        conn.close()
    return {"content": [{"type": "text", "text": f"Snapshot saved: {npath} (v{next_version}, {len(content)} bytes, {content.count(chr(10))+1} lines)"}]}


def tool_file_diff(path: str, version: Optional[int] = None) -> dict:
    npath = _normalize_path(path)
    try:
        with open(npath, 'r', encoding='utf-8') as f:
            current = f.read()
    except FileNotFoundError:
        return {"content": [{"type": "text", "text": f"File not found: {path}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error reading {path}: {e}"}]}
    versions = _all_versions(path)
    if not versions:
        return {"content": [{"type": "text", "text": f"No snapshots for {path}. Use file_snapshot first."}]}
    if version is not None:
        snapshots = [v for v in versions if v['version'] == version]
        if not snapshots:
            return {"content": [{"type": "text", "text": f"Version {version} not found for {path}. Available: {[v['version'] for v in versions]}"}]}
        snapshot = snapshots[0]
    else:
        snapshot = versions[0]
    old_content = snapshot['content']
    if old_content == current:
        return {"content": [{"type": "text", "text": f"No changes: {npath} (v{snapshot['version']} matches current)"}]}
    old_lines = old_content.splitlines(True)
    new_lines = current.splitlines(True)
    diff_lines = [f"--- {npath} (v{snapshot['version']})", f"+++ {npath} (current)"]
    diff = list(difflib.unified_diff(old_lines, new_lines, n=3))
    if not diff:
        diff_lines.append("(only whitespace changes)")
    else:
        actual_diff = diff[2:] if len(diff) > 2 else diff
        diff_lines.extend(actual_diff)
    added = sum(1 for l in diff_lines if l.startswith('+') and not l.startswith('+++'))
    removed = sum(1 for l in diff_lines if l.startswith('-') and not l.startswith('---'))
    result = "\n".join(diff_lines)
    if len(result) > 5000:
        result = result[:5000] + f"\n... (truncated, {len(result)} total chars)"
    return {"content": [{"type": "text", "text": f"Diff: {npath} (v{snapshot['version']} -> current)\n{added} additions, {removed} removals, {len(old_lines)}->{len(new_lines)} lines\n\n{result}"}]}


def tool_file_snapshots_list(path: str) -> dict:
    versions = _all_versions(path)
    if not versions:
        return {"content": [{"type": "text", "text": f"No snapshots for: {_normalize_path(path)}"}]}
    lines = [f"Snapshots for {_normalize_path(path)}:"]
    for v in versions:
        ts = time.strftime('%H:%M:%S', time.localtime(v['timestamp']))
        lines.append(f"  v{v['version']} | {ts} | {v['size']} bytes | {v['lines']} lines")
    lines.append(f"  Total: {len(versions)} versions (max {MAX_VERSIONS})")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


FILE_TOOL_SCHEMAS = [
    {
        "name": "file_snapshot",
        "description": "Save current file content to PDB as versioned snapshot. Call before editing so file_diff works.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "file_diff",
        "description": "Show unified diff between current file and stored snapshot. Without version: compares against latest.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"},
                "version": {"type": "integer", "description": "Optional snapshot version"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "file_snapshots_list",
        "description": "List all stored snapshots for a file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path to the file"}
            },
            "required": ["path"]
        }
    }
]

FILE_TOOL_HANDLERS = {
    "file_snapshot": tool_file_snapshot,
    "file_diff": tool_file_diff,
    "file_snapshots_list": tool_file_snapshots_list,
}
