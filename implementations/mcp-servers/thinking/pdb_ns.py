"""
LUMEN PDB Namespace Tools — custom namespace read/write with plain text keys.

Unlike the standalone pdb_set/pdb_get (MUMPS-encoded), these tools use
plain .encode() keys compatible with the thinking server's STATE namespace.
They share the same _globals table, same lock, same database.

Key format: plain text string, e.g. "contacts:1", "health:mood:2026-07-04"
"""

import json
import time
from typing import Any


def pdb_ns_tool_set(args: dict) -> dict:
    """Write to a custom PDB namespace with plain text key."""
    import server
    ns = args.get("ns", "").strip()
    key = args.get("key", "").strip()
    value = args.get("value")
    if not ns or not key:
        return {"content": [{"type": "text", "text": "Error: 'ns' and 'key' required."}]}
    if value is None:
        return {"content": [{"type": "text", "text": "Error: 'value' required. Use pdb_ns_kill to delete."}]}
    # Serialize: if value is a dict/list, dump to JSON
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False)
    elif not isinstance(value, str):
        value = str(value)
    server._pdb_save_lock.acquire()
    try:
        import sqlite3
        conn = sqlite3.connect(str(server._PDB_PATH))
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            (ns, key.encode(), value.encode())
        )
        conn.commit()
        conn.close()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error writing to PDB: {e}"}]}
    finally:
        server._pdb_save_lock.release()
    preview = value[:60] + "..." if len(value) > 60 else value
    return {"content": [{"type": "text", "text": f"✅ pdb_ns_set: {ns}:{key} = {preview}"}]}


def pdb_ns_tool_get(args: dict) -> dict:
    """Read from a custom PDB namespace by plain text key."""
    import server
    ns = args.get("ns", "").strip()
    key = args.get("key", "").strip()
    if not ns or not key:
        return {"content": [{"type": "text", "text": "Error: 'ns' and 'key' required."}]}
    try:
        import sqlite3
        conn = sqlite3.connect(str(server._PDB_PATH))
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?",
            (ns, key.encode())
        ).fetchone()
        conn.close()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error reading PDB: {e}"}]}
    if not row:
        return {"content": [{"type": "text", "text": f"(none) — {ns}:{key} not found"}]}
    value = row["value"]
    # Try to decode as JSON for pretty display
    try:
        parsed = json.loads(value)
        return {"content": [{"type": "text", "text": json.dumps(parsed, indent=2, ensure_ascii=False)}]}
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {"content": [{"type": "text", "text": value}]}


def pdb_ns_tool_kill(args: dict) -> dict:
    """Delete a key from a custom PDB namespace."""
    import server
    ns = args.get("ns", "").strip()
    key = args.get("key", "").strip()
    if not ns or not key:
        return {"content": [{"type": "text", "text": "Error: 'ns' and 'key' required."}]}
    try:
        import sqlite3
        conn = sqlite3.connect(str(server._PDB_PATH))
        cursor = conn.execute(
            "DELETE FROM _globals WHERE ns=? AND subkey=?",
            (ns, key.encode())
        )
        deleted = cursor.rowcount
        conn.commit()
        conn.close()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}]}
    if deleted:
        return {"content": [{"type": "text", "text": f"🗑️ Deleted {ns}:{key}"}]}
    return {"content": [{"type": "text", "text": f"(none) — {ns}:{key} not found"}]}


def pdb_ns_tool_order(args: dict) -> dict:
    """Iterate keys in a namespace by prefix (like MUMPS $ORDER)."""
    import server
    ns = args.get("ns", "").strip()
    prefix = args.get("prefix", "")
    limit = min(args.get("limit", 20), 100)
    try:
        import sqlite3
        conn = sqlite3.connect(str(server._PDB_PATH))
        conn.row_factory = sqlite3.Row
        if prefix:
            # Use LIKE with prefix — SQLite can use index for prefix queries
            rows = conn.execute(
                "SELECT subkey FROM _globals WHERE ns=? AND subkey LIKE ? ORDER BY subkey LIMIT ?",
                (ns, (prefix + "%").encode(), limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT subkey FROM _globals WHERE ns=? ORDER BY subkey LIMIT ?",
                (ns, limit)
            ).fetchall()
        conn.close()
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Error: {e}"}]}
    if not rows:
        return {"content": [{"type": "text", "text": f"(empty) - no keys in {ns}" + (f" with prefix '{prefix}'" if prefix else "")}]}
    keys = [r["subkey"].decode() if isinstance(r["subkey"], bytes) else r["subkey"] for r in rows]
    lines = [f"📂 {ns} ({len(keys)} keys):"]
    for k in keys:
        lines.append(f"  • {k}")
    if len(rows) == limit:
        lines.append(f"  ... (showing first {limit})")
    return {"content": [{"type": "text", "text": "\n".join(lines)}]}


# ── Handler and Schema exports (same pattern as kanban.py) ──

PDB_NS_HANDLERS = {
    "pdb_ns_set": pdb_ns_tool_set,
    "pdb_ns_get": pdb_ns_tool_get,
    "pdb_ns_kill": pdb_ns_tool_kill,
    "pdb_ns_order": pdb_ns_tool_order,
}

PDB_NS_SCHEMAS = [
    {
        "name": "pdb_ns_set",
        "description": "Write to a custom PDB namespace with plain text key. Unlike pdb_set (MUMPS-encoded), this uses plain .encode() — compatible with the thinking server. Keys are readable strings like 'contacts:1' or 'health:mood:2026-07-04'. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace name (e.g. 'personal', 'projects')"},
                "key": {"type": "string", "description": "Plain text key (e.g. 'contacts:1', 'health:mood:2026-07-04')"},
                "value": {"description": "Value to store (string, number, or JSON object/array)"}
            },
            "required": ["ns", "key", "value"]
        }
    },
    {
        "name": "pdb_ns_get",
        "description": "Read from a custom PDB namespace by plain text key. Returns JSON-parsed if possible, raw string otherwise. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace name"},
                "key": {"type": "string", "description": "Plain text key"}
            },
            "required": ["ns", "key"]
        }
    },
    {
        "name": "pdb_ns_kill",
        "description": "Delete a key from a custom PDB namespace. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace name"},
                "key": {"type": "string", "description": "Plain text key to delete"}
            },
            "required": ["ns", "key"]
        }
    },
    {
        "name": "pdb_ns_order",
        "description": "List keys in a namespace, optionally filtered by prefix. Like MUMPS $ORDER() but for plain text keys. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace name"},
                "prefix": {"type": "string", "description": "Optional key prefix filter (e.g. 'contacts:' lists all contacts)"},
                "limit": {"type": "integer", "description": "Max keys to return", "default": 20}
            },
            "required": ["ns"]
        }
    },
]
