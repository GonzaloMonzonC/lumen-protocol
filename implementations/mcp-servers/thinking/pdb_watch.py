#!/usr/bin/env python3
"""
pdb_watch.py — PDB Watch & Notification tools for LLM agents.

Polling-based change detection: registers interest in PDB namespaces,
then compares current state against stored snapshots to detect
insets/updates/deletes between checks.

PDB schema:
  WATCHED_KEYS:  ns='WATCHED_KEYS', subkey=f'{watch_id}' → json of {ns, pattern, created_at}
  WATCH_SNAPSHOTS: ns='WATCH_SNAPSHOTS', subkey=f'{watch_id}:{subkey}' → json of value
  AGENT_NOTIFICATIONS: ns='AGENT_NOTIFICATIONS', subkey=f'{watch_id}:{subkey}:{timestamp}' → json
"""

import json
import sqlite3
import time
import re
from pathlib import Path

import _pdb

HERE = Path(__file__).parent
_PDB_PATH = Path(_pdb.PDB_PATH)


def _get_conn():
    return _pdb.pdb_connect()


def _encode(val):
    return val.encode() if isinstance(val, str) else val


def tool_pdb_watch(ns: str, pattern: str = None) -> dict:
    """Register watch on a PDB namespace. Returns watch_id."""
    if not ns:
        return {"content": [{"type": "text", "text": "Error: ns required"}]}
    
    conn = _get_conn()
    try:
        # Generate watch_id
        watch_id = f"{ns}:{pattern or '*'}:{int(time.time())}"
        
        # Store watch config
        data = json.dumps({
            "ns": ns,
            "pattern": pattern or "*",
            "created_at": time.time()
        }).encode()
        
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            ('WATCHED_KEYS', watch_id.encode(), data)
        )
        
        # Take initial snapshot: query all keys in the namespace
        # We query _globals for this namespace and store each value
        ns_pattern = f"{ns}:%".encode()
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? AND subkey LIKE ?",
            (ns, ns_pattern)
        ).fetchall()
        
        snapshots = 0
        for subkey, val in rows:
            conn.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                ('WATCH_SNAPSHOTS', f"{watch_id}:{subkey.decode() if isinstance(subkey, bytes) else subkey}".encode(), val)
            )
            snapshots += 1
        
        conn.commit()
        
        return {"content": [{"type": "text", "text": f"Watch registered: {watch_id} ({snapshots} keys snapshotted)"}]}
    finally:
        conn.close()


def tool_pdb_unwatch(watch_id: str) -> dict:
    """Remove a watch and its snapshots."""
    conn = _get_conn()
    try:
        # Remove watch config
        conn.execute("DELETE FROM _globals WHERE ns='WATCHED_KEYS' AND subkey=?", (watch_id.encode(),))
        # Remove snapshots
        conn.execute("DELETE FROM _globals WHERE ns='WATCH_SNAPSHOTS' AND subkey LIKE ?", (f"{watch_id}:%".encode(),))
        conn.commit()
        return {"content": [{"type": "text", "text": f"Watch removed: {watch_id}"}]}
    finally:
        conn.close()


def tool_pdb_list_watches() -> dict:
    """List all registered watches."""
    conn = _get_conn()
    try:
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns='WATCHED_KEYS' ORDER BY subkey"
        ).fetchall()
        if not rows:
            return {"content": [{"type": "text", "text": "No watches registered."}]}
        
        result = ["Active watches:"]
        for subkey, val in rows:
            try:
                data = json.loads(val.decode())
                watch_id = subkey.decode() if isinstance(subkey, bytes) else subkey
                # Count snapshots
                count = conn.execute(
                    "SELECT COUNT(*) FROM _globals WHERE ns='WATCH_SNAPSHOTS' AND subkey LIKE ?",
                    (f"{watch_id}:%".encode(),)
                ).fetchone()[0]
                result.append(f"  {watch_id} ({count} keys)")
            except:
                continue
        
        return {"content": [{"type": "text", "text": "\n".join(result)}]}
    finally:
        conn.close()


def tool_pdb_check_notifications() -> dict:
    """
    Check all registered watches for changes since last check.
    Reports: new keys, modified keys, deleted keys.
    """
    conn = _get_conn()
    try:
        # Get all watches
        watches = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns='WATCHED_KEYS' ORDER BY subkey"
        ).fetchall()
        
        if not watches:
            return {"content": [{"type": "text", "text": "No watches registered. Use pdb_watch first."}]}
        
        all_notifications = []
        
        for watch_subkey, watch_val in watches:
            watch_id = watch_subkey.decode() if isinstance(watch_subkey, bytes) else watch_subkey
            try:
                watch_data = json.loads(watch_val.decode())
            except:
                continue
            
            ns = watch_data["ns"]
            pattern = watch_data.get("pattern", "*")
            
            # Get current state of the watched namespace
            ns_pattern = f"{ns}:%".encode()
            current_rows = conn.execute(
                "SELECT subkey, value FROM _globals WHERE ns=? AND subkey LIKE ?",
                (ns, ns_pattern)
            ).fetchall()
            
            current_keys = {}
            for sk, val in current_rows:
                sk_str = sk.decode() if isinstance(sk, bytes) else sk
                current_keys[sk_str] = val
            
            # Apply pattern filter
            if pattern and pattern != "*":
                try:
                    p = re.compile(pattern.replace("*", ".*").replace("?", "."))
                    current_keys = {k: v for k, v in current_keys.items() if p.search(k)}
                except:
                    pass
            
            # Get stored snapshots for this watch
            snap_rows = conn.execute(
                "SELECT subkey, value FROM _globals WHERE ns='WATCH_SNAPSHOTS' AND subkey LIKE ?",
                (f"{watch_id}:%".encode(),)
            ).fetchall()
            
            snapshot_keys = {}
            for sk, val in snap_rows:
                sk_str = sk.decode() if isinstance(sk, bytes) else sk
                # Remove watch_id: prefix
                actual_key = sk_str[len(watch_id)+1:]
                snapshot_keys[actual_key] = val
            
            # Detect changes
            new_keys = [k for k in current_keys if k not in snapshot_keys]
            deleted_keys = [k for k in snapshot_keys if k not in current_keys]
            modified_keys = []
            for k in current_keys:
                if k in snapshot_keys and current_keys[k] != snapshot_keys[k]:
                    modified_keys.append(k)
            
            # Record notifications for changes
            timestamp = time.time()
            for key in new_keys:
                notif_subkey = f"{watch_id}:{key}:{timestamp}:new"
                notif_val = json.dumps({
                    "watch_id": watch_id,
                    "key": key,
                    "change": "new",
                    "timestamp": timestamp,
                    "value_snippet": (current_keys[key].decode()[:200] if isinstance(current_keys[key], bytes) else str(current_keys[key])[:200])
                }).encode()
                conn.execute(
                    "INSERT INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                    ('AGENT_NOTIFICATIONS', notif_subkey.encode(), notif_val)
                )
                all_notifications.append(f"  NEW {key}")
            
            for key in modified_keys:
                notif_subkey = f"{watch_id}:{key}:{timestamp}:modified"
                notif_val = json.dumps({
                    "watch_id": watch_id,
                    "key": key,
                    "change": "modified",
                    "timestamp": timestamp
                }).encode()
                conn.execute(
                    "INSERT INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                    ('AGENT_NOTIFICATIONS', notif_subkey.encode(), notif_val)
                )
                all_notifications.append(f"  MODIFIED {key}")
            
            for key in deleted_keys:
                notif_subkey = f"{watch_id}:{key}:{timestamp}:deleted"
                notif_val = json.dumps({
                    "watch_id": watch_id,
                    "key": key,
                    "change": "deleted",
                    "timestamp": timestamp
                }).encode()
                conn.execute(
                    "INSERT INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                    ('AGENT_NOTIFICATIONS', notif_subkey.encode(), notif_val)
                )
                all_notifications.append(f"  DELETED {key}")
            
            # Update snapshots to current state (only for existing keys)
            # First delete old snapshots
            conn.execute("DELETE FROM _globals WHERE ns='WATCH_SNAPSHOTS' AND subkey LIKE ?", 
                        (f"{watch_id}:%".encode(),))
            # Then insert new snapshots
            for k, v in current_keys.items():
                conn.execute(
                    "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                    ('WATCH_SNAPSHOTS', f"{watch_id}:{k}".encode(), v)
                )
        
        conn.commit()
        
        if not all_notifications:
            # Clean old notifications (>24h)
            cutoff = time.time() - 86400
            conn.execute("DELETE FROM _globals WHERE ns='AGENT_NOTIFICATIONS'")
            conn.commit()
            return {"content": [{"type": "text", "text": "No changes detected since last check."}]}
        
        result = f"Notifications ({len(all_notifications)}):\n" + "\n".join(all_notifications)
        if len(result) > 4000:
            result = result[:4000] + "\n... (truncated)"
        
        return {"content": [{"type": "text", "text": result}]}
    finally:
        conn.close()


def tool_pdb_clear_notifications() -> dict:
    """Clear all stored notifications."""
    conn = _get_conn()
    try:
        conn.execute("DELETE FROM _globals WHERE ns='AGENT_NOTIFICATIONS'")
        conn.commit()
        return {"content": [{"type": "text", "text": "Notifications cleared."}]}
    finally:
        conn.close()


def tool_pdb_notifications_pending() -> dict:
    """Check if there are pending notifications (without consuming them)."""
    conn = _get_conn()
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns='AGENT_NOTIFICATIONS'"
        ).fetchone()[0]
        if count == 0:
            return {"content": [{"type": "text", "text": "0 pending notifications."}]}
        
        latest = conn.execute(
            "SELECT subkey FROM _globals WHERE ns='AGENT_NOTIFICATIONS' ORDER BY subkey DESC LIMIT 5"
        ).fetchall()
        
        lines = [f"{count} pending notifications."]
        for row in latest:
            lines.append(f"  {row[0].decode() if isinstance(row[0], bytes) else row[0]}")
        
        return {"content": [{"type": "text", "text": "\n".join(lines)}]}
    finally:
        conn.close()


PDB_WATCH_SCHEMAS = [
    {
        "name": "pdb_watch",
        "description": "Register watch on a PDB namespace. Takes initial snapshot. Returns watch_id for use with pdb_check_notifications.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "PDB namespace to watch (e.g. AGENT_OUTBOX)"},
                "pattern": {"type": "string", "description": "Optional key pattern filter (glob-style, e.g. zalo:*)", "default": "*"}
            },
            "required": ["ns"]
        }
    },
    {
        "name": "pdb_unwatch",
        "description": "Remove a watch and its snapshots by watch_id.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "watch_id": {"type": "string", "description": "Watch ID from pdb_watch"}
            },
            "required": ["watch_id"]
        }
    },
    {
        "name": "pdb_list_watches",
        "description": "List all active PDB watches.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_check_notifications",
        "description": "Check all watches for changes since last check. Reports new/modified/deleted keys. Updates snapshots. Call at start of each turn to detect async changes.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_notifications_pending",
        "description": "Check if there are pending notifications without consuming them.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_clear_notifications",
        "description": "Clear all stored notifications.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    }
]

PDB_WATCH_HANDLERS = {
    "pdb_watch": tool_pdb_watch,
    "pdb_unwatch": tool_pdb_unwatch,
    "pdb_list_watches": tool_pdb_list_watches,
    "pdb_check_notifications": tool_pdb_check_notifications,
    "pdb_notifications_pending": tool_pdb_notifications_pending,
    "pdb_clear_notifications": tool_pdb_clear_notifications,
}
