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
import json, logging, os, sqlite3, struct, sys, threading, time
from pathlib import Path
from typing import Any, Optional

# MVM — singleton global (VM de procesos M)
_mvm_instance = None
def _get_mvm():
    global _mvm_instance
    if _mvm_instance is None:
        import importlib.util
        _mvm_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mvm.py")
        _mvm_spec = importlib.util.spec_from_file_location("mvm", _mvm_path)
        if _mvm_spec and os.path.exists(_mvm_path):
            _mvm_mod = importlib.util.module_from_spec(_mvm_spec)
            _mvm_spec.loader.exec_module(_mvm_mod)
            _mvm_instance = _mvm_mod.MVM(sys.modules[__name__])
    return _mvm_instance

# M-Light evaluator for trigger conditions and rules
_m_encoder = None
try:
    import importlib.util
    _m_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m_light.py")
    _m_spec = importlib.util.spec_from_file_location("m_light", _m_path)
    if _m_spec:
        _m_mod = importlib.util.module_from_spec(_m_spec)
        _m_spec.loader.exec_module(_m_mod)
        _m_encoder = _m_mod.MEvaluator()
except Exception:
    _m_encoder = None

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SQLite connection — single persistent connection, WAL mode
# With global mapping support for namespace→file redirection
# ---------------------------------------------------------------------------

_DB_PATH: Optional[str] = None
_conn: Optional[sqlite3.Connection] = None
_conn_lock = threading.Lock()

# Global mapping registry: ns → alternative db path
# Stored in ^MAP_CFG(ns) = path in the MAIN pdb
_db_connections: dict[str, sqlite3.Connection] = {}
_db_map: dict[str, str] = {}  # populated from MAP_CFG at first use

_MAP_CFG_NS = "MAP_CFG"

def _load_db_map():
    """Load global mappings from the main PDB into _db_map."""
    global _db_map
    try:
        c = _get_conn()  # ensure main conn exists
        rows = c.execute(
            "SELECT subkey, value FROM _globals WHERE ns=?", [_MAP_CFG_NS]
        ).fetchall()
        _db_map = {}
        for r in rows:
            subs = decode_subkey(r["subkey"])
            if len(subs) >= 1:
                ns = subs[0]
                if isinstance(ns, bytes):
                    ns = ns.decode("utf-8", errors="replace")
                path = r["value"].decode("utf-8", errors="replace") if r["value"] else None
                if path:
                    _db_map[ns] = path
    except Exception:
        _db_map = {}

def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = os.environ.get("PDB_PATH") or str(
            Path(__file__).resolve().parent / "lumen-pdb.db"
        )
    return _DB_PATH

def _get_conn(ns: str = None, subs: list = None) -> sqlite3.Connection:
    """Get a connection for the given namespace.
    If ns has subs and a partition config, routes to the correct partition.
    If ns has a global mapping, returns the mapped DB connection.
    Otherwise returns the default connection."""
    global _conn

    # Partition routing (checked first — more specific)
    if ns and subs and _part_configs:
        part_cfg = _part_configs.get(ns)
        if part_cfg:
            key_pos = part_cfg.get("key_pos", 0)
            ranges = part_cfg.get("ranges", [])
            if key_pos < len(subs):
                part_key = subs[key_pos]
                if isinstance(part_key, (int, float)):
                    for r in ranges:
                        if part_key <= r.get("max", float('inf')):
                            mapped_path = r.get("path")
                            if mapped_path:
                                pkey = f"{ns}_part_{part_key}"
                                return _get_or_create_mapped_conn(pkey, mapped_path)
                            break

    # Check if this namespace has a global mapping
    if ns and _db_map:
        mapped_path = _db_map.get(ns)
        if mapped_path:
            if ns not in _db_connections:
                c = sqlite3.connect(mapped_path, timeout=5, check_same_thread=False)
                c.execute("PRAGMA journal_mode=DELETE")
                c.execute("PRAGMA synchronous=NORMAL")
                c.execute("PRAGMA busy_timeout=5000")
                c.execute("PRAGMA cache_size=-8000")
                c.row_factory = sqlite3.Row
                _init_schema(c)
                _db_connections[ns] = c
            return _db_connections[ns]

    # Default connection
    if _conn is None:
        with _conn_lock:
            if _conn is None:
                path = _get_db_path()
                c = sqlite3.connect(path, timeout=10, check_same_thread=False)
                c.execute("PRAGMA journal_mode=DELETE")
                c.execute("PRAGMA synchronous=NORMAL")
                c.execute("PRAGMA busy_timeout=30000")
                c.execute("PRAGMA cache_size=-8000")  # 8 MB
                c.row_factory = sqlite3.Row
                _init_schema(c)
                _conn = c
    # Auto-checkpoint si WAL > 10MB (previene DB locks)
    if _conn:
        try:
            wal_path = _get_db_path() + "-wal"
            if os.path.exists(wal_path) and os.path.getsize(wal_path) > 10_000_000:
                _conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except:
            pass
    return _conn

def _get_or_create_mapped_conn(key: str, path: str) -> sqlite3.Connection:
    """Get or create a connection for a mapped path. Used by mapping and partitioning."""
    if key in _db_connections:
        return _db_connections[key]
    c = sqlite3.connect(path, timeout=5, check_same_thread=False)
    c.execute("PRAGMA journal_mode=DELETE")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA busy_timeout=5000")
    c.execute("PRAGMA cache_size=-8000")
    c.row_factory = sqlite3.Row
    _init_schema(c)
    _db_connections[key] = c
    return c

# Load db map on first module access
_load_db_map()

# Partition config — loaded lazily
_PART_CFG_NS = "PART_CFG"
_part_configs: dict = {}
_part_configs_loaded = False

def _load_part_configs():
    """Load partition configurations from PDB."""
    global _part_configs, _part_configs_loaded
    if _part_configs_loaded:
        return
    try:
        c = _get_conn()
        rows = c.execute(
            "SELECT subkey, value FROM _globals WHERE ns=?", [_PART_CFG_NS]
        ).fetchall()
        _part_configs = {}
        for r in rows:
            subs = decode_subkey(r["subkey"])
            if len(subs) >= 1:
                ns = subs[0]
                if isinstance(ns, bytes):
                    ns = ns.decode("utf-8", errors="replace")
                val = json.loads(r["value"].decode("utf-8", errors="replace")) if r["value"] else {}
                if isinstance(val, dict):
                    _part_configs[ns] = val
        _part_configs_loaded = True
    except Exception:
        _part_configs = {}

def tool_partition_define(args: dict) -> dict:
    """Define automatic partitioning for a namespace.
    Partitions split by subscript at key_pos into ranges, each range mapped to a file.
    Example: key_pos=0, ranges=[{max:100000, path:'/data/part1.db'}, {max:200000, path:'/data/part2.db'}]"""
    ns = args["ns"]
    key_pos = args.get("key_pos", 0)
    ranges = args.get("ranges", [])
    if not ranges:
        return {"success": False, "error": "At least one range required"}
    try:
        # Validate paths
        for r in ranges:
            path = Path(r.get("path", "")).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            test = sqlite3.connect(str(path), timeout=2)
            test.execute("PRAGMA journal_mode=DELETE")
            test.close()
            r["path"] = str(path)
        # Store config
        c = _get_conn()
        key = encode_subkey([ns])
        val = json.dumps({"key_pos": key_pos, "ranges": ranges}).encode()
        c.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [_PART_CFG_NS, key, val]
        )
        c.commit()
        _part_configs[ns] = {"key_pos": key_pos, "ranges": ranges}
        return {"success": True, "message": f"^{ns} partitioned by subs[{key_pos}], {len(ranges)} ranges"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_partition_list(args: dict) -> dict:
    """List all partition configurations."""
    _load_part_configs()
    results = []
    for ns, cfg in _part_configs.items():
        results.append({"namespace": ns, "key_pos": cfg.get("key_pos"), "range_count": len(cfg.get("ranges", []))})
    return {"success": True, "partitions": results, "count": len(results)}

def tool_partition_drop(args: dict) -> dict:
    """Remove partition configuration for a namespace. Falls back to single file."""
    ns = args["ns"]
    try:
        c = _get_conn()
        key = encode_subkey([ns])
        c.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [_PART_CFG_NS, key])
        c.commit()
        _part_configs.pop(ns, None)
        # Clean up partition connections
        keys_to_remove = [k for k in _db_connections if k.startswith(f"{ns}_part_")]
        for k in keys_to_remove:
            _db_connections.pop(k, None)
        return {"success": True, "message": f"Partitioning removed: ^{ns}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ---------------------------------------------------------------------------
# Global Mapping tools — ^GLOBAL → file redirection (MSM-style)
# ---------------------------------------------------------------------------

def tool_map_set(args: dict) -> dict:
    """Map a namespace to a different SQLite file. ^ns(subs) will read/write to that file.
    Analogous to MSM global mapping. Stored in ^MAP_CFG(ns) in the main PDB."""
    ns = args["ns"]
    db_path = args.get("db_path", "")
    if not db_path:
        # Remove mapping (use default DB)
        c = _get_conn(ns)
        key = encode_subkey([ns])
        c.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [_MAP_CFG_NS, key])
        c.commit()
        _db_map.pop(ns, None)
        _db_connections.pop(ns, None)
        return {"success": True, "message": f"Mapping removed: ^{ns} → default"}
    try:
        # Verify the path is writable by creating the file if needed
        path = Path(db_path).resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        # Test connection
        test_conn = sqlite3.connect(str(path), timeout=2)
        test_conn.execute("PRAGMA journal_mode=DELETE")
        test_conn.close()
        # Store mapping
        c = _get_conn(ns)
        key = encode_subkey([ns])
        c.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [_MAP_CFG_NS, key, str(path).encode()]
        )
        c.commit()
        _db_map[ns] = str(path)
        return {"success": True, "message": f"^{ns} → {path}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_map_get(args: dict) -> dict:
    """Get the mapped path for a namespace."""
    ns = args["ns"]
    path = _db_map.get(ns)
    if path:
        return {"success": True, "namespace": ns, "db_path": path}
    return {"success": True, "namespace": ns, "db_path": None, "message": "Using default DB"}

def tool_map_list(args: dict) -> dict:
    """List all namespace→file mappings."""
    if not _db_map:
        return {"success": True, "mappings": [], "count": 0}
    mappings = [{"namespace": ns, "db_path": path} for ns, path in _db_map.items()]
    return {"success": True, "mappings": mappings, "count": len(mappings)}

def tool_map_drop(args: dict) -> dict:
    """Remove a namespace mapping. Falls back to default DB."""
    ns = args["ns"]
    c = _get_conn(ns)
    key = encode_subkey([ns])
    c.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [_MAP_CFG_NS, key])
    c.commit()
    _db_map.pop(ns, None)
    _db_connections.pop(ns, None)
    return {"success": True, "message": f"Mapping removed: ^{ns} → default"}

# ---------------------------------------------------------------------------
# Journaling — WAL management, checkpoint, backup
# ---------------------------------------------------------------------------

def tool_journal_checkpoint(args: dict) -> dict:
    """Force a WAL checkpoint on the main PDB and all mapped/partitioned DBs.
    Returns WAL file sizes before and after."""
    import os
    results = {"default": {}, "mapped": {}}
    # Default DB
    c = _get_conn()
    before = _wal_size(_get_db_path())
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    after = _wal_size(_get_db_path())
    results["default"] = {"db": _get_db_path(), "wal_before_kb": before//1024, "wal_after_kb": after//1024}
    # Mapped/partitioned DBs
    for key, conn in _db_connections.items():
        try:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except:
            pass
    return {"success": True, "checkpoints": results}

def _wal_size(db_path: str) -> int:
    """Get WAL file size for a given DB path."""
    import os
    wal_path = db_path + "-wal"
    try:
        return os.path.getsize(wal_path)
    except:
        return 0

def tool_journal_status(args: dict) -> dict:
    """Show journal status for the main PDB and all mapped connections."""
    c = _get_conn()
    pages = c.execute("PRAGMA page_count").fetchone()[0]
    page_size = c.execute("PRAGMA page_size").fetchone()[0]
    wal_auto = c.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
    results = {
        "default": {
            "db_path": _get_db_path(),
            "db_size_kb": os.path.getsize(_get_db_path()) // 1024 if os.path.exists(_get_db_path()) else 0,
            "wal_size_kb": _wal_size(_get_db_path()) // 1024,
            "pages": pages,
            "page_size": page_size,
            "wal_autocheckpoint": wal_auto,
            "journal_mode": c.execute("PRAGMA journal_mode").fetchone()[0],
        },
        "mapped": {}
    }
    for key, conn in _db_connections.items():
        try:
            p = conn.execute("PRAGMA page_count").fetchone()[0]
            ps = conn.execute("PRAGMA page_size").fetchone()[0]
            results["mapped"][key] = {"page_count": p, "page_size": ps}
        except:
            pass
    return {"success": True, "status": results}

def tool_journal_backup(args: dict) -> dict:
    """Create a consistent backup of the main PDB (with WAL checkpoint).
    Optionally specify backup path. Default: lumen-pdb.backup.db"""
    backup_path = args.get("backup_path", str(Path(_get_db_path()).parent / "lumen-pdb.backup.db"))
    try:
        c = _get_conn()
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        from shutil import copy2
        copy2(_get_db_path(), backup_path)
        size = os.path.getsize(backup_path)
        return {"success": True, "backup_path": backup_path, "size_bytes": size}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_m_eval(args: dict) -> dict:
    """Evaluate an M expression using M-Light. Supports $GET, $DATA, $PIECE, $EXTRACT, $SELECT.
    Examples: $GET(^PATIENT(42,"name")), $PIECE("a|b|c","|",2), $SELECT(1=1:"yes",1:"no")"""
    expr = args.get("expression", "")
    try:
        import importlib.util, sys
        _m_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m_light.py")
        _m_spec = importlib.util.spec_from_file_location("m_light", _m_path)
        _m_mod = importlib.util.module_from_spec(_m_spec)
        _m_spec.loader.exec_module(_m_mod)
        # Pass this module as the PDB reference
        encoder = _m_mod.MEvaluator(sys.modules[__name__])
        result = encoder.eval_expr(expr)
        return {"success": True, "expression": expr, "result": result}
    except Exception as e:
        return {"success": False, "error": str(e), "expression": expr}

def tool_m_repl(args: dict) -> dict:
    """M REPL — ejecuta una o más líneas de código M contra PDB en vivo.
    Cada línea se evalúa independientemente. Las variables persisten entre líneas.
    Soporta: S, K, F, Q, IF, $O, $G, $D, $P, $E, $S.
    Ejemplo: S N=\"\" F  S N=$O(^nombres(N)) Q:N=\"\"  S ^res(N)=N"""
    code = args.get("code", "")
    if not code.strip():
        return {"success": True, "result": "", "lines": 0}
    try:
        import importlib.util, sys
        _m_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m_light.py")
        _m_spec = importlib.util.spec_from_file_location("m_light", _m_path)
        _m_mod = importlib.util.module_from_spec(_m_spec)
        _m_spec.loader.exec_module(_m_mod)
        encoder = _m_mod.MEvaluator(sys.modules[__name__])
        output = []
        for line in code.strip().split("\n"):
            line = line.strip()
            if not line or line.startswith(";"):
                continue
            try:
                result = encoder.eval(line)
                output.append(f"> {line}")
                if result is not None:
                    output.append(f"  = {result}")
            except Exception as e:
                output.append(f"> {line}")
                output.append(f"  ! {e}")
        return {"success": True, "result": "\n".join(output), "lines": len([l for l in code.strip().split("\n") if l.strip() and not l.strip().startswith(";")])}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── MVM — M Virtual Machine tools ──

def tool_mvm_spawn(args: dict) -> dict:
    """Spawn a new M process. Returns PID ($J)."""
    code = args.get("code", "")
    name = args.get("name", f"proc_{time.time()}")
    vm = _get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        pid = vm.spawn(code, name=name)
        procs = vm.list_processes()
        procs_info = [{"pid": p["pid"], "name": p["name"], "status": p["status"]} for p in procs]
        return {"success": True, "pid": pid, "processes": procs_info}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_tick(args: dict) -> dict:
    """Execute one tick of the MVM dispatcher. Runs all processes."""
    vm = _get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        max_per = args.get("max_per_process", 100)
        alive = vm.tick(max_per_process=max_per)
        procs = vm.list_processes()
        procs_info = [{"pid": p["pid"], "name": p["name"], "status": p["status"], "pc": p["pc"]} for p in procs]
        return {"success": True, "alive": alive, "total": len(procs_info), "processes": procs_info}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_list(args: dict) -> dict:
    """List all MVM processes and their status."""
    vm = _get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        procs = vm.list_processes()
        return {"success": True, "count": len(procs), "processes": procs}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_kill(args: dict) -> dict:
    """Kill an MVM process by PID."""
    pid = str(args.get("pid", ""))
    vm = _get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        ok = vm.kill(pid)
        return {"success": ok, "pid": pid}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_mailbox_send(args: dict) -> dict:
    """Send a message to a process mailbox."""
    to_pid = str(args.get("to_pid", ""))
    message = args.get("message", "")
    vm = _get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        msg_id = vm.mailbox_send(to_pid, message)
        return {"success": True, "message_id": msg_id, "to_pid": to_pid}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_mailbox_read(args: dict) -> dict:
    """Read all pending messages from a process mailbox."""
    pid = str(args.get("pid", ""))
    vm = _get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        msgs = vm.mailbox_read(pid)
        return {"success": True, "count": len(msgs), "messages": msgs}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── DBFIX — Mantenimiento automático ──

def tool_dbfix(args: dict) -> dict:
    """DBFIX — mantenimiento automático de PDB.
    Ejecuta: integrity_check, reindex FTS5, WAL checkpoint, vacuum condicional."""
    report = {}
    c = _get_conn()

    # 1. Integrity check
    try:
        rows = c.execute("PRAGMA integrity_check").fetchall()
        errors = [r[0] for r in rows if r[0] != 'ok']
        report['integrity'] = {'ok': len(errors) == 0, 'errors': errors[:5]}
    except Exception as e:
        report['integrity'] = {'ok': False, 'error': str(e)}

    # 2. FTS5 reindex
    try:
        c.execute("DELETE FROM _fts")
        c.execute("INSERT INTO _fts(ns, value) SELECT ns, value FROM _globals WHERE value IS NOT NULL")
        fts_count = c.execute("SELECT COUNT(*) FROM _fts").fetchone()[0]
        report['fts_reindex'] = {'ok': True, 'count': fts_count}
    except Exception as e:
        report['fts_reindex'] = {'ok': False, 'error': str(e)}

    # 3. WAL checkpoint
    try:
        before = _wal_size(_get_db_path())
        c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        after = _wal_size(_get_db_path())
        report['wal_checkpoint'] = {'ok': True, 'wal_before_kb': before//1024, 'wal_after_kb': after//1024}
    except Exception as e:
        report['wal_checkpoint'] = {'ok': False, 'error': str(e)}

    # 4. Vacuum condicional
    try:
        db_size = os.path.getsize(_get_db_path())
        page_count = c.execute("PRAGMA page_count").fetchone()[0]
        page_size = c.execute("PRAGMA page_size").fetchone()[0]
        freelist = c.execute("PRAGMA freelist_count").fetchone()[0]
        free_pct = (freelist * page_size / db_size * 100) if db_size > 0 else 0
        if db_size > 100_000_000 and free_pct > 20:
            c.execute("VACUUM")
            report['vacuum'] = {'ok': True, 'freed_mb': round(db_size/1024/1024 - os.path.getsize(_get_db_path())/1024/1024, 1)}
        else:
            report['vacuum'] = {'skipped': True, 'reason': f'DB {db_size/1024/1024:.0f}MB, free {free_pct:.0f}%'}
    except Exception as e:
        report['vacuum'] = {'ok': False, 'error': str(e)}

    c.commit()
    return {"success": True, "report": report}

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
    """Encode subscript list into a sortable BLOB key.

    Binary format:
        Each subscript is encoded as: [type_byte] [data] [separator?]

        Types:
        - ``\\x00`` — NULL sentinel (backward compat, only as last sub)
        - ``\\x01`` + 8 bytes (IEEE 754 double, sortable) + ``\\xff`` — numeric
        - ``\\x02`` + UTF-8 bytes + ``\\xff`` — string
        - ``\\x02\\xff`` — empty string ``""`` (zero-length string marker)

    Examples:
        ``['ext', '.py', 'foo.py']`` →
        ``\\x02ext\\xff\\x02.py\\xff\\x02foo.py\\xff``

        ``['ext', '', 'foo']`` (empty extension) →
        ``\\x02ext\\xff\\x02\\xff\\x02foo\\xff``

    NOTE: The old ``\\x00`` sentinel for ``""`` broke multi-subscript keys
    because ``decode_subkey`` stopped at ``\\x00``. Fixed 2026-06-27.
    """
    parts = []
    for sub in subs:
        if sub is None:  # null sentinel (backward compat)
            parts.append(b'\x00')
        elif sub == "":  # empty string — encode as zero-length string,
            parts.append(b'\x02\xff')  # not as \x00 sentinel which breaks $ORDER
        elif isinstance(sub, (int, float)):
            parts.append(b'\x01' + _double_to_sortable(float(sub)) + b'\xff')
        elif isinstance(sub, str):
            data = sub.encode('utf-8')
            parts.append(b'\x02' + data + b'\xff')
        else:
            raise ValueError(f"Invalid subscript type: {type(sub)} ({sub!r})")
    return b''.join(parts)

def decode_subkey(blob: bytes) -> list:
    """Decode a full subkey BLOB back into a list of subscripts.

    Inverse of encode_subkey. See encode_subkey docs for binary format.

    Handles both:
    - New format: ``\\x02\\xff`` for empty string ``""``
    - Legacy format: ``\\x00`` sentinel (backward compatible, last subscript only)
    """
    subs = []
    i = 0
    while i < len(blob):
        typ = blob[i]
        i += 1
        if typ == 0x00:  # null sentinel (backward compat)
            subs.append(None)
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
                # Check for zero-length string (\x02 followed by \xff)
                if i < len(blob) and blob[i] == 0xff:
                    subs.append("")
                    i += 1
                else:
                    data = blob[i:]
                    i = len(blob)
            else:
                if end == i:  # zero-length string: \x02\xff
                    subs.append("")
                else:
                    data = blob[i:end]
                    subs.append(data.decode('utf-8'))
                i = end + 1
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
        c = _get_conn(ns, subs)
        c.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [ns, key, _encode_value(value)]
        )
        _auto_index_on_set(ns, subs, c)
        _fire_triggers("ON_SET", ns, subs, value, c)
        c.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_get(args: dict) -> dict:
    """$GET(^ns(subs))"""
    ns = args["ns"]; subs = args["subs"]; default = args.get("default")
    try:
        key = encode_subkey(subs)
        c = _get_conn(ns, subs)
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
        
        c = _get_conn(ns, subs)
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
        c = _get_conn(ns, subs)
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
        c = _get_conn(ns, subs)
        _auto_index_on_kill(ns, subs, c)
        _fire_triggers("ON_KILL", ns, subs, None, c)
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
        c = _get_conn(ns, subs)
        
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
        c = _get_conn(target_ns, target_subs)
        
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

# ---------------------------------------------------------------------------
# Triggers — ON SET / ON KILL callbacks
# ---------------------------------------------------------------------------
# Define a trigger: ^TRIGGER_CFG(ns, trigger_id) = {"event":"ON_SET","action":"pdb_set|webhook|log","params":{...}}
# Events: ON_SET, ON_KILL (ON_READ planned)
# Actions: pdb_set(replicate to another ns), webhook(POST url), log(system log)

_TRIGGER_CFG_NS = "TRIGGER_CFG"

def _load_triggers() -> dict:
    """Load all trigger definitions. Returns {ns: {trigger_id: {event, action, params}}}."""
    triggers = {}
    conn = _get_conn()
    rows = conn.execute(
        "SELECT subkey, value FROM _globals WHERE ns=? ORDER BY subkey",
        [_TRIGGER_CFG_NS]
    ).fetchall()
    for r in rows:
        subs = decode_subkey(r["subkey"])
        if len(subs) < 2:
            continue
        ns = subs[0] if isinstance(subs[0], str) else subs[0].decode() if isinstance(subs[0], bytes) else str(subs[0])
        tid = subs[1] if isinstance(subs[1], str) else subs[1].decode() if isinstance(subs[1], bytes) else str(subs[1])
        val = _decode_value(r["value"]) if r["value"] else {}
        if isinstance(val, dict):
            if ns not in triggers:
                triggers[ns] = {}
            triggers[ns][tid] = val
    return triggers

def _fire_triggers(event: str, ns: str, subs: list, value, conn, old_value=None):
    """Called after SET/KILL. Executes matching trigger actions."""
    triggers = _load_triggers()
    if ns not in triggers:
        return
    for tid, cfg in triggers[ns].items():
        if cfg.get("event") != event:
            continue
        action = cfg.get("action", "")
        params = cfg.get("params", {})
        try:
            if action == "pdb_set":
                dest_ns = params.get("dest_ns", ns)
                # Template substitution: {sub_N} → orig_subs[N]
                dest_subs = []
                for s in params.get("dest_subs", subs):
                    if isinstance(s, str) and s.startswith("{sub_") and s.endswith("}"):
                        idx = int(s[5:-1])
                        dest_subs.append(subs[idx] if idx < len(subs) else s)
                    else:
                        dest_subs.append(s)
                dest_key = encode_subkey(dest_subs)
                conn.execute(
                    "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                    [dest_ns, dest_key, _encode_value(params.get("dest_value", value))]
                )
            elif action == "log":
                logger.info(f"TRIGGER [{event}] ^{ns}({subs}) = {value}")
        except Exception as e:
            logger.warning(f"TRIGGER error {tid} on ^{ns}: {e}")

def tool_trigger_define(args: dict) -> dict:
    """Define a trigger. Fires on SET/KILL events in a namespace."""
    ns = args["ns"]
    trigger_id = args.get("trigger_id")
    event = args.get("event", "ON_SET")
    action = args.get("action", "log")
    params = args.get("params", {})
    import uuid
    trigger_id = trigger_id or f"trg_{uuid.uuid4().hex[:8]}"
    try:
        conn = _get_conn(ns)
        key = encode_subkey([ns, trigger_id])
        val = json.dumps({"event": event, "action": action, "params": params}).encode()
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [_TRIGGER_CFG_NS, key, val]
        )
        conn.commit()
        return {"success": True, "trigger_id": trigger_id,
                "message": f"Trigger {trigger_id}: ON {event} → {action}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_trigger_list(args: dict) -> dict:
    """List all defined triggers."""
    ns_filter = args.get("ns")
    try:
        triggers = _load_triggers()
        results = []
        for ns_name, trigs in triggers.items():
            if ns_filter and ns_name != ns_filter:
                continue
            for tid, cfg in trigs.items():
                results.append({"namespace": ns_name, "trigger_id": tid, **cfg})
        return {"success": True, "triggers": results, "count": len(results)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_trigger_drop(args: dict) -> dict:
    """Remove a trigger definition."""
    ns = args["ns"]
    trigger_id = args["trigger_id"]
    try:
        conn = _get_conn(ns)
        key = encode_subkey([ns, trigger_id])
        conn.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [_TRIGGER_CFG_NS, key])
        conn.commit()
        return {"success": True, "message": f"Trigger dropped: {ns}/{trigger_id}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_trigger(args: dict) -> dict:
    """List or drop triggers (legacy/combined entry point)."""
    action = args.get("action", "list")
    if action == "list":
        return tool_trigger_list(args)
    elif action == "drop":
        return tool_trigger_drop(args)
    return {"success": False, "error": "Unknown action. Use list or drop."}

def tool_index_define(args: dict) -> dict:
    """Define an auto-index. After this, every SET to ^ns(subs) with
    a value at sub_pos will auto-maintain ^_IDX_{ns}_{name}(value, ...)."""
    ns = args["ns"]
    idx_name = args["idx_name"]
    sub_pos = args.get("sub_pos", 1)
    try:
        conn = _get_conn(ns)
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
        conn = _get_conn(ns)
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
        "name": "pdb_trigger_define",
        "description": "Define a trigger. Fires on ON_SET or ON_KILL events in a namespace. Actions: log, pdb_set (replicate), webhook. Use {sub_N} in dest_subs for subscript substitution.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to watch"},
                "trigger_id": {"type": "string", "description": "Optional custom ID (auto-generated if omitted)"},
                "event": {"type": "string", "enum": ["ON_SET", "ON_KILL"], "description": "Event type", "default": "ON_SET"},
                "action": {"type": "string", "enum": ["log", "pdb_set", "webhook"], "description": "Action to execute", "default": "log"},
                "params": {"type": "object", "description": "Action params: dest_ns, dest_subs (with {sub_N} templates), dest_value, url"}
            },
            "required": ["ns"]
        }
    },
    {
        "name": "pdb_trigger_list",
        "description": "List all defined triggers. Filter by namespace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Optional namespace filter"}
            }
        }
    },
    {
        "name": "pdb_trigger_drop",
        "description": "Remove a trigger definition.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace of the trigger"},
                "trigger_id": {"type": "string", "description": "Trigger ID to remove"}
            },
            "required": ["ns", "trigger_id"]
        }
    },
    {
        "name": "pdb_trigger",
        "description": "Combined trigger management: list or drop triggers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "drop"], "description": "Action"},
                "ns": {"type": "string"},
                "trigger_id": {"type": "string"}
            },
            "required": ["action"]
        }
    },
    {
        "name": "pdb_map_set",
        "description": "Map a namespace to a different SQLite file. ^ns(subs) will read/write to that file instead of the default DB. Pass empty db_path to remove mapping. Analogous to MSM global mapping.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to map (e.g. 'PATIENT')"},
                "db_path": {"type": "string", "description": "Path to SQLite file. Empty string removes mapping."}
            },
            "required": ["ns"]
        }
    },
    {
        "name": "pdb_map_get",
        "description": "Get the mapped file path for a namespace.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to query"}
            },
            "required": ["ns"]
        }
    },
    {
        "name": "pdb_map_list",
        "description": "List all namespace→file global mappings.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_map_drop",
        "description": "Remove a namespace mapping. Falls back to default PDB.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to unmap"}
            },
            "required": ["ns"]
        }
    },
    {
        "name": "pdb_m_eval",
        "description": "Evaluate an M expression using M-Light. Supports $GET(^ns(subs)), $PIECE, $EXTRACT, $SELECT. Examples: $GET(^PATIENT(42,\"name\")), $PIECE(\"a|b|c\",\"|\",2).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "M expression to evaluate"}
            },
            "required": ["expression"]
        }
    },
    {
        "name": "pdb_m_repl",
        "description": "M REPL — ejecuta código M contra PDB en vivo. Variables persisten entre líneas. Múltiples líneas separadas por saltos. Ejemplo: S N=\"\"\\nF  S N=$O(^n(N)) Q:N=\"\"",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "Código M (una o más líneas)"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "pdb_dbfix",
        "description": "DBFIX — mantenimiento automático de PDB. Ejecuta: integrity_check, FTS5 reindex, WAL checkpoint, vacuum condicional. Devuelve report completo.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_mvm_spawn",
        "description": "Spawn a new M process (MVM). Returns PID ($J). Code runs as M-Light in a persistent process.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "description": "M code to execute"},
                "name": {"type": "string", "description": "Process name"}
            },
            "required": ["code"]
        }
    },
    {
        "name": "pdb_mvm_tick",
        "description": "Execute one VM tick. Runs all active processes by a number of instructions each.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "max_per_process": {"type": "integer", "description": "Max instructions per process"}
            }
        }
    },
    {
        "name": "pdb_mvm_list",
        "description": "List all MVM processes with status, PC, vars, age.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_mvm_kill",
        "description": "Kill an MVM process by PID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "string", "description": "Process ID to kill"}
            },
            "required": ["pid"]
        }
    },
    {
        "name": "pdb_mvm_mailbox_send",
        "description": "Send a message to a process mailbox.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to_pid": {"type": "string", "description": "Target process ID"},
                "message": {"description": "Message content (string or object)"}
            },
            "required": ["to_pid", "message"]
        }
    },
    {
        "name": "pdb_mvm_mailbox_read",
        "description": "Read all pending messages from a process mailbox. Messages are deleted after reading.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "string", "description": "Process ID to read mailbox from"}
            },
            "required": ["pid"]
        }
    },
    {
        "name": "pdb_partition_define",
        "description": "Define automatic partitioning for a namespace. Partitions split by subscript at key_pos into ranges, each range mapped to a separate SQLite file. Solves the MSM 2GB limit problem.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to partition"},
                "key_pos": {"type": "integer", "description": "Subscript position to partition by (0-based, default: 0)", "default": 0},
                "ranges": {"type": "array", "items": {"type": "object", "properties": {"max": {"type": "number"}, "path": {"type": "string"}}},
                          "description": "Range definitions: [{max: 100000, path: '/data/part1.db'}, {max: 200000, path: '/data/part2.db'}]"}
            },
            "required": ["ns", "ranges"]
        }
    },
    {
        "name": "pdb_partition_list",
        "description": "List all partition configurations.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "pdb_partition_drop",
        "description": "Remove partition configuration for a namespace. Falls back to single file.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ns": {"type": "string", "description": "Namespace to remove partitioning from"}
            },
            "required": ["ns"]
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
    "pdb_trigger_define": tool_trigger_define,
    "pdb_trigger_list": tool_trigger_list,
    "pdb_trigger_drop": tool_trigger_drop,
    "pdb_trigger": tool_trigger,
    "pdb_map_set": tool_map_set,
    "pdb_map_get": tool_map_get,
    "pdb_map_list": tool_map_list,
    "pdb_map_drop": tool_map_drop,
    "pdb_partition_define": tool_partition_define,
    "pdb_partition_list": tool_partition_list,
    "pdb_partition_drop": tool_partition_drop,
    "pdb_m_eval": tool_m_eval,
    "pdb_m_repl": tool_m_repl,
    "pdb_dbfix": tool_dbfix,
    "pdb_mvm_spawn": tool_mvm_spawn,
    "pdb_mvm_tick": tool_mvm_tick,
    "pdb_mvm_list": tool_mvm_list,
    "pdb_mvm_kill": tool_mvm_kill,
    "pdb_mvm_mailbox_send": tool_mvm_mailbox_send,
    "pdb_mvm_mailbox_read": tool_mvm_mailbox_read,
}
