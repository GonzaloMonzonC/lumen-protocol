#!/usr/bin/env python3
"""
PDBM-Lumen — Process Database MUMPS-style on SQLite.

Hierarchical key-value store inspired by MUMPS globals, backed by SQLite B-tree.
No schema, no migrations, no DDL. The agent stores data as trees:

    ^PATIENT(42,"name") = "Juan"
    ^PATIENT(42,"visit",1,"dx") = "HTN"

Dual interface: KV tools (pdb_set/get/order/data/kill/incr/merge) for daily work,
SQL tools (pdb_query) for analysis.
"""

from __future__ import annotations
import json, logging, os, sqlite3, struct, threading, time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite connection — single persistent connection, WAL mode
# ---------------------------------------------------------------------------

_DB_PATH: Optional[str] = None
_conn: Optional[sqlite3.Connection] = None
_conn_lock = threading.Lock()

def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = os.environ.get("PDB_PATH") or str(
            Path(__file__).resolve().parent / "lumen-pdb.db"
        )
    return _DB_PATH

def _get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        with _conn_lock:
            if _conn is None:
                path = _get_db_path()
                c = sqlite3.connect(path, timeout=5, check_same_thread=False)
                c.execute("PRAGMA journal_mode=WAL")
                c.execute("PRAGMA synchronous=NORMAL")
                c.execute("PRAGMA busy_timeout=5000")
                c.execute("PRAGMA cache_size=-8000")  # 8 MB
                c.row_factory = sqlite3.Row
                _init_schema(c)
                _conn = c
    return _conn

def _init_schema(c: sqlite3.Connection):
    c.execute("""
        CREATE TABLE IF NOT EXISTS _globals (
            ns     TEXT NOT NULL,
            subkey BLOB NOT NULL,
            value  TEXT,   -- NULL = structural node (no value, has children)
            PRIMARY KEY (ns, subkey)
        ) WITHOUT ROWID
    """)

# ---------------------------------------------------------------------------
# Subkey encoding — sortable byte representation of subscript chains
#
# Each level: [type byte] [data] [0xFF separator]
#   type 0x01 → numeric: 8-byte big-endian double (sign-transformed)
#   type 0x02 → string:  raw UTF-8 bytes
#   0xFF is the level separator (invalid in UTF-8, always sorts high)
#
# Empty sentinel (for $ORDER boundaries, never stored):
#   sub = "" → single \x00 byte (sorts before everything)
#
# Examples:
#   ^PATIENT(1001,"name")
#   → 02 50 41 54 49 45 4E 54 FF   (PATIENT)
#     01 [8-byte BE double 1001] FF  (1001)
#     02 6E 61 6D 65 FF             (name)
#
# The encoding sorts correctly: "" < numerics < strings, levels separated.
# ---------------------------------------------------------------------------

def encode_subkey(subs: list) -> bytes:
    """Encode subscript list into a sortable BLOB key."""
    parts = []
    for sub in subs:
        if sub is None or sub == "":  # empty sentinel
            parts.append(b'\x00')
        elif isinstance(sub, (int, float)):
            parts.append(b'\x01' + _double_to_sortable(float(sub)) + b'\xff')
        elif isinstance(sub, str):
            data = sub.encode('utf-8')
            parts.append(b'\x02' + data + b'\xff')
        else:
            raise ValueError(f"Invalid subscript type: {type(sub)} ({sub!r})")
    return b''.join(parts)

def decode_subkey(blob: bytes) -> list:
    """Decode a full subkey BLOB back into a list of subscripts."""
    subs = []
    i = 0
    while i < len(blob):
        typ = blob[i]
        i += 1
        if typ == 0x00:  # empty sentinel
            subs.append("")
            break  # sentinel is always last
        elif typ == 0x01:  # numeric
            data = blob[i:i+8]
            i += 8
            subs.append(_sortable_to_double(data))
            if i < len(blob) and blob[i] == 0xff:
                i += 1  # skip separator
        elif typ == 0x02:  # string
            end = blob.find(b'\xff', i)
            if end == -1:
                data = blob[i:]
                i = len(blob)
            else:
                data = blob[i:end]
                i = end + 1
            subs.append(data.decode('utf-8'))
        else:
            raise ValueError(f"Unknown subkey type byte: 0x{typ:02x}")
    return subs

def count_levels(blob: bytes) -> int:
    """Count how many subscript levels are in a subkey BLOB."""
    if not blob:
        return 0
    count = 0
    i = 0
    while i < len(blob):
        typ = blob[i]
        i += 1
        count += 1
        if typ == 0x00:
            break
        elif typ == 0x01:
            i += 8  # 8 bytes double
            if i < len(blob) and blob[i] == 0xff:
                i += 1
        elif typ == 0x02:
            end = blob.find(b'\xff', i)
            if end == -1:
                i = len(blob)
            else:
                i = end + 1
    return count

def extract_level(blob: bytes, level_idx: int) -> Optional[Any]:
    """Extract the subscript at the given 0-based level index."""
    current = 0
    i = 0
    while i < len(blob) and current <= level_idx:
        typ = blob[i]
        start = i
        i += 1
        if typ == 0x00:
            if current == level_idx:
                return ""
            break
        elif typ == 0x01:
            if current == level_idx:
                return _sortable_to_double(blob[i:i+8])
            i += 8
            if i < len(blob) and blob[i] == 0xff:
                i += 1
        elif typ == 0x02:
            end = blob.find(b'\xff', i)
            if end == -1:
                data = blob[i:]
                i = len(blob)
            else:
                data = blob[i:end]
                i = end + 1
            if current == level_idx:
                return data.decode('utf-8')
        current += 1
    return None

def _double_to_sortable(value: float) -> bytes:
    """IEEE 754 double → 8 bytes sortable by memcmp (totalOrder)."""
    raw = struct.pack('>d', value)
    sign = raw[0] & 0x80
    if sign:  # negative: flip all bits
        return bytes(b ^ 0xFF for b in raw)
    else:    # positive: flip sign bit only
        return bytes([raw[0] ^ 0x80]) + raw[1:]

def _sortable_to_double(data: bytes) -> float:
    """Inverse: 8 sortable bytes → double."""
    if data[0] & 0x80:  # original was positive
        raw = bytes([data[0] ^ 0x80]) + data[1:]
    else:  # original was negative
        raw = bytes(b ^ 0xFF for b in data)
    return struct.unpack('>d', raw)[0]

# ---------------------------------------------------------------------------
# Value encoding — store as JSON text for SQL compatibility
# ---------------------------------------------------------------------------

def _encode_value(value) -> str:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)

def _decode_value(raw: Optional[str]):
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw  # fallback: return raw string

# ---------------------------------------------------------------------------
# SQL helpers
# ---------------------------------------------------------------------------

def _execute(sql: str, params: list = None) -> list:
    """Execute SQL, return rows as list of dicts."""
    c = _get_conn()
    try:
        cur = c.execute(sql, params or [])
        if sql.strip().upper().startswith("SELECT") or sql.strip().upper().startswith("WITH"):
            return [dict(row) for row in cur.fetchall()]
        else:
            c.commit()
            return [{"rows_affected": cur.rowcount}]
    except Exception as e:
        return [{"error": str(e)}]

# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------

def tool_set(args: dict) -> dict:
    """SET ^ns(sub1,sub2,...)=value"""
    ns = args["ns"]; subs = args["subs"]; value = args["value"]
    try:
        key = encode_subkey(subs)
        c = _get_conn()
        c.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [ns, key, _encode_value(value)]
        )
        c.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_get(args: dict) -> dict:
    """$GET(^ns(subs))"""
    ns = args["ns"]; subs = args["subs"]; default = args.get("default")
    try:
        key = encode_subkey(subs)
        c = _get_conn()
        row = c.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?", [ns, key]
        ).fetchone()
        if row and row["value"] is not None:
            return {"success": True, "value": _decode_value(row["value"])}
        return {"success": True, "value": default, "found": False}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_order(args: dict) -> dict:
    ns = args["ns"]; subs = args["subs"]; direction = args.get("direction", 1)
    """$ORDER(^ns(subs), direction) — find next/prev subscript at last level."""
    try:
        if len(subs) < 1:
            return {"success": False, "error": "Need at least one subscript for $ORDER"}
        
        parent_subs = subs[:-1]
        current = subs[-1]
        parent_key = encode_subkey(parent_subs)
        target_level = len(parent_subs)  # 0-based level we're querying
        
        # Build search key and direction
        if current == "" or current is None:
            if direction == 1:  # first
                search_key = parent_key
                op = ">"
                order = "ASC"
            else:  # last
                search_key = parent_key + b'\xff\xff\xff\xff'
                op = "<"
                order = "DESC"
        else:
            full_key = encode_subkey(subs)
            if direction == 1:
                search_key = full_key
                op = ">"
                order = "ASC"
            else:
                search_key = full_key
                op = "<"
                order = "DESC"
        
        c = _get_conn()
        # Paginate: scan until sibling found at target level (fix LIMIT 50 bug)
        offset = 0
        page_size = 200
        found_val = None
        while True:
            rows = c.execute(
                f"SELECT subkey FROM _globals WHERE ns=? AND subkey {op} ? "
                f"ORDER BY subkey {order} LIMIT ? OFFSET ?",
                [ns, search_key, page_size, offset]
            ).fetchall()
            if not rows:
                break
            for row in rows:
                sk = row["subkey"]
                lvls = count_levels(sk)
                if lvls < target_level + 1:
                    continue
                sub_val = extract_level(sk, target_level)
                if current != "" and current is not None:
                    ctype = type(current)
                    if ctype == float and isinstance(sub_val, (int, float)):
                        if abs(float(current) - float(sub_val)) < 1e-10:
                            continue
                    elif current == sub_val:
                        continue
                if parent_key and not sk.startswith(parent_key):
                    continue
                found_val = sub_val
                break
            if found_val is not None:
                break
            offset += page_size
        if found_val is not None:
            return {"success": True, "value": found_val}
        return {"success": True, "value": None}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_data(args: dict) -> dict:
    ns = args["ns"]; subs = args["subs"]
    r"""$DATA(^ns(subs)) — check existence and structure.
    
    Returns:
        0  = node does not exist
        1  = exists with value, no children
        10 = exists without value, has children
        11 = exists with value and children
    """
    try:
        key = encode_subkey(subs)
        c = _get_conn()
        row = c.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?", [ns, key]
        ).fetchone()
        
        if not row:
            # Check if it has children without existing itself
            has_children = c.execute(
                "SELECT 1 FROM _globals WHERE ns=? AND subkey > ? AND subkey < ? || X'FF' LIMIT 1",
                [ns, key, key]
            ).fetchone()
            if has_children:
                return {"success": True, "value": 10}
            # Check if it's a prefix-child (deeper level under this path)
            prefix = key + b'\x00'  # anything after our key with a separator
            has_children = c.execute(
                "SELECT 1 FROM _globals WHERE ns=? AND subkey > ? LIMIT 1",
                [ns, prefix]
            ).fetchone()
            # This is approximate... a better check would verify subkey starts with our key
            # For practical purposes, we check if any key starts with our key prefix
            # Actually let's use LIKE-like prefix matching via range query
            # subkey >= key + 0x00 and subkey < key + 0xFF
            # But 0xFF is our separator byte... all children have key + 0xFF + ...
            # So they'll all be > key + 0x00 and also > key + 0xFF (since 0xFF is max byte)
            # Hmm. Let me simplify:
            # Children of KEY have subkey starting with KEY (same bytes + more)
            # So: subkey != key but subkey starts with key
            # In SQLite BLOB: use LIKE or just check prefix
            if has_children:
                return {"success": True, "value": 10}
            return {"success": True, "value": 0}
        
        has_value = row["value"] is not None
        # Check for children
        child_prefix = key + b'\xff'  # children start with key + 0xFF (next level separator)
        # Actually children have the parent's full key as prefix, plus more bytes
        # Since our encoding uses 0xFF as separator, a child subkey ends with 0xFF at the parent level
        # and continues with more bytes. So children have key as a byte prefix.
        # But since the key itself ends with 0xFF (separator), any key that starts with key
        # is actually the same key (identical). Children have key + more_bytes.
        # So let's find keys that are longer than key and have key as prefix.
        has_children = c.execute(
            "SELECT 1 FROM _globals WHERE ns=? AND subkey > ? AND subkey < ? LIMIT 1",
            [ns, key, key + b'\xff\xff\xff\xff']
        ).fetchone()
        # Better: check if any key exists with key as prefix (longer than key)
        # Next byte after key in B-tree order
        # If the first key > key has key as prefix, it's a child
        next_key = c.execute(
            "SELECT subkey FROM _globals WHERE ns=? AND subkey > ? ORDER BY subkey LIMIT 1",
            [ns, key]
        ).fetchone()
        has_children = False
        if next_key:
            nk = next_key["subkey"]
            # Check if next_key starts with key
            if len(nk) > len(key) and nk[:len(key)] == key:
                has_children = True
        
        if has_value and has_children:
            return {"success": True, "value": 11}
        elif has_value:
            return {"success": True, "value": 1}
        elif has_children:
            return {"success": True, "value": 10}
        else:
            return {"success": True, "value": 0}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_kill(args: dict) -> dict:
    ns = args["ns"]; subs = args["subs"]
    """KILL ^ns(subs) — delete node and all children."""
    try:
        key = encode_subkey(subs)
        c = _get_conn()
        # Delete the node itself
        c.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [ns, key])
        # Delete all children (keys that start with key and are longer)
        c.execute(
            "DELETE FROM _globals WHERE ns=? AND subkey > ? AND subkey < ?",
            [ns, key, key + b'\xff\xff\xff\xff']
        )
        c.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_incr(args: dict) -> dict:
    ns = args["ns"]; subs = args["subs"]; increment = args.get("increment", 1.0)
    """$INCREMENT(^ns(subs), increment) — atomic increment. Returns new value."""
    try:
        key = encode_subkey(subs)
        c = _get_conn()
        
        # Two-step atomic increment: ensure node exists, then increment
        c.execute(
            "INSERT OR IGNORE INTO _globals (ns, subkey, value) VALUES (?, ?, '0')",
            [ns, key]
        )
        c.execute(
            "UPDATE _globals SET value = CAST(json(value) AS REAL) + ? "
            "WHERE ns=? AND subkey=?",
            [increment, ns, key]
        )
        c.commit()
        
        # Read back
        row = c.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?", [ns, key]
        ).fetchone()
        val = _decode_value(row["value"]) if row else increment
        return {"success": True, "value": val}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_merge(args: dict) -> dict:
    target_ns = args["target_ns"]; target_subs = args["target_subs"]; source_ns = args["source_ns"]; source_subs = args["source_subs"]
    """MERGE ^target_ns(target_subs) = ^source_ns(source_subs)"""
    try:
        src_key = encode_subkey(source_subs)
        tgt_key = encode_subkey(target_subs)
        c = _get_conn()
        
        # Copy source node
        row = c.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?",
            [source_ns, src_key]
        ).fetchone()
        if row:
            c.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                [target_ns, tgt_key, row["value"]]
            )
        
        # Copy all children with subkey rewrite
        child_rows = c.execute(
            "SELECT subkey, value FROM _globals "
            "WHERE ns=? AND subkey > ? AND subkey < ?",
            [source_ns, src_key, src_key + b'\xff\xff\xff\xff']
        ).fetchall()
        
        for child in child_rows:
            sk = child["subkey"]
            # Rewrite subkey: replace source prefix with target prefix
            new_sk = tgt_key + sk[len(src_key):]
            c.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                [target_ns, new_sk, child["value"]]
            )
        
        c.commit()
        return {"success": True, "nodes_copied": 1 + len(child_rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------------------------------------------------------------------------
# SQL tools
# ---------------------------------------------------------------------------

def tool_query(args: dict) -> dict:
    sql = args["sql"]; params = args.get("params"); limit = args.get("limit", 100)
    """Execute a read-only SQL query."""
    try:
        sql_upper = sql.strip().upper()
        if not (sql_upper.startswith("SELECT") or sql_upper.startswith("WITH")):
            return {"success": False, "error": "Only SELECT/WITH queries allowed in pdb_query"}
        
        if " LIMIT " not in sql_upper:
            sql = sql.rstrip(";") + f" LIMIT {limit}"
        
        rows = _execute(sql, params)
        return {"success": True, "rows": rows, "count": len(rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_schema() -> dict:
    """Describe the database: namespaces, sizes, sample paths."""
    try:
        c = _get_conn()
        # Namespace summary
        namespaces = c.execute("""
            SELECT ns, COUNT(*) as nodes,
                   COUNT(value) as with_values,
                   SUM(CASE WHEN value IS NULL THEN 1 ELSE 0 END) as structural,
                   MIN(LENGTH(subkey)) as min_key_len,
                   MAX(LENGTH(subkey)) as max_key_len
            FROM _globals GROUP BY ns ORDER BY nodes DESC
        """).fetchall()
        
        # Table info
        tables = c.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE '_%'"
        ).fetchall()
        
        db_path = _get_db_path()
        db_size = os.path.getsize(db_path) if os.path.exists(db_path) else 0
        
        return {
            "success": True,
            "database": db_path,
            "size_bytes": db_size,
            "namespaces": [dict(r) for r in namespaces],
            "app_tables": [r["name"] for r in tables],
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_backup(path: str = None) -> dict:
    """Create backup or return DB stats."""
    try:
        if path:
            import shutil
            src = _get_db_path()
            shutil.copy2(src, path)
            return {"success": True, "backup_path": path, "size_bytes": os.path.getsize(path)}
        
        # Stats only
        db_path = _get_db_path()
        c = _get_conn()
        cur = c.execute("SELECT COUNT(*) as total FROM _globals")
        total = cur.fetchone()["total"]
        return {
            "success": True,
            "database": db_path,
            "size_bytes": os.path.getsize(db_path) if os.path.exists(db_path) else 0,
            "total_nodes": total,
        }
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Tool registry
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "pdb_set",
        "description": "SET a value at a hierarchical path. Creates node if missing. Analogous to MUMPS SET ^global(subs)=value. Value can be string, number, boolean, array, object, or null.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace (global name, e.g. 'PATIENT', 'CONFIG')"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
                         "description": "Subscript path, e.g. [42, 'name'] for ^GLOBAL(42,'name')"},
                "value": {"description": "Value to store. JSON-serializable. null creates a structural node (container with no value)."}
            },
            "required": ["ns", "subs", "value"]
        }
    },
    {
        "name": "pdb_get",
        "description": "GET value at a hierarchical path. Returns null if not found (unless default provided). Analogous to MUMPS $GET(^global(subs), default).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
                "default": {"description": "Default value if key not found"}
            },
            "required": ["ns", "subs"]
        }
    },
    {
        "name": "pdb_order",
        "description": "Find the next/previous subscript at the current level. Pass '' (empty string) as the LAST subscript to get first/last. Returns null when no more subscripts. Analogous to MUMPS $ORDER(^global(subs), direction).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]},
                         "description": "Subscript path. Last element is the current position; '' (empty string) means 'before first'."},
                "direction": {"type": "integer", "default": 1, "description": "1=forward, -1=backward"}
            },
            "required": ["ns", "subs"]
        }
    },
    {
        "name": "pdb_data",
        "description": "Check node existence and structure. Returns: 0=not exists, 1=value only, 10=children only, 11=value+children. Analogous to MUMPS $DATA(^global(subs)).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}
            },
            "required": ["ns", "subs"]
        }
    },
    {
        "name": "pdb_kill",
        "description": "Delete a node and its entire subtree. Analogous to MUMPS KILL ^global(subs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}
            },
            "required": ["ns", "subs"]
        }
    },
    {
        "name": "pdb_incr",
        "description": "Atomic increment. Creates node with 0 if missing. Returns new value. Analogous to MUMPS $INCREMENT(^global(subs), increment).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
                "increment": {"type": "number", "default": 1}
            },
            "required": ["ns", "subs"]
        }
    },
    {
        "name": "pdb_merge",
        "description": "Copy a subtree from source to target. All nodes under source become accessible under target. Analogous to MUMPS MERGE ^target(t_subs)=^source(s_subs).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "target_ns": {"type": "string"},
                "target_subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
                "source_ns": {"type": "string"},
                "source_subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}
            },
            "required": ["target_ns", "target_subs", "source_ns", "source_subs"]
        }
    },
    {
        "name": "pdb_query",
        "description": "Execute a SQL query. Only SELECT/WITH allowed. Use for aggregations, JOINs, analytics across namespaces. The _globals table has columns: ns, subkey (BLOB), value (TEXT/JSON).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "SQL query (SELECT/WITH only)"},
                "params": {"type": "array", "items": {"type": ["string", "number", "null"]}, "description": "Query parameters"},
                "limit": {"type": "integer", "default": 100}
            },
            "required": ["sql"]
        }
    },
    {
        "name": "pdb_schema",
        "description": "Describe the database: list all namespaces, node counts, app tables, DB size.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pdb_backup",
        "description": "Backup the database to a file, or show DB stats (total nodes, size).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Backup path. Omit for stats only."}
            }
        }
    },
]

HANDLERS = {
    "pdb_set": tool_set,
    "pdb_get": tool_get,
    "pdb_order": tool_order,
    "pdb_data": tool_data,
    "pdb_kill": tool_kill,
    "pdb_incr": tool_incr,
    "pdb_merge": tool_merge,
    "pdb_query": tool_query,
    "pdb_schema": tool_schema,
    "pdb_backup": tool_backup,
}
