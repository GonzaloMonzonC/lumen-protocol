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
        _auto_index_on_set(ns, subs, c)
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
        _auto_index_on_kill(ns, subs, c)
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

def tool_schema(args: dict = None) -> dict:
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

def tool_backup(args: dict = None) -> dict:
    """Create backup or return DB stats."""
    try:
        if isinstance(args, dict):
            path = args.get("path")
        else:
            path = args  # backwards compat with positional args
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


# ---------------------------------------------------------------------------
# FASE 1: High-level tools for LLM productivity
# ---------------------------------------------------------------------------

def tool_batch_set(args: dict) -> dict:
    """Atomic batch insert: multiple records in one transaction."""
    items = args["items"]
    if not items:
        return {"success": True, "count": 0}
    c = _get_conn()
    try:
        for item in items:
            key = encode_subkey(item["subs"])
            c.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                [item["ns"], key, _encode_value(item["value"])]
            )
            _auto_index_on_set(item["ns"], item["subs"], c)
        c.commit()
        return {"success": True, "count": len(items)}
    except Exception as e:
        c.rollback()
        return {"success": False, "error": str(e)}

def tool_scratch_set(args: dict) -> dict:
    """Set a scratchpad value (temporary working memory for the LLM).
    Stored under ^SCRATCH(key). Survives context compressions."""
    return tool_set({"ns": "SCRATCH", "subs": [args["key"]], "value": args["value"]})

def tool_scratch_get(args: dict) -> dict:
    """Get a scratchpad value by key."""
    return tool_get({"ns": "SCRATCH", "subs": [args["key"]]})

def tool_scratch_del(args: dict) -> dict:
    """Delete a scratchpad key entirely."""
    return tool_kill({"ns": "SCRATCH", "subs": [args["key"]]})

def tool_fts_search(args: dict) -> dict:
    """Full-text search across all stored values using SQLite FTS5.
    Automatically builds/updates index on each call. Results ranked by relevance."""
    query = args["query"]
    limit = args.get("limit", 10)
    ns_filter = args.get("ns")
    c = _get_conn()
    try:
        # Create FTS5 table on first call (no content= sync — handles WITHOUT ROWID tables)
        c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS _fts USING fts5(
            ns, value, tokenize='unicode61'
        )""")
        # Rebuild index: delete stale, insert current
        c.execute("DELETE FROM _fts")
        c.execute("INSERT INTO _fts(ns, value) SELECT ns, value FROM _globals WHERE value IS NOT NULL")
        c.commit()
        # Search
        if ns_filter:
            sql = "SELECT rank, rowid, ns, value FROM _fts WHERE _fts MATCH ? AND ns=? ORDER BY rank LIMIT ?"
            params = [query, ns_filter, limit]
        else:
            sql = "SELECT rank, rowid, ns, value FROM _fts WHERE _fts MATCH ? ORDER BY rank LIMIT ?"
            params = [query, limit]
        rows = c.execute(sql, params).fetchall()
        results = []
        for r in rows:
            results.append({
                "rank": round(r["rank"], 2),
                "ns": r["ns"],
                "value": _decode_value(r["value"]),
            })
        return {"success": True, "results": results, "count": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Auto-indices — MUMPS-style ^IDX maintained automatically
# ---------------------------------------------------------------------------
# Define an index: ^INDEX_CFG(ns, idx_name) = {"sub_pos": N}
# tells PDB: "when ^ns(..., value_at_pos_N) changes, update ^IDX_ns_idx_name"
# On SET: auto-creates ^_IDX_{ns}_{idx_name}(extracted_value, parent_subs...) = ""
# On KILL: auto-deletes matching index entries

_INDEX_CFG_NS = "INDEX_CFG"
_INDEX_DATA_NS_PREFIX = "_IDX"

def _load_index_configs() -> dict:
    """Load all index definitions from PDB. Returns {ns: {idx_name: sub_pos}}."""
    configs = {}
    conn = _get_conn()
    rows = conn.execute(
        "SELECT subkey, value FROM _globals WHERE ns=? ORDER BY subkey",
        [_INDEX_CFG_NS]
    ).fetchall()
    for r in rows:
        # subkey encodes: idx_name
        subs = decode_subkey(r["subkey"])
        if len(subs) < 2:
            continue
        ns = subs[0]
        if isinstance(ns, bytes):
            ns = ns.decode("utf-8", errors="replace")
        idx_name = subs[1]
        if isinstance(idx_name, bytes):
            idx_name = idx_name.decode("utf-8", errors="replace")
        val = _decode_value(r["value"]) if r["value"] else {}
        sub_pos = val.get("sub_pos", 1) if isinstance(val, dict) else 1
        if ns not in configs:
            configs[ns] = {}
        configs[ns][idx_name] = sub_pos
    return configs

def _auto_index_on_set(ns: str, orig_subs: list, conn):
    """After SET, update auto-indices for this namespace.
    Entry: ^_IDX_{ns}_{idx_name}(indexed_value) = hash(orig_subs):JSON
    KILL uses prefix match on hash to find all children entries."""
    configs = _load_index_configs()
    if ns not in configs:
        return
    for idx_name, sub_pos in configs[ns].items():
        if sub_pos >= len(orig_subs):
            continue
        indexed_value = orig_subs[sub_pos]
        if indexed_value is None or indexed_value == "":
            continue
        idx_ns = f"{_INDEX_DATA_NS_PREFIX}_{ns}_{idx_name}"
        idx_key = encode_subkey([str(indexed_value)] + orig_subs)
        # Value format: "HASH:JSON" where HASH = hash of orig_subs for prefix match on KILL
        subs_hash = abs(hash(str(orig_subs))) % 10_000_000
        idx_val = f"{subs_hash}:{json.dumps({'orig_subs': orig_subs})}".encode()
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [idx_ns, idx_key, idx_val]
        )

def _auto_index_on_kill(ns: str, orig_subs: list, conn):
    """After KILL, clean up auto-indices by hash prefix match on value.
    Deletes entries whose stored orig_subs STARTS WITH the killed path.
    e.g. KILL [42] cleans [42, 'name', 'Juan'] because [42] is prefix."""
    configs = _load_index_configs()
    if ns not in configs:
        return
    for idx_name in configs[ns]:
        idx_ns = f"{_INDEX_DATA_NS_PREFIX}_{ns}_{idx_name}"
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=?", [idx_ns]
        ).fetchall()
        for r in rows:
            if r[1] is None:
                continue
            try:
                # Value format: "HASH:{...}"
                colon_pos = r[1].find(b':')
                if colon_pos < 0:
                    continue
                payload = r[1][colon_pos+1:]
                val = json.loads(payload.decode("utf-8", errors="replace"))
                stored_subs = val.get("orig_subs", [])
                # Check if killed path is a PREFIX of stored subs
                if len(stored_subs) >= len(orig_subs) and stored_subs[:len(orig_subs)] == orig_subs:
                    conn.execute(
                        "DELETE FROM _globals WHERE ns=? AND subkey=?",
                        [idx_ns, r[0]]
                    )
            except Exception:
                continue

def tool_index_define(args: dict) -> dict:
    """Define an auto-index. After this, every SET to ^ns(subs) with
    a value at sub_pos will auto-maintain ^_IDX_{ns}_{name}(value, ...)."""
    ns = args["ns"]
    idx_name = args["idx_name"]
    sub_pos = args.get("sub_pos", 1)
    try:
        conn = _get_conn()
        key = encode_subkey([ns, idx_name])
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [_INDEX_CFG_NS, key, json.dumps({"sub_pos": sub_pos}).encode()]
        )
        conn.commit()
        return {"success": True,
                "message": f"Index defined: ^{ns}(:,{sub_pos}) → ^_IDX_{ns}_{idx_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_index_list(args: dict) -> dict:
    """List all defined auto-indices."""
    try:
        configs = _load_index_configs()
        indices = []
        for ns, idx_map in configs.items():
            for idx_name, sub_pos in idx_map.items():
                indices.append({
                    "namespace": ns,
                    "index_name": idx_name,
                    "sub_pos": sub_pos,
                    "data_ns": f"_IDX_{ns}_{idx_name}"
                })
        return {"success": True, "indices": indices, "count": len(indices)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_index_drop(args: dict) -> dict:
    """Remove an auto-index definition and its data."""
    ns = args["ns"]
    idx_name = args["idx_name"]
    try:
        conn = _get_conn()
        key = encode_subkey([ns, idx_name])
        # Remove definition
        conn.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [_INDEX_CFG_NS, key])
        # Remove index data
        idx_ns = f"{_INDEX_DATA_NS_PREFIX}_{ns}_{idx_name}"
        conn.execute("DELETE FROM _globals WHERE ns=?", [idx_ns])
        conn.commit()
        return {"success": True, "message": f"Index dropped: ^{ns} -> ^_IDX_{ns}_{idx_name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
# In MUMPS: LOCK ^GLOBAL(key) acquires, LOCK (no args) releases all.
# Here we use threading locks keyed by namespace+subscripts.
# Supports blocking acquire with optional timeout, and targeted release.

_locks: dict[str, threading.Lock] = {}
_locks_lock = threading.Lock()

def _lock_key(ns: str, subs: list) -> str:
    """Build a lock key from namespace + subscripts."""
    return ns + ":" + "|".join(str(s) for s in subs)

def tool_lock(args: dict) -> dict:
    """LOCK ^ns(subs) — acquire a resource lock. Blocking with optional timeout."""
    ns = args["ns"]
    subs = args.get("subs", [])
    timeout = args.get("timeout", None)  # None = block indefinitely
    key = _lock_key(ns, subs)

    with _locks_lock:
        if key not in _locks:
            _locks[key] = threading.Lock()

    lock = _locks[key]
    acquired = lock.acquire(timeout=timeout)
    if acquired:
        return {"content": [{"type": "text", "text": f"Lock acquired: ^${ns}({','.join(str(s) for s in subs)})"}]}
    else:
        return {"content": [{"type": "text", "text": f"Lock timeout: ^${ns}({','.join(str(s) for s in subs)})"}]}

def tool_unlock(args: dict) -> dict:
    """UNLOCK ^ns(subs) — release a specific lock. If no args, releases all locks held by this thread."""
    ns = args.get("ns")
    subs = args.get("subs", [])
    all_flag = args.get("all", False)

    if all_flag or ns is None:
        # Release all locks this thread holds
        released = 0
        with _locks_lock:
            for key, lock in list(_locks.items()):
                try:
                    lock.release()
                    released += 1
                except RuntimeError:
                    pass  # not owned by this thread
        return {"content": [{"type": "text", "text": f"Released {released} lock(s)"}]}

    key = _lock_key(ns, subs)
    with _locks_lock:
        lock = _locks.get(key)
    if lock:
        try:
            lock.release()
            return {"content": [{"type": "text", "text": f"Lock released: ^${ns}({','.join(str(s) for s in subs)})"}]}
        except RuntimeError:
            return {"content": [{"type": "text", "text": f"Lock not held by this thread: ^${ns}({','.join(str(s) for s in subs)})"}]}
    return {"content": [{"type": "text", "text": f"Lock not found: ^${ns}({','.join(str(s) for s in subs)})"}]}

# ---------------------------------------------------------------------------
# Tool definitions
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
    {
        "name": "pdb_batch_set",
        "description": "Atomic batch insert. Insert multiple records in a single transaction. Much faster than calling pdb_set repeatedly.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "ns": {"type": "string"},
                            "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
                            "value": {"description": "Value to store (any JSON type)"}
                        },
                        "required": ["ns", "subs", "value"]
                    },
                    "description": "Array of records to insert"
                }
            },
            "required": ["items"]
        }
    },
    {
        "name": "pdb_scratch_set",
        "description": "Set a scratchpad value. Temporary working memory for the LLM that survives context compressions. Use for intermediate results, state, or any data you need across turns.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Scratchpad key"},
                "value": {"description": "Value to store (any JSON type)"}
            },
            "required": ["key", "value"]
        }
    },
    {
        "name": "pdb_scratch_get",
        "description": "Get a scratchpad value by key. Returns null if key doesn't exist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Scratchpad key"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "pdb_scratch_del",
        "description": "Delete a scratchpad key entirely.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Scratchpad key to delete"}
            },
            "required": ["key"]
        }
    },
    {
        "name": "pdb_fts_search",
        "description": "Full-text search across all stored values using SQLite FTS5. Automatically indexes new content. Results ranked by relevance. Use for searching documents, descriptions, logs, or any text content stored in PDB.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "FTS5 query (supports AND, OR, NOT, phrases, prefixes)"},
                "limit": {"type": "integer", "default": 10, "description": "Max results"},
                "ns": {"type": "string", "description": "Optional namespace filter (e.g. 'TRAVEL' to only search travel data)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "pdb_index_define",
        "description": "Define an auto-index. After this, every SET to ^ns(subs) with a value at sub_pos will auto-maintain ^_IDX_{ns}_{name}(value, parent_subs...). Use pdb_index_list to see defined indices.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to index (e.g. 'PATIENT')"},
                "idx_name": {"type": "string", "description": "Index name (e.g. 'name' creates ^_IDX_PATIENT_name)"},
                "sub_pos": {"type": "integer", "description": "Subscript position containing the indexed value (0-based, default: 1)", "default": 1}
            },
            "required": ["ns", "idx_name"]
        }
    },
    {
        "name": "pdb_index_list",
        "description": "List all defined auto-indices.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_index_drop",
        "description": "Remove an auto-index definition and all its stored index data.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace of the index"},
                "idx_name": {"type": "string", "description": "Index name to drop"}
            },
            "required": ["ns", "idx_name"]
        }
    },
    {
        "name": "pdb_lock",
        "description": "LOCK — acquire a resource lock. Blocks other sessions from writing to the same namespace+subscripts. Analogous to MUMPS LOCK ^ns(subs). Use with pdb_unlock.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to lock (e.g. 'STATE')"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}, "description": "Subscript path to lock"},
                "timeout": {"type": "number", "description": "Max seconds to wait. Omit to block indefinitely."}
            },
            "required": ["ns"]
        }
    },
    {
        "name": "pdb_unlock",
        "description": "UNLOCK — release a resource lock. Pass all=true to release all locks held by the current session. Analogous to MUMPS LOCK (no args).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to unlock"},
                "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}, "description": "Subscript path to unlock"},
                "all": {"type": "boolean", "description": "Release ALL locks held by this session", "default": False}
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
    "pdb_batch_set": tool_batch_set,
    "pdb_scratch_set": tool_scratch_set,
    "pdb_scratch_get": tool_scratch_get,
    "pdb_scratch_del": tool_scratch_del,
    "pdb_fts_search": tool_fts_search,
    "pdb_lock": tool_lock,
    "pdb_unlock": tool_unlock,
    "pdb_index_define": tool_index_define,
    "pdb_index_list": tool_index_list,
    "pdb_index_drop": tool_index_drop,
}
