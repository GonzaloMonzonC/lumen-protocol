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
import json, logging, os, sqlite3, struct, sys, threading, time, hashlib
from pathlib import Path
from typing import Any, Optional

# MSM connection module — poner en path desde arranque, no en caliente
_msm_scripts = os.path.expanduser("~/Documents/GitHub/pdb-msm-importer/scripts")
if _msm_scripts not in sys.path:
    sys.path.insert(0, _msm_scripts)

# MVM — singleton global (VM de procesos M)
_mvm_instance = None
def __get_mvm():
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
_db_map_loaded = False
_atomic_ctx = threading.local()

_MAP_CFG_NS = "MAP_CFG"

def _load_db_map():
    """Load global mappings from the main PDB into _db_map."""
    global _db_map, _db_map_loaded
    if _db_map_loaded:
        return
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
                raw = r["value"]
                if isinstance(raw, bytes):
                    path = raw.decode("utf-8", errors="replace")
                elif isinstance(raw, str):
                    path = raw.strip('"')
                else:
                    path = str(raw) if raw else None
                if path:
                    _db_map[ns] = path
        _db_map_loaded = True
    except Exception:
        _db_map = {}
        _db_map_loaded = True

def _get_db_path() -> str:
    global _DB_PATH
    if _DB_PATH is None:
        _DB_PATH = (
            os.environ.get("PDB_PATH")
            or os.environ.get("PDB_DB")
            or str(Path(__file__).resolve().parent / "lumen-pdb.db")
        )
        # SQLite no crea directorios: asegura que el padre exista.
        parent = os.path.dirname(_DB_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)
    return _DB_PATH

def _apply_pragmas(c: sqlite3.Connection, busy_timeout: int = 5000) -> None:
    """PRAGMAs estándar para toda conexión PDB.
    WAL es persistente en la BD: no mezclar con journal_mode=DELETE
    (pdb_ttl.py también usa WAL — mantener consistente)."""
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute(f"PRAGMA busy_timeout={busy_timeout}")
    c.execute("PRAGMA cache_size=-8000")  # 8 MB
    c.execute("PRAGMA mmap_size=268435456")  # 256 MB

def pdb_connect(readonly: bool = False, timeout: float = 5.0, path: str = None) -> sqlite3.Connection:
    """Punto de entrada público del contrato PDB (Fase 1b).

    Única forma legítima de abrir una conexión SQLite al PDB fuera de este
    módulo: centraliza ruta (env PDB_PATH > PDB_DB > default), PRAGMAs (WAL)
    y, en el futuro, la elección de motor (PDB_ENGINE). Devuelve una conexión
    NUEVA que el llamante debe cerrar. Para operar sobre globals usa las
    tool_* de este módulo, que comparten conexión y aplican triggers/índices.

    readonly usa query_only (compatible con WAL, a diferencia de mode=ro
    por URI, que falla si -wal/-shm no existen).

    path: override explícito para tooling (migradores, inspección de
    copias). Por defecto, la BD canónica."""
    c = sqlite3.connect(path or _get_db_path(), timeout=timeout, check_same_thread=False)
    _apply_pragmas(c, busy_timeout=int(timeout * 1000))
    if readonly:
        c.execute("PRAGMA query_only=ON")
    c.row_factory = sqlite3.Row
    return c

def _get_conn(ns: str = None, subs: list = None) -> sqlite3.Connection:
    """Get a connection for the given namespace.
    If ns has subs and a partition config, routes to the correct partition.
    If ns has a global mapping, returns the mapped DB connection.
    Otherwise returns the default connection."""
    global _conn
    atomic_connection = getattr(_atomic_ctx, "connection", None)
    if atomic_connection is not None:
        return atomic_connection

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
    if ns and not _db_map_loaded:
        _load_db_map()
    if ns and _db_map:
        mapped_path = _db_map.get(ns)
        if mapped_path:
            # MSM mount: devolver MsmConnection en lugar de SQLite
            if mapped_path.upper().endswith('.MSM'):
                from msm_connection import MsmConnection
                return MsmConnection(mapped_path)
            
            # Normal SQLite connection
            if ns not in _db_connections:
                c = sqlite3.connect(mapped_path, timeout=5, check_same_thread=False)
                _apply_pragmas(c, busy_timeout=5000)
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
                _apply_pragmas(c, busy_timeout=30000)
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

def _maybe_commit(conn: sqlite3.Connection) -> None:
    """Commit unless a VM diff owns the surrounding SQLite transaction."""
    if not getattr(_atomic_ctx, "active", False):
        conn.commit()


def _publish_atomic_changes(connection: sqlite3.Connection, pending: list) -> None:
    """Publish CDC/event-route notifications after an atomic commit is visible."""
    for change_data, op, routed_value in pending:
        _publish_change(change_data)
        _check_event_routes(
            change_data["ns"],
            change_data["subs"],
            op,
            routed_value,
            connection,
        )


def _get_or_create_mapped_conn(key: str, path: str) -> sqlite3.Connection:
    """Get or create a connection for a mapped path. Used by mapping and partitioning."""
    if key in _db_connections:
        return _db_connections[key]
    c = sqlite3.connect(path, timeout=5, check_same_thread=False)
    _apply_pragmas(c, busy_timeout=5000)
    c.row_factory = sqlite3.Row
    _init_schema(c)
    _db_connections[key] = c
    return c

# _db_map loaded lazily in _get_conn() when ns is provided

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
            test.execute("PRAGMA journal_mode=WAL")
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
        test_conn.execute("PRAGMA journal_mode=WAL")
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
    """Create a consistent backup of the main PDB (SQLite Online Backup API,
    safe with concurrent writers under WAL — no checkpoint+copy race).
    Optionally specify backup path. Default: lumen-pdb.backup.db"""
    backup_path = args.get("backup_path", str(Path(_get_db_path()).parent / "lumen-pdb.backup.db"))
    try:
        c = _get_conn()
        dst = sqlite3.connect(backup_path)
        with dst:
            c.backup(dst)
        dst.close()
        size = os.path.getsize(backup_path)
        return {"success": True, "backup_path": backup_path, "size_bytes": size}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_m_eval(args: dict) -> dict:
    """Evaluate an M expression OR command using M-Light.
    Supports expressions: $GET, $DATA, $PIECE, $EXTRACT, $SELECT
    Supports commands: SET, FOR, KILL, IF, WRITE, $ORDER
    Examples:
        $GET(^PATIENT(42,"name"))
        $SELECT(1=1:"yes",1:"no")
        S I="" F  S I=$O(^FS(I)) Q:I=""  S ^SUM=$G(^SUM)+1
    """
    expr = args.get("expression", "")
    if not expr.strip():
        return {"success": False, "error": "Empty expression"}
    if os.environ.get("MLIGHT_ENGINE", "rust").lower() == "rust":
        try:
            from lumen_mlight import execute_sqlite
            response = execute_sqlite(
                expr,
                persist=args.get("persist", True),
                namespaces=args.get("namespaces"),
                gas_limit=int(args.get("gas_limit", 1000)),
                gas_budget=int(args.get("gas_budget", 0)),
            )
            state = response.get("state") or {}
            stack = state.get("stack") or []
            result = state.get("output") or (stack[-1] if stack else "")
            return {
                "success": response.get("ok", False),
                "expression": expr,
                "result": result,
                "mode": "rust_stackvm",
                "execution": response.get("execution"),
                "state": state,
                "error": response.get("error"),
            }
        except Exception as rust_error:
            if os.environ.get("MLIGHT_ENGINE_STRICT") == "1":
                return {
                    "success": False,
                    "expression": expr,
                    "error": f"Rust M-Light unavailable: {rust_error}",
                }
            logger.warning("Rust M-Light unavailable; Python fallback: %s", rust_error)
    try:
        import importlib.util, sys
        _m_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m_light.py")
        _m_spec = importlib.util.spec_from_file_location("m_light", _m_path)
        _m_mod = importlib.util.module_from_spec(_m_spec)
        _m_spec.loader.exec_module(_m_mod)
        encoder = _m_mod.MEvaluator(sys.modules[__name__])

        # Try as expression first (pure functions like $G, $P, etc.)
        # If it looks like a command (starts with S, K, F, I, W, D, G, N, O, U, C)
        # or contains '=', use eval instead of eval_expr
        first_word = expr.strip().split()[0].upper() if expr.strip() else ''
        is_command = first_word in ('S', 'K', 'F', 'I', 'W', 'D', 'G', 'N', 'O', 'U', 'C', 'SET', 'KILL', 'FOR', 'IF', 'WRITE', 'DO', 'GOTO', 'NEW', 'OPEN', 'USE', 'CLOSE', 'TSTART', 'TCOMMIT', 'TROLLBACK')
        has_assignment = '=' in expr and not expr.strip().startswith('$')

        if is_command or has_assignment:
            result = encoder.eval(expr)
            return {"success": True, "expression": expr, "result": str(result) if result is not None else "", "mode": "eval"}
        else:
            result = encoder.eval_expr(expr)
            return {"success": True, "expression": expr, "result": result, "mode": "eval_expr"}
    except Exception as e:
        # Fallback: try eval_expr if eval failed
        try:
            import importlib.util, sys
            _m_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "m_light.py")
            _m_spec = importlib.util.spec_from_file_location("m_light", _m_path)
            _m_mod = importlib.util.module_from_spec(_m_spec)
            _m_spec.loader.exec_module(_m_mod)
            encoder = _m_mod.MEvaluator(sys.modules[__name__])
            result = encoder.eval_expr(expr)
            return {"success": True, "expression": expr, "result": result, "mode": "eval_expr_fallback"}
        except Exception as e2:
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
    vm = __get_mvm()
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
    """Execute one tick of the MVM dispatcher. Runs all ready processes."""
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        max_per = args.get("max_per_process", 100)
        alive = vm.tick_all(max_per_process=max_per)
        procs = vm.list_processes()
        procs_info = [{"pid": p["pid"], "name": p["name"], "status": p["status"], "pc": p["pc"]} for p in procs]
        return {"success": True, "alive": alive, "total": len(procs_info), "processes": procs_info}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_list(args: dict) -> dict:
    """List all MVM processes and their status."""
    vm = __get_mvm()
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
    vm = __get_mvm()
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
    vm = __get_mvm()
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
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        msgs = vm.mailbox_read(pid)
        return {"success": True, "count": len(msgs), "messages": msgs}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── MVM Scheduler — HIBERNATE + auto-wake ──

def tool_mvm_sleep(args: dict) -> dict:
    """HIBERNATE a process for N seconds. Wakes automatically via ^SCHEDULE."""
    pid = args.get("pid")
    seconds = args.get("seconds", 60)
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    if not vm.sleep_process(pid, seconds):
        return {"success": False, "error": f"Process {pid} not found"}
    return {"success": True, "pid": pid, "status": "HIBERNATE",
            "wake_in_seconds": seconds}

def tool_mvm_wake(args: dict) -> dict:
    """Wake a HIBERNATE process manually."""
    pid = args.get("pid")
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    if not vm.wake_process(pid):
        return {"success": False, "error": f"Process {pid} not found or not HIBERNATE"}
    return {"success": True, "pid": pid, "status": "READY"}

def tool_mvm_schedule_list(args: dict) -> dict:
    """List all scheduled wake-ups (^SCHEDULE entries)."""
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    entries = []
    pid = ""
    while True:
        r = vm.pdb.tool_order({"ns": "SCHEDULE", "subs": [pid], "direction": 1})
        if r.get("value") is None:
            break
        pid = str(r["value"])
        val = vm.pdb.tool_get({"ns": "SCHEDULE", "subs": [pid]})
        try:
            wake_time = float(val.get("value", 0))
            entries.append({
                "pid": int(pid) if pid.isdigit() else pid,
                "wake_time": wake_time,
                "remaining": max(0, wake_time - time.time())
            })
        except (ValueError, TypeError):
            entries.append({"pid": pid, "wake_time": val.get("value", "?"), "remaining": -1})
    return {"success": True, "entries": entries, "count": len(entries)}

# ── Agent Outbox ─────────────────────────────────────────────────────────

def tool_mvm_outbox(args: dict) -> dict:
    """Read pending outbox messages from MVM processes."""
    limit = args.get("limit", 10)
    priority = args.get("priority", "")
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        messages = vm.outbox_read(limit=limit, priority=priority)
        return {"success": True, "messages": messages, "count": len(messages)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_outbox_ack(args: dict) -> dict:
    """Acknowledge an outbox message (mark as read)."""
    msg_id = args.get("msg_id")
    if msg_id is None:
        return {"success": False, "error": "msg_id required"}
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        ok = vm.outbox_ack(msg_id)
        return {"success": ok, "msg_id": msg_id,
                "message": "Acknowledged" if ok else "Message not found"}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_outbox_send(args: dict) -> dict:
    """Send a message to the agent outbox from an MVM process."""
    pid = args.get("pid")
    payload = args.get("payload", "")
    priority = args.get("priority", "normal")
    msg_type = args.get("type", "text")
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        msg_id = vm.outbox_send(pid, payload, priority=priority, msg_type=msg_type)
        return {"success": True, "msg_id": msg_id}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_mvm_outbox_cleanup(args: dict) -> dict:
    """Clean up acknowledged messages older than max_age."""
    max_age = args.get("max_age_secs", 86400)
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        vm.outbox_cleanup(max_age_secs=max_age)
        return {"success": True, "message": f"Cleaned up messages older than {max_age}s"}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── DBFIX ────────────────────────────────────────────────────────────────

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
    c.execute("""CREATE TABLE IF NOT EXISTS _event_routes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ns TEXT NOT NULL,
        subkey_pattern TEXT DEFAULT '',
        event_type TEXT NOT NULL DEFAULT '*',
        target_type TEXT NOT NULL DEFAULT 'mvm',
        target_id TEXT NOT NULL,
        active INTEGER DEFAULT 1,
        created_at REAL NOT NULL,
        UNIQUE(ns, subkey_pattern, event_type, target_type, target_id)
    )""")

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
            rows = []
            for row in cur.fetchall():
                safe = {}
                for k, v in dict(row).items():
                    if isinstance(v, bytes):
                        try:
                            safe[k] = v.decode('utf-8')
                        except UnicodeDecodeError:
                            safe[k] = v.hex()
                    else:
                        safe[k] = v
                rows.append(safe)
            return rows
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
        # Time-travel: save old value before overwriting
        row = c.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?", [ns, key]
        ).fetchone()
        if row and row["value"] is not None:
            _save_to_history(ns, subs, _decode_value(row["value"]), "SET", c)
        c.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [ns, key, _encode_value(value)]
        )
        _auto_index_on_set(ns, subs, c)
        _fire_triggers("ON_SET", ns, subs, value, c)
        _schema_auto_index_on_set(ns, subs, value, c)
        old_val = _decode_value(row["value"]) if row and row["value"] is not None else None
        _maybe_commit(c)
        _record_change(ns, subs, "SET", old_val, value, c)
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

def tool_has(args: dict) -> dict:
    """pdb_has(ns, subs) — devuelve True/False sin ambigüedades."""
    ns = args["ns"]; subs = args["subs"]
    try:
        key = encode_subkey(subs)
        c = _get_conn(ns, subs)
        row = c.execute(
            "SELECT 1 FROM _globals WHERE ns=? AND subkey=?", [ns, key]
        ).fetchone()
        return {"success": True, "value": row is not None}
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
                # Saltar el subárbol completo de `current` de un salto:
                # todo descendiente de full_key es < full_key+\xff (los
                # subkeys continúan con \x00/\x01/\x02), así que el índice
                # aterriza directo en el siguiente hermano en vez de
                # escanear fila a fila cada hijo (era O(subárbol) por paso).
                search_key = full_key + b'\xff'
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
        out_of_range = False
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
                if parent_key and not sk.startswith(parent_key):
                    # Índice ordenado: fuera del rango del padre ya no puede
                    # haber más matches — cortar (antes: continue, que
                    # escaneaba el namespace entero fila a fila).
                    out_of_range = True
                    break
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
                found_val = sub_val
                break
            if found_val is not None or out_of_range:
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
            # Nodo sin valor propio: tiene hijos ⟺ el primer subkey posterior
            # lleva `key` como prefijo (mismo criterio que el branch con valor)
            next_key = c.execute(
                "SELECT subkey FROM _globals WHERE ns=? AND subkey > ? ORDER BY subkey LIMIT 1",
                [ns, key]
            ).fetchone()
            if next_key:
                nk = next_key["subkey"]
                if len(nk) > len(key) and nk[:len(key)] == key:
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
        # Time-travel: save nodes before deleting
        rows = c.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? AND (subkey=? OR (subkey > ? AND subkey < ?))",
            [ns, key, key, key + b'\xff\xff\xff\xff']
        ).fetchall()
        for r in rows:
            child_subs = decode_subkey(r[0])
            if child_subs:
                _save_to_history(ns, child_subs, _decode_value(r[1]), "KILL", c)
        _auto_index_on_kill(ns, subs, c)
        _fire_triggers("ON_KILL", ns, subs, None, c)
        _schema_auto_index_on_kill(ns, subs, c)
        # Capture old values for CDC before deleting
        old_rows_data = []
        for r in rows:
            if r[0] and r[1] is not None:
                child_subs = decode_subkey(r[0])
                old_rows_data.append((child_subs, _decode_value(r[1])))
        # Delete the node itself
        c.execute("DELETE FROM _globals WHERE ns=? AND subkey=?", [ns, key])
        # Delete all children (keys that start with key and are longer)
        c.execute(
            "DELETE FROM _globals WHERE ns=? AND subkey > ? AND subkey < ?",
            [ns, key, key + b'\xff\xff\xff\xff']
        )
        _maybe_commit(c)
        for child_subs, child_val in old_rows_data:
            _record_change(ns, child_subs, "KILL", child_val, None, c)
        if not old_rows_data:
            _record_change(ns, subs, "KILL", None, None, c)
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_apply_batch(args: dict) -> dict:
    """Apply SET/KILL operations as one SQLite transaction.

    Used by the Rust M-Light snapshot adapter. Each mutation still traverses
    the normal history, trigger, index, CDC and FTS paths, but no intermediate
    commit is visible. Mapped/partitioned namespaces are rejected because a
    single SQLite transaction cannot span database files.
    """
    operations = args.get("operations", [])
    preconditions = args.get("preconditions", [])
    if not operations:
        return {"success": True, "operations": 0}
    main = _get_conn()
    for operation in operations:
        ns = operation.get("ns")
        subs = operation.get("subs", [])
        if _get_conn(ns, subs) is not main:
            return {
                "success": False,
                "error": "atomic VM diff cannot span mapped/partitioned databases",
            }

    connection = pdb_connect(timeout=30)
    pending = []
    batch_error = None
    try:
        connection.execute("BEGIN IMMEDIATE")
        _atomic_ctx.connection = connection
        _atomic_ctx.active = True
        _atomic_ctx.pending_changes = pending
        for expected in preconditions:
            key = encode_subkey(expected.get("subs", []))
            row = connection.execute(
                "SELECT value FROM _globals WHERE ns=? AND subkey=?",
                [expected["ns"], key],
            ).fetchone()
            found = row is not None and row["value"] is not None
            if found != expected.get("found", False):
                raise RuntimeError(
                    f"PDB_CONFLICT ^{expected['ns']}({expected.get('subs', [])}) existence changed"
                )
            if found and _decode_value(row["value"]) != expected.get("value"):
                raise RuntimeError(
                    f"PDB_CONFLICT ^{expected['ns']}({expected.get('subs', [])}) value changed"
                )
        for operation in operations:
            kind = operation.get("op", "").upper()
            payload = {"ns": operation["ns"], "subs": operation.get("subs", [])}
            if kind == "SET":
                payload["value"] = operation.get("value")
                result = tool_set(payload)
            elif kind == "KILL":
                result = tool_kill(payload)
            else:
                raise ValueError(f"unsupported batch operation: {kind}")
            if not result.get("success"):
                raise RuntimeError(result.get("error", f"{kind} failed"))
        connection.commit()
    except Exception as error:
        connection.rollback()
        batch_error = str(error)
    finally:
        _atomic_ctx.active = False
        _atomic_ctx.connection = None
        _atomic_ctx.pending_changes = []

    if batch_error is not None:
        connection.close()
        return {"success": False, "error": batch_error}

    try:
        _publish_atomic_changes(connection, pending)
    finally:
        connection.close()
    return {"success": True, "operations": len(operations)}

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
        _record_change(target_ns, target_subs, "MERGE", None,
                       {"source_ns": source_ns, "source_subs": source_subs,
                        "nodes_copied": 1 + len(child_rows)}, c)
        return {"success": True, "nodes_copied": 1 + len(child_rows)}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Time-travel — history & rollback
# ---------------------------------------------------------------------------

def tool_history(args: dict) -> dict:
    """Retrieve version history for a key. Returns list of {timestamp, value, op}."""
    ns = args["ns"]; subs = args["subs"]; limit = args.get("limit", 50)
    try:
        conn = _get_conn()
        # Find all history entries for this ns+subs path
        hist_ns = "HISTORY"
        hist_prefix = encode_subkey([ns] + subs)
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? AND subkey >= ? "
            "AND subkey < ? ORDER BY subkey DESC LIMIT ?",
            [hist_ns, hist_prefix, hist_prefix + b'\xff\xff\xff\xff', limit]
        ).fetchall()
        versions = []
        for r in rows:
            val = _decode_value(r["value"]) if r["value"] else {}
            if isinstance(val, str):
                try: val = json.loads(val)
                except: val = {"value": val}
            child_subs = decode_subkey(r["subkey"])
            ts = child_subs[-1] if len(child_subs) > len(subs) + 1 else ""
            versions.append({
                "timestamp": ts,
                "value": val.get("value"),
                "op": val.get("op", "SET"),
            })
        return {"success": True, "versions": versions, "count": len(versions)}
    except Exception as e:
        return {"success": False, "error": str(e)}

def tool_rollback(args: dict) -> dict:
    """Rollback a key to a previous version by timestamp."""
    ns = args["ns"]; subs = args["subs"]; timestamp = args["timestamp"]
    try:
        conn = _get_conn()
        hist_ns = "HISTORY"
        key = encode_subkey([ns] + subs + [timestamp])
        row = conn.execute(
            "SELECT value FROM _globals WHERE ns=? AND subkey=?", [hist_ns, key]
        ).fetchone()
        if not row or row["value"] is None:
            return {"success": False, "error": f"No history entry found at {timestamp}"}
        val = _decode_value(row["value"])
        if isinstance(val, str):
            val = json.loads(val)
        if val.get("op") == "KILL":
            # Key was killed at this point — restore means KILL the current value
            key_current = encode_subkey(subs)
            conn.execute(
                "DELETE FROM _globals WHERE ns=? AND subkey=?", [ns, key_current]
            )
        else:
            # Restore old value
            old_ns = ns; old_subs = subs
            tool_set({"ns": old_ns, "subs": old_subs, "value": val.get("value")})
        return {"success": True, "restored": val}
    except Exception as e:
        return {"success": False, "error": str(e)}


# ---------------------------------------------------------------------------
# Change Feed — CDC for agents
# ---------------------------------------------------------------------------

import time as _time

_subscribers: list = []  # list of (ns_pattern, callback)


def _publish_change(change_data: dict) -> None:
    """Notify in-process subscribers after the owning transaction commits."""
    if _subscribers:
        for pattern, callback in _subscribers:
            try:
                if _ns_matches(change_data["ns"], pattern):
                    callback(change_data)
            except Exception:
                pass
        _notify_watch_queues(change_data)


def _record_change(ns: str, subs: list, op: str, old_value, new_value, conn):
    """Record a mutation in ^CHANGES for CDC. Called after every SET/KILL/MERGE."""
    # Skip CHANGES and HISTORY namespaces to prevent self-referential bloat
    if ns == 'CHANGES' or ns == 'HISTORY':
        return
    # FIX task_49 (27-ago): no-op SETs (mismo valor) NO generan CDC. Antes cada SET
    # escribia una entrada con ts_ns unico aunque el valor no cambiara -> bloat
    # infinito (ej. watchdog de Angi escribiendo 3 metricas cada 5 min = 864/dia).
    if op == "SET" and old_value is not None and old_value == new_value:
        return
    try:
        ts_ns = _time.time_ns()
        ts_iso = _time.strftime("%Y-%m-%dT%H:%M:%S", _time.gmtime(ts_ns / 1_000_000_000))
        ts_iso += f".{ts_ns % 1_000_000_000:09d}Z"

        # Store in ^CHANGES(timestamp_ns, op, ns, ...subs)
        change_key = encode_subkey([ts_ns, op, ns] + list(subs))
        change_val_dict = {
            "old_value": old_value,
            "new_value": new_value,
            "timestamp": ts_iso,
            "op": op,
            "ns": ns,
            "subs": subs,
        }

        change_ns = "CHANGES"
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [change_ns, change_key, _encode_value(change_val_dict)]
        )
        _maybe_commit(conn)

        change_data = {
            "op": op, "ns": ns, "subs": subs,
            "old_value": old_value, "new_value": new_value,
            "timestamp": ts_iso, "timestamp_ns": ts_ns,
        }
        if getattr(_atomic_ctx, "active", False):
            _atomic_ctx.pending_changes.append(
                (change_data, op, new_value if op in ("SET", "MERGE") else None)
            )
        else:
            _publish_change(change_data)

        # FTS5 incremental index
        try:
            subkey_bytes = encode_subkey(subs)
            if op == "SET" and new_value is not None:
                rid = _fts_rowid(ns, subkey_bytes)
                conn.execute(
                    "INSERT OR REPLACE INTO _fts(rowid, ns, value) VALUES (?, ?, ?)",
                    [rid, ns, str(new_value)]
                )
            elif op == "KILL":
                rid = _fts_rowid(ns, subkey_bytes)
                conn.execute("DELETE FROM _fts WHERE rowid=?", [rid])
            _maybe_commit(conn)
        except Exception:
            pass  # FTS failure never breaks primary write
        if not getattr(_atomic_ctx, "active", False):
            _check_event_routes(
                ns,
                subs,
                op,
                new_value if op in ("SET", "MERGE") else None,
                conn,
            )
    except Exception:
        pass  # CDC failure must never break the primary write


import fnmatch as _fnmatch

def _ns_matches(ns: str, pattern: str) -> bool:
    """Glob match for namespace patterns. Supports:
    - '*' matches everything
    - 'STATE:*' matches STATE AND STATE:global AND STATE:global:objective
    - 'PATIENT*' matches PATIENT, PATIENT_IDX
    - Exact match: 'STATE' matches only STATE
    """
    if pattern == "*":
        return True
    # 'NS:*' pattern: matches NS AND NS:anything
    if pattern.endswith(":*"):
        prefix = pattern[:-2]  # remove ':*'
        if ns == prefix:
            return True
        if ns.startswith(prefix + ":"):
            return True
        # Also try fnmatch for cases like 'STATE:*:goal_*'
        return _fnmatch.fnmatch(ns, pattern)
    # Standard glob
    return _fnmatch.fnmatch(ns, pattern)


# Streaming $Q — background thread for watch()
import threading as _threading
import queue as _queue_module

_watch_queues: list = []  # list of (ns_pattern, queue)
_watch_lock = _threading.Lock()


def _notify_watch_queues(change_data: dict):
    """Notify watch queues of a matching change."""
    ns = change_data.get("ns", "")
    with _watch_lock:
        for pattern, q in _watch_queues:
            if _ns_matches(ns, pattern):
                try:
                    q.put_nowait(change_data)
                except _queue_module.Full:
                    pass  # drop if queue full


def tool_watch(args: dict) -> dict:
    """Block until a change matching ns_pattern occurs, or timeout expires.
    Returns the change dict, or None on timeout."""
    ns_pattern = args.get("ns_pattern", "*")
    timeout = args.get("timeout", 30)  # seconds, 0 = no timeout

    q: _queue_module.Queue = _queue_module.Queue(maxsize=100)
    with _watch_lock:
        _watch_queues.append((ns_pattern, q))

    try:
        change = q.get(timeout=timeout if timeout > 0 else None)
        return {"success": True, "change": change, "found": True}
    except _queue_module.Empty:
        return {"success": True, "change": None, "found": False, "timeout": True}
    finally:
        with _watch_lock:
            _watch_queues[:] = [(p, qq) for p, qq in _watch_queues if qq is not q]


def tool_q_subscribe(args: dict) -> dict:
    """Register a persistent subscription in ^SUBSCRIPTIONS.
    Survives restarts. Changes are accumulated and can be fetched later."""
    ns_pattern = args.get("ns_pattern", "*")
    label = args.get("label", f"sub_{_time.time_ns()}")

    try:
        conn = _get_conn()
        sub_key = encode_subkey([label])
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            ["SUBSCRIPTIONS", sub_key, _encode_value({
                "ns_pattern": ns_pattern,
                "label": label,
                "created": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
                "last_seen": None,
            })]
        )
        conn.commit()
        return {"success": True, "subscription_id": label, "ns_pattern": ns_pattern}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_q_unsubscribe(args: dict) -> dict:
    """Remove a persistent subscription from ^SUBSCRIPTIONS."""
    label = args.get("label")

    try:
        conn = _get_conn()
        sub_key = encode_subkey([label])
        conn.execute(
            "DELETE FROM _globals WHERE ns='SUBSCRIPTIONS' AND subkey=?",
            [sub_key]
        )
        conn.commit()
        return {"success": True}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_q_list(args: dict = None) -> dict:
    """List all persistent subscriptions from ^SUBSCRIPTIONS."""
    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns='SUBSCRIPTIONS' ORDER BY subkey"
        ).fetchall()
        subs = []
        for r in rows:
            val = _decode_value(r["value"])
            if isinstance(val, str):
                try: val = json.loads(val)
                except: val = {"raw": val}
            subs.append(val)
        return {"success": True, "subscriptions": subs, "count": len(subs)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_changes(args: dict) -> dict:
    """Return all changes since a given timestamp_ns. Polling API for agents."""
    since = args.get("since", 0)
    limit = args.get("limit", 100)
    ns_filter = args.get("ns")  # optional namespace filter

    try:
        conn = _get_conn()
        change_ns = "CHANGES"
        since_key = encode_subkey([since]) if since else b""

        if ns_filter:
            # Filter at SQL level using json_extract
            rows = conn.execute(
                "SELECT subkey, value FROM _globals WHERE ns=? AND subkey > ? "
                "AND json_extract(value, '$.ns') = ? "
                "ORDER BY subkey ASC LIMIT ?",
                [change_ns, since_key, ns_filter, limit]
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT subkey, value FROM _globals WHERE ns=? AND subkey > ? "
                "ORDER BY subkey ASC LIMIT ?",
                [change_ns, since_key, limit]
            ).fetchall()

        changes = []
        for r in rows:
            val = _decode_value(r["value"])
            if isinstance(val, str):
                try: val = json.loads(val)
                except: val = {"raw": val}
            changes.append(val)

        return {"success": True, "changes": changes, "count": len(changes)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_subscribe(args: dict) -> dict:
    """Register a subscription for changes matching a namespace pattern.
    Callback is stored in-process. Returns subscriber ID for unsubscribe."""
    ns_pattern = args.get("ns_pattern", "*")
    # For Hermes tools, callback is stored in the subscriber list.
    # In-process consumers call pdb_subscribe() directly from Python.
    sub_id = f"sub_{_time.time_ns()}"
    # Store for in-process use — Hermes agents access via the bridge
    _subscribers.append((ns_pattern, lambda change: None))  # placeholder
    return {"success": True, "subscriber_id": sub_id, "ns_pattern": ns_pattern}


def tool_unsubscribe(args: dict) -> dict:
    """Remove a subscription by ID."""
    sub_id = args.get("subscriber_id")
    # Simple: just clear all (subscriptions are ephemeral)
    global _subscribers
    _subscribers = [(p, cb) for p, cb in _subscribers if cb.__name__ != sub_id]
    return {"success": True}


# In-process subscription (called directly from Python agents)
def pdb_subscribe(ns_pattern: str, callback):
    """Subscribe to changes matching ns_pattern. callback(change_dict)."""
    _subscribers.append((ns_pattern, callback))
    return len(_subscribers) - 1


def pdb_unsubscribe(index: int):
    """Remove subscription by index (returned by pdb_subscribe)."""
    if 0 <= index < len(_subscribers):
        _subscribers.pop(index)
        return True
    return False


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


def tool_context_gc(args: dict = None) -> dict:
    """Cognitive GC — prune ^CONTEXT trees that exceed depth/volume.
    
    Scans ^CONTEXT(session_id, turn_id, ...) for sessions deeper than
    max_depth. Summarizes the oldest N turns using deterministic heuristics
    (no LLM), stores the summary at ^CONTEXT(session_id, "summary"),
    and KILLs the old branches. Designed to run periodically as MVM cron.
    
    Returns stats on GC actions taken."""
    import time as _gc_t
    c = _get_conn()
    max_depth = (args or {}).get("max_depth", 50)
    max_age = (args or {}).get("max_age_secs", 3600)  # 1h
    dry_run = (args or {}).get("dry_run", False)
    
    try:
        # Find all sessions in ^CONTEXT
        sessions = set()
        rows = c.execute(
            "SELECT DISTINCT substr(subkey, 2, instr(subkey, X'FF')-2) as session_id "
            "FROM _globals WHERE ns='CONTEXT'"
        ).fetchall()
        
        pruned = 0
        summarized = 0
        
        for row in rows:
            sid = row[0]
            if isinstance(sid, bytes):
                sid = sid.decode('utf-8', errors='replace')
            
            # Count turns in this session
            prefix = chr(2) + sid + chr(255) + chr(2)  # {sid}ÿ
            turns = c.execute(
                "SELECT subkey, value FROM _globals WHERE ns='CONTEXT' "
                "AND substr(subkey, 1, ?)=? AND value IS NOT NULL",
                [len(prefix), prefix]
            ).fetchall()
            
            if len(turns) > max_depth:
                # Session too deep — summarise oldest turns
                to_prune = turns[:len(turns) - max_depth]
                keep = turns[len(turns) - max_depth:]
                
                # Build deterministic summary of pruned turns
                summary_parts = []
                for t in to_prune:
                    val = t["value"]
                    if val:
                        try:
                            text = val.decode('utf-8', errors='replace')
                            if len(text) > 100:
                                text = text[:100] + "..."
                            summary_parts.append(text)
                        except:
                            pass
                
                summary = " | ".join(summary_parts) if summary_parts else "(summarized)"
                summary = summary[:2000]  # cap length
                
                if not dry_run:
                    # Store summary
                    summary_key = chr(2) + sid + chr(255) + chr(2) + "summary" + chr(255)
                    c.execute(
                        "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                        ['CONTEXT', summary_key.encode() if isinstance(summary_key, str) else summary_key, summary]
                    )
                    # Kill old turns
                    for t in to_prune:
                        c.execute("DELETE FROM _globals WHERE ns='CONTEXT' AND subkey=?", [t["subkey"]])
                    summarized += 1
                    pruned += len(to_prune)
        
        c.commit()
        return {"success": True, "pruned": pruned, "summarized": summarized,
                "sessions_scanned": len(sessions)}
    except Exception as e:
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

def _fts_rowid(ns: str, subkey: bytes) -> int:
    """Deterministic rowid from ns+subkey for incremental FTS5 maintenance."""
    return int(hashlib.md5(ns.encode() + b":" + subkey).hexdigest()[:8], 16)


def tool_fts_search(args: dict) -> dict:
    """Full-text search using SQLite FTS5 with incremental hash-based index.

    No full rebuild on each call. Index maintained incrementally via
    _record_change() hook on every SET/KILL/MERGE."""
    query = args["query"]
    limit = args.get("limit", 10)
    ns_filter = args.get("ns")
    c = _get_conn()
    try:
        # Create FTS5 table on first call (standalone, hash-based rowid)
        c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS _fts USING fts5(
            ns, value, tokenize='unicode61'
        )""")

        # One-time rebuild for existing data (only if not migrated)
        migrated = c.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='_fts_migrated'"
        ).fetchone()
        if not migrated:
            n_reindexed = 0
            rows = c.execute(
                "SELECT ns, subkey, value FROM _globals WHERE value IS NOT NULL AND value != ''"
            ).fetchall()
            for r in rows:
                rid = _fts_rowid(r["ns"], r["subkey"])
                c.execute("INSERT OR REPLACE INTO _fts(rowid, ns, value) VALUES (?, ?, ?)",
                         [rid, r["ns"], str(r["value"])])
                n_reindexed += 1
            c.execute("CREATE TABLE IF NOT EXISTS _fts_migrated (v INTEGER)")
            c.execute("INSERT INTO _fts_migrated VALUES (1)")
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
# Time-travel — value history
# ---------------------------------------------------------------------------

_HISTORY_NS = "HISTORY"

def _save_to_history(ns: str, subs: list, old_value, op: str, conn):
    """Save old value to ^HISTORY before SET/KILL mutates it.
    Key: ^HISTORY(ns, sub1, ..., timestamp) = {value, op}"""
    # Skip transient/volatile namespaces to prevent history bloat
    if ns.startswith('batch_') or ns.startswith('bench_') or ns.startswith('_tmp_'):
        return
    ts = f"t{int(time.time()*1000000)}"
    hist_key = encode_subkey([ns] + subs + [ts])
    entry = json.dumps({"value": old_value, "op": op, "ns": ns, "subs": subs})
    conn.execute(
        "INSERT INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
        [_HISTORY_NS, hist_key, entry.encode()]
    )


# ---------------------------------------------------------------------------
# Auto-indices — MUMPS-style ^IDX maintained automatically
# ---------------------------------------------------------------------------
# Define an index: ^INDEX_CFG(ns, idx_name) = {"sub_pos": N}
# tells PDB: "when ^ns(..., value_at_pos_N) changes, update ^IDX_ns_idx_name"
# On SET: auto-creates ^_IDX_{ns}_{idx_name}(extracted_value, parent_subs...) = ""
# On KILL: auto-deletes matching index entries

_INDEX_CFG_NS = "INDEX_CFG"
_INDEX_DATA_NS_PREFIX = "_IDX"
_SCHEMA_NS = "SCHEMA"

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

# ── Schema-based auto-index (flat-mapping pattern) ──
# ^SCHEMA("ENTRY") = "campo1,campo2,campo3" defines fields for ^ENTRY(id)="val1^val2^val3"
# On SET: auto-creates ^_IDX_ENTRY_campo1("val1", id) = "" for each field
# On KILL: auto-deletes matching index entries

def _load_schema(ns: str) -> list[str] | None:
    """Load flat-map schema for a namespace from ^SCHEMA(ns).
    Returns list of field names or None if no schema defined."""
    conn = _get_conn()
    key = encode_subkey([ns])
    row = conn.execute(
        "SELECT value FROM _globals WHERE ns=? AND subkey=?", [_SCHEMA_NS, key]
    ).fetchone()
    if row and row["value"] is not None:
        fields = _decode_value(row["value"])
        if isinstance(fields, str):
            return [f.strip() for f in fields.split(",")]
    return None

def _schema_auto_index_on_set(ns: str, subs: list, value, conn):
    """Create reverse indexes from flat-mapped values based on ^SCHEMA."""
    schema = _load_schema(ns)
    if not schema or not isinstance(value, str) or "^" not in value:
        return
    parts = value.split("^")
    if len(parts) != len(schema):
        return  # Schema mismatch — skip indexing
    for i, field_name in enumerate(schema):
        field_val = parts[i].strip()
        if not field_val:
            continue
        idx_ns = f"{_INDEX_DATA_NS_PREFIX}_{ns}_{field_name}"
        # Index: field_value + orig_subs (id as tiebreaker for duplicates)
        idx_key = encode_subkey([field_val] + subs)
        subs_hash = abs(hash(str(subs))) % 10_000_000
        idx_val = f"{subs_hash}:{json.dumps({'orig_subs': subs})}".encode()
        conn.execute(
            "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
            [idx_ns, idx_key, idx_val]
        )

def _schema_auto_index_on_kill(ns: str, subs: list, conn):
    """Clean up schema-based reverse indexes on KILL."""
    schema = _load_schema(ns)
    if not schema:
        return
    for field_name in schema:
        idx_ns = f"{_INDEX_DATA_NS_PREFIX}_{ns}_{field_name}"
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=?", [idx_ns]
        ).fetchall()
        for r in rows:
            if r[1] is None:
                continue
            try:
                colon_pos = r[1].find(b':')
                if colon_pos < 0:
                    continue
                payload = r[1][colon_pos+1:]
                val = json.loads(payload.decode("utf-8", errors="replace"))
                stored_subs = val.get("orig_subs", [])
                if len(stored_subs) >= len(subs) and stored_subs[:len(subs)] == subs:
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

def _init_locks_table():
    """Create the multi-process lock table if not exists."""
    try:
        c = _get_conn()
        c.execute("""CREATE TABLE IF NOT EXISTS _lock_table (
            key TEXT PRIMARY KEY,
            owner TEXT NOT NULL,
            acquired_at REAL NOT NULL,
            expires_at REAL
        )""")
        c.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        pass

def _acquire_sqlite_lock(key: str, owner: str, timeout: float = None) -> bool:
    """Acquire a named lock via SQLite INSERT (UNIQUE constraint = lock contention).
    Multi-process safe. Returns True if acquired, False if timeout.
    timeout=None blocks indefinitely; timeout=0 makes exactly one attempt
    (the MVM uses that non-blocking probe and retries cooperatively).
    Re-acquiring a key already held by the same owner succeeds (reentrant)."""
    import time as _lt
    _init_locks_table()
    deadline = _lt.time() + timeout if timeout is not None else float('inf')

    while True:
        try:
            c = _get_conn()
            # Clean stale locks first (own transaction)
            c.execute("DELETE FROM _lock_table WHERE expires_at IS NOT NULL AND expires_at < ?",
                     [_lt.time()])
            c.commit()

            # Try to INSERT — UNIQUE constraint on key acts as the lock
            try:
                c.execute(
                    "INSERT INTO _lock_table(key, owner, acquired_at) VALUES (?, ?, ?)",
                    [key, owner, _lt.time()]
                )
                c.commit()
                return True
            except Exception:
                # Lock held — rollback; reentrada del mismo owner cuenta como adquirido
                try:
                    c.rollback()
                except Exception:
                    pass
                row = c.execute(
                    "SELECT owner FROM _lock_table WHERE key=?", [key]
                ).fetchone()
                if row and row["owner"] == owner:
                    return True
                if _lt.time() >= deadline:
                    return False
                _lt.sleep(0.05)
        except Exception:
            if _lt.time() >= deadline:
                return False
            _lt.sleep(0.1)
def _release_sqlite_lock(key: str, owner: str):
    """Release a named lock by deleting its row."""
    try:
        c = _get_conn()
        c.execute("BEGIN EXCLUSIVE")
        c.execute("DELETE FROM _lock_table WHERE key=? AND owner=?", [key, owner])
        c.commit()
    except Exception:
        pass

def tool_lock(args: dict) -> dict:
    """LOCK ^ns(subs) — acquire a resource lock. Multi-process safe via SQLite.
    args["owner"] overrides the default pid_threadid owner (MVM jobs pass mvm_<pid>)."""
    ns = args["ns"]
    subs = args.get("subs", [])
    timeout = args.get("timeout", None)  # None = block indefinitely
    key = _lock_key(ns, subs)
    owner = args.get("owner") or f"{os.getpid()}_{threading.get_native_id()}"

    # Try SQLite multi-process lock first
    acquired = _acquire_sqlite_lock(key, owner, timeout)
    if acquired:
        return {"success": True, "locked": True,
                "key": key, "owner": owner}
    else:
        return {"success": False, "locked": False,
                "key": key, "error": "timeout"}

def tool_unlock(args: dict) -> dict:
    """UNLOCK ^ns(subs) — release a specific lock. If no args, releases all held by this process.
    args["owner"] overrides the default pid_threadid owner (MVM jobs pass mvm_<pid>)."""
    ns = args.get("ns")
    subs = args.get("subs", [])
    all_flag = args.get("all", False)
    owner = args.get("owner") or f"{os.getpid()}_{threading.get_native_id()}"

    if all_flag or ns is None:
        try:
            c = _get_conn()
            c.execute("DELETE FROM _lock_table WHERE owner=?", [owner])
            c.commit()
            return {"success": True, "released": True, "owner": owner}
        except Exception:
            return {"success": False, "error": "failed to release locks"}

    key = _lock_key(ns, subs)
    _release_sqlite_lock(key, owner)
    return {"success": True, "released": True, "key": key}


# ---------------------------------------------------------------------------
# Embedding (RAG) tools
# Requires: pip install fastembed
# Uses: sentence-transformers/all-MiniLM-L6-v2 (384 dims)

_EMBED_MODEL = None
_EMBED_DIMS = 384
_EMBED_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
_EMBED_MATRIX = None  # numpy array cache
_EMBED_HASHES = None  # list of hash strings
_vec_initialized = False


def _init_vec():
    """One-time init of sqlite-vec extension and vec0 tables."""
    global _vec_initialized
    if _vec_initialized:
        return
    try:
        import sqlite_vec
        c = _get_conn()
        c.enable_load_extension(True)
        sqlite_vec.load(c)
        # Standalone vec0 table (OBJ-6k — general vector search)
        c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS _vec_embeddings USING vec0(
            embedding float[384] distance_metric=cosine,
            hash text +,
            text text +,
            source text +
        )""")
        # Hierarchical vec0 table (OBJ-7b — RAG with partition key)
        c.execute("""CREATE VIRTUAL TABLE IF NOT EXISTS _vec_hierarchical USING vec0(
            embedding float[384] distance_metric=cosine,
            path text partition key,
            hash text +,
            text text +,
            source text +
        )""")
        _vec_initialized = True
    except Exception:
        pass  # graceful fallback if sqlite-vec not installed

def _get_embedder():
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        try:
            from fastembed import TextEmbedding
            _EMBED_MODEL = TextEmbedding(_EMBED_MODEL_NAME)
        except ImportError:
            raise ImportError("fastembed not installed. Run: pip install fastembed")
    return _EMBED_MODEL

def tool_embed(args: dict) -> dict:
    """Generate embeddings for text(s) and store in PDB."""
    texts = args.get("texts", args.get("text", ""))
    source = args.get("source", "")
    if isinstance(texts, str):
        texts = [texts]
    import hashlib, time
    global _EMBED_MATRIX, _EMBED_HASHES
    model = _get_embedder()
    results = []
    cache_stale = _EMBED_MATRIX is not None  # only invalidate if matrix already loaded
    for text, emb in zip(texts, list(model.embed(texts))):
        h = hashlib.sha256(text.encode()).hexdigest()[:16]
        if cache_stale and (_EMBED_HASHES is None or h not in _EMBED_HASHES):
            # New content while the numpy matrix is cached → force rebuild on next search
            _EMBED_MATRIX = None
            _EMBED_HASHES = None
            cache_stale = False
        items = [{"ns": "EMBED", "subs": [h, dim], "value": str(round(float(v), 6))} for dim, v in enumerate(emb)]
        items += [{"ns": "EMBED_META", "subs": [h, "text"], "value": text},
                  {"ns": "EMBED_META", "subs": [h, "source"], "value": source or ""},
                  {"ns": "EMBED_META", "subs": [h, "created"], "value": str(time.time())}]
        # Full vector as single JSON array for fast numpy loading (search matrix)
        items.append({"ns": "EMBED_VEC", "subs": [h], "value": [round(float(v), 6) for v in emb]})
        tool_batch_set({"items": items})
        # Also store in sqlite-vec for KNN search
        try:
            _init_vec()
            import json as _vj
            c = _get_conn()
            c.execute(
                "INSERT OR REPLACE INTO _vec_embeddings(rowid, embedding, hash, text, source) "
                "VALUES (?, ?, ?, ?, ?)",
                [int(h, 16) % (1 << 62), _vj.dumps([round(float(v), 6) for v in emb]),
                 h, text, source or ""]
            )
            # Also store in hierarchical vec0 with path partition key
            path = source or "general"
            c.execute(
                "INSERT OR REPLACE INTO _vec_hierarchical(rowid, embedding, path, hash, text, source) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                [int(h, 16) % (1 << 62), _vj.dumps([round(float(v), 6) for v in emb]),
                 path, h, text, source or ""]
            )
        except Exception:
            pass  # sqlite-vec failure doesn't break primary storage
        results.append({"hash": h, "dims": len(emb), "source": source})
    return {"success": True, "results": results, "count": len(results)}

def tool_embed_search(args: dict) -> dict:
    """Search indexed texts by cosine similarity."""
    query = args.get("query", "")
    limit = min(args.get("limit", 5), 50)
    if not query:
        return {"success": False, "error": "query required"}
    import math
    model = _get_embedder()
    q_emb = list(model.embed([query]))[0]
    q_vec = [float(q_emb[i]) for i in range(_EMBED_DIMS)]
    q_norm = math.sqrt(sum(v*v for v in q_vec))
    if q_norm > 0:
        q_vec = [v/q_norm for v in q_vec]
    c = _get_conn()

    # Cached vector matrix: load once, reuse across calls
    import json as _j
    global _EMBED_MATRIX, _EMBED_HASHES
    if _EMBED_MATRIX is None:
        cur = c.execute("SELECT subkey, value FROM _globals WHERE ns='EMBED_VEC'")
        hashes = []
        vecs = []
        for sk, val in cur.fetchall():
            try:
                decoded = decode_subkey(sk)
            except:
                continue
            if not decoded: continue
            hashes.append(str(decoded[0]))
            raw = val.decode('utf-8') if isinstance(val, bytes) else str(val)
            try:
                vecs.append(_j.loads(raw))
            except:
                continue
        _EMBED_HASHES = hashes
        if not vecs:
            _EMBED_MATRIX = None
            return {"success": True, "results": [], "total": 0}
        _EMBED_MATRIX = __import__('numpy', fromlist=['']).array(vecs, dtype='float32')

    # Early return if no vectors indexed
    if _EMBED_MATRIX is None or len(_EMBED_HASHES) == 0:
        return {"success": True, "results": [], "total": 0}

    # Vectorized cosine similarity
    import numpy as np
    norms = np.linalg.norm(_EMBED_MATRIX, axis=1)
    dots = _EMBED_MATRIX @ q_vec
    scores = dots / (norms * q_norm)
    top_idx = np.argsort(scores)[-limit:][::-1]

    scored = []
    for idx in top_idx:
        h = _EMBED_HASHES[idx]
        score = float(scores[idx])
        # Read metadata by exact subkey labels (text/source/created) — no heuristics
        hb = h.encode("utf-8") if isinstance(h, str) else h
        cur2 = c.execute("SELECT subkey, value FROM _globals WHERE ns='EMBED_META' AND substr(subkey, 2, 16)=?", [hb])
        meta = {}
        for sk2, val in cur2.fetchall():
            if val is None:
                continue
            raw = val.decode("utf-8") if isinstance(val, bytes) else str(val)
            try:
                parts = decode_subkey(sk2)
            except Exception:
                continue
            if len(parts) >= 2:
                # Values are stored JSON-encoded via _encode_value (json.dumps)
                try:
                    decoded = _j.loads(raw)
                except Exception:
                    decoded = raw
                meta[str(parts[1])] = decoded if isinstance(decoded, str) else raw
        scored.append({"hash": h, "text": meta.get("text", ""), "source": meta.get("source", ""), "score": round(score, 4)})
    scored.sort(key=lambda x: -x["score"])
    return {"success": True, "results": scored[:limit], "count": len(scored[:limit])}


def tool_vec_search(args: dict) -> dict:
    """Search embeddings by cosine similarity using sqlite-vec KNN index.

    Optimized with partition key when 'path' is provided — only searches
    the relevant shard instead of the whole index (hierarchical RAG).
    Falls back to numpy-based tool_embed_search if sqlite-vec unavailable."""
    query = args.get("query", "")
    limit = min(args.get("limit", 5), 50)
    path = args.get("path", "")
    if not query:
        return {"success": False, "error": "query required"}
    try:
        _init_vec()
        import math, json as _vj
        model = _get_embedder()
        q_emb = list(model.embed([query]))[0]
        q_json = _vj.dumps([float(v) for v in q_emb])
        c = _get_conn()

        if path:
            # Hierarchical RAG: use partition key for O(log N) search
            table = "_vec_hierarchical"
            if path.endswith("*"):
                # Prefix match: strip "*" and use prefix filter
                prefix = path[:-1]
                sql = (
                    f"SELECT rowid, distance, hash, text, source FROM {table} "
                    f"WHERE embedding MATCH ? AND substr(path, 1, ?)=? ORDER BY distance LIMIT ?"
                )
                rows = c.execute(sql, (q_json, len(prefix), prefix, limit))
            else:
                # Exact partition match
                sql = (
                    f"SELECT rowid, distance, hash, text, source FROM {table} "
                    f"WHERE embedding MATCH ? AND path=? ORDER BY distance LIMIT ?"
                )
                rows = c.execute(sql, (q_json, path, limit))
        else:
            # Full search (no partition filter)
            table = "_vec_embeddings"
            sql = (
                f"SELECT rowid, distance, hash, text, source FROM {table} "
                f"WHERE embedding MATCH ? ORDER BY distance LIMIT ?"
            )
            rows = c.execute(sql, (q_json, limit))

        results = []
        for r in rows:
            results.append({
                "hash": r["hash"],
                "text": r["text"],
                "score": round(1.0 - r["distance"], 4),
                "source": r["source"],
            })
        return {"success": True, "results": results, "count": len(results)}
    except Exception as e:
        # Fallback to numpy-based search
        return tool_embed_search(args)



# ── Event Routes — PDB → MVM event-driven cognition (OBJ-7d) ──

def _init_event_routes():
    """Create _event_routes table if not exists."""
    try:
        c = _get_conn()
        c.execute("""CREATE TABLE IF NOT EXISTS _event_routes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ns TEXT NOT NULL,
            subkey_pattern TEXT DEFAULT '',
            event_type TEXT NOT NULL DEFAULT '*',
            target_type TEXT NOT NULL DEFAULT 'mvm',
            target_id TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            created_at REAL NOT NULL,
            UNIQUE(ns, subkey_pattern, event_type, target_type, target_id)
        )""")
        c.execute("PRAGMA wal_checkpoint(PASSIVE)")
    except Exception:
        pass

# Cache of active routes: refreshed on each call, not per SET
_event_route_cache = None  # list of dicts or None = needs refresh
_event_route_cache_time = 0.0
_EVENT_CACHE_TTL = 2.0  # seconds before refresh

def _refresh_event_route_cache():
    """Refresh the event route cache from DB."""
    global _event_route_cache, _event_route_cache_time
    import time as _t
    now = _t.time()
    if _event_route_cache is not None and now - _event_route_cache_time < _EVENT_CACHE_TTL:
        return _event_route_cache
    try:
        c = _get_conn()
        try:
            rows = c.execute(
                "SELECT id, ns, subkey_pattern, event_type, target_type, target_id, active FROM _event_routes WHERE active=1"
            ).fetchall()
        except Exception:
            # Table may not exist in this connection (mapped/partitioned)
            _init_event_routes()
            rows = c.execute(
                "SELECT id, ns, subkey_pattern, event_type, target_type, target_id, active FROM _event_routes WHERE active=1"
            ).fetchall()
        _event_route_cache = [dict(r) for r in rows]
        _event_route_cache_time = now
        return _event_route_cache
    except Exception:
        return _event_route_cache or []

_in_event_delivery = False  # anti-reentrance flag

def _check_event_routes(ns: str, subs: list, op: str, value, conn):
    """Check active event routes and deliver matching events to MVM mailbox.
    Called from _record_change() after CDC write.
    Designed to be fast: uses cached routes, no SQL per event.
    """
    global _in_event_delivery
    if _in_event_delivery:
        return  # prevent re-entrant loops
    _in_event_delivery = True
    try:
        routes = _refresh_event_route_cache()
        if not routes:
            return
        import time as _t
        import json as _j

        # Build event payload once
        payload = _j.dumps({
            "__pdb_event__": True,
            "op": op,
            "ns": ns,
            "subs": list(subs),
            "value": str(value) if value is not None else None,
            "timestamp": _t.time(),
        })

        for route in routes:
            try:
                # NS match: exact or '*'
                if route["ns"] != "*" and route["ns"] != ns:
                    continue
                # Event type match
                if route["event_type"] != "*" and route["event_type"] != op:
                    continue
                # Subkey pattern match (fnmatch on stringified subs)
                if route["subkey_pattern"]:
                    sub_str = "/".join(str(s) for s in subs)
                    import fnmatch as _fn
                    if not _fn.fnmatch(sub_str, route["subkey_pattern"]):
                        continue
                # Deliver to target
                if route["target_type"] == "mvm":
                    vm = __get_mvm()
                    if vm:
                        vm.mailbox_send(route["target_id"], payload)
                # (future: webhook, log, etc.)
            except Exception:
                pass  # single route failure never breaks others
    finally:
        _in_event_delivery = False


# ── Tool: pdb_event_route_define ──

def tool_event_route_define(args: dict) -> dict:
    """Define an event route: ns changes → MVM mailbox delivery."""
    import time as _t
    ns = args.get("ns", "*")
    subkey_pattern = args.get("subkey_pattern", "")
    event_type = args.get("event_type", "*")
    target_type = args.get("target_type", "mvm")
    target_id = args.get("target_id", "")
    if not target_id:
        return {"success": False, "error": "target_id required"}
    _init_event_routes()
    try:
        c = _get_conn()
        c.execute(
            "INSERT OR IGNORE INTO _event_routes(ns, subkey_pattern, event_type, target_type, target_id, active, created_at) VALUES (?, ?, ?, ?, ?, 1, ?)",
            [ns, subkey_pattern, event_type, target_type, target_id, _t.time()]
        )
        c.commit()
        # Get the inserted id
        row = c.execute("SELECT last_insert_rowid()").fetchone()
        rid = row[0] if row else 0
        # Invalidate cache
        global _event_route_cache
        _event_route_cache = None
        return {"success": True, "route_id": rid, "ns": ns}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_event_route_remove(args: dict) -> dict:
    """Remove an event route by id."""
    rid = args.get("route_id", 0)
    if not rid:
        return {"success": False, "error": "route_id required"}
    _init_event_routes()
    try:
        c = _get_conn()
        c.execute("DELETE FROM _event_routes WHERE id=?", [rid])
        c.commit()
        global _event_route_cache
        _event_route_cache = None
        return {"success": True, "route_id": rid}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_event_route_list(args: dict) -> dict:
    """List event routes, optionally filtered by ns."""
    ns = args.get("ns", None)
    _init_event_routes()
    try:
        c = _get_conn()
        if ns:
            rows = c.execute("SELECT * FROM _event_routes WHERE ns=? ORDER BY id", [ns]).fetchall()
        else:
            rows = c.execute("SELECT * FROM _event_routes ORDER BY id").fetchall()
        routes_list = []
        for r in rows:
            d = dict(r)
            # Convert bytes/Decimal if present
            for k, v in list(d.items()):
                if hasattr(v, 'iso_format'):  # pragma: no cover
                    d[k] = str(v)
            routes_list.append(d)
        return {"success": True, "routes": routes_list, "count": len(routes_list)}
    except Exception as e:
        return {"success": False, "error": str(e), "routes": []}


# ── Tool: pdb_mvm_state_export ──

def tool_mvm_state_export(args: dict) -> dict:
    """Export MVM process state as JSON-serializable dict."""
    pid = args.get("pid", "")
    if not pid:
        return {"success": False, "error": "pid required"}
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        data = vm.export_state(str(pid))
        if not data:
            return {"success": False, "error": f"Process {pid} not found"}
        return {"success": True, "pid": int(pid), "state": data}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_mvm_state_import(args: dict) -> dict:
    """Import MVM process from exported state dict."""
    state_data = args.get("state", {})
    if not state_data:
        return {"success": False, "error": "state dict required"}
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        new_pid = vm.import_state(state_data)
        if new_pid < 0:
            return {"success": False, "error": "Import failed"}
        return {"success": True, "pid": new_pid, "message": f"Process restored as PID {new_pid}"}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_mvm_state_save(args: dict) -> dict:
    """Save process state as snapshot blob in ^STATE(pid, snapshot)."""
    pid = args.get("pid", "")
    if not pid:
        return {"success": False, "error": "pid required"}
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        ok = vm.state_save(str(pid))
        return {"success": ok, "pid": int(pid)}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_mvm_state_restore(args: dict) -> dict:
    """Restore a process from a saved snapshot. Returns new PID."""
    pid = args.get("pid", "")
    if not pid:
        return {"success": False, "error": "pid required"}
    vm = __get_mvm()
    if not vm:
        return {"success": False, "error": "MVM not available"}
    try:
        new_pid = vm.state_restore(str(pid))
        if new_pid < 0:
            return {"success": False, "error": f"No snapshot found for PID {pid}"}
        return {"success": True, "pid": new_pid, "message": f"Process restored as PID {new_pid}"}
    except Exception as e:
        return {"success": False, "error": str(e)}




# ---- MVM App Platform (OBJ-8) ----


def tool_mvm_app_define(args):
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "name required"}
    code = args.get("code", "")
    if not code:
        return {"success": False, "error": "code required"}
    trig = args.get("triggers", {})
    sched = args.get("schedule", "")
    import time as _t
    try:
        tool_set({"ns": "APPS", "subs": [name, "code"], "value": code})
        tool_set({"ns": "APPS", "subs": [name, "triggers"], "value": str(trig)})
        tool_set({"ns": "APPS", "subs": [name, "schedule"], "value": sched})
        tool_set({"ns": "APPS", "subs": [name, "created"], "value": str(_t.time())})
        return {"success": True, "name": name, "lines": len(code.split(chr(10)))}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_mvm_app_list(args):
    try:
        apps = []
        name = ""
        while True:
            r = tool_order({"ns": "APPS", "subs": [name], "direction": 1})
            if r.get("value") is None:
                break
            name = r["value"]
            if name in ("created",):
                continue
            cr = tool_get({"ns": "APPS", "subs": [name, "code"]})
            tr = tool_get({"ns": "APPS", "subs": [name, "triggers"]})
            sr = tool_get({"ns": "APPS", "subs": [name, "schedule"]})
            apps.append({"name": name, "code_len": len(cr.get("value", "")),
                        "triggers": tr.get("value", ""), "schedule": sr.get("value", "")})
        return {"success": True, "apps": apps, "count": len(apps)}
    except Exception as e:
        return {"success": False, "error": str(e), "apps": []}


def tool_mvm_app_run(args):
    name = args.get("name", "")
    if not name:
        return {"success": False, "error": "name required"}
    try:
        r = tool_get({"ns": "APPS", "subs": [name, "code"]})
        code = r.get("value", "")
        if not code:
            return {"success": False, "error": "App not found or empty"}
        vm_app = __get_mvm()
        if not vm_app:
            return {"success": False, "error": "MVM not available"}
        pid = vm_app.spawn(code, name="app_" + name)
        return {"success": True, "pid": pid, "name": name}
    except Exception as e:
        return {"success": False, "error": str(e)}


def tool_mvm_app_generate(args):
    desc = args.get("description", "").lower()
    name = args.get("name", "myapp")
    c = chr(10)
    if "agenda" in desc or "cita" in desc or "appointment" in desc:
        code = (
            'S ^APPS("' + name + '","created")=$ZT' + c
            + 'S ^APPS("' + name + '","desc")="Agenda de ' + name + '"' + c
            + 'Q' + c
            + 'add(d,t,desc) S id=$O(^APPS("' + name + '","citas",""),-1)+1' + c
            + ' S ^APPS("' + name + '","citas",id,"date")=d' + c
            + ' S ^APPS("' + name + '","citas",id,"time")=t' + c
            + ' S ^APPS("' + name + '","citas",id,"desc")=desc' + c
            + ' W "Cita #"_id_" creada",!' + c
            + ' Q' + c
            + 'list() S id="" F  S id=$O(^APPS("' + name + '","citas",id)) Q:id=""  D' + c
            + ' . W id_": "_$G(^APPS("' + name + '","citas",id,"date"))' + c
            + ' . W " "_$G(^APPS("' + name + '","citas",id,"time"))' + c
            + ' . W " - "_$G(^APPS("' + name + '","citas",id,"desc")),!' + c
            + ' Q'
        )
        return {"success": True, "code": code, "template": "agenda", "name": name}
    code = (
        'S ^APPS("' + name + '","created")=$ZT' + c
        + 'S ^APPS("' + name + '","desc")="' + desc + '"' + c
        + 'Q' + c
        + 'add(item) S id=$O(^APPS("' + name + '","items",""),-1)+1' + c
        + ' S ^APPS("' + name + '","items",id)=item' + c
        + ' W "Added #"_id,! ' + c
        + ' Q' + c
        + 'list() S id="" F  S id=$O(^APPS("' + name + '","items",id)) Q:id=""  D' + c
        + ' . W id_": "_$G(^APPS("' + name + '","items",id)),!' + c
        + ' Q' + c
        + 'delete(id) K ^APPS("' + name + '","items",id)' + c
        + ' W "Deleted #"_id,! ' + c
        + ' Q'
    )
    return {"success": True, "code": code, "template": "generic", "name": name}




# ── MVM Fork Cognitivo ──────────────────────────────────────────
def tool_mvm_fork(args: dict) -> dict:
    pid = args.get("pid")
    if pid is None:
        return {"error": "pid required"}
    try:
        mvm = __get_mvm()
        new_pid = mvm.fork(int(pid))
        if new_pid > 0:
            return {"success": True, "pid": new_pid}
        return {"error": f"No se pudo forkear pid={pid}"}
    except Exception as e:
        return {"error": str(e)}

def tool_mvm_diff(args: dict) -> dict:
    pid_a = args.get("pid_a")
    pid_b = args.get("pid_b")
    if pid_a is None or pid_b is None:
        return {"error": "pid_a and pid_b required"}
    try:
        mvm = __get_mvm()
        return mvm.diff_processes(int(pid_a), int(pid_b))
    except Exception as e:
        return {"error": str(e)}

def tool_mvm_promote(args: dict) -> dict:
    source = args.get("source_pid")
    target = args.get("target_pid")
    if source is None:
        return {"error": "source_pid required"}
    try:
        mvm = __get_mvm()
        return mvm.promote(int(source), int(target) if target is not None else None)
    except Exception as e:
        return {"error": str(e)}

TOOLS = [
    {
        "name": "pdb_vec_search",
        "description": "KNN vector search with hierarchical path filtering",
        "inputSchema": {"type": "object", "properties": {
            "query": {"type": "string"},
            "limit": {"type": "integer", "default": 5},
            "path": {"type": "string", "description": "Hierarchical path filter"}
        }, "required": ["query"]}
    },
    {
        "name": "pdb_context_gc",
        "description": "Cognitive GC - prune CONTEXT trees",
        "inputSchema": {"type": "object", "properties": {
            "max_depth": {"type": "integer", "default": 50},
            "dry_run": {"type": "boolean", "default": False}
        }}
    },
    {
        "name": "pdb_set",
        "description": "SET ^ns(subs)=value",
        "inputSchema": {"type": "object", "properties": {
            "ns": {"type": "string"},
            "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}},
            "value": {"description": "Value to store"}
        }, "required": ["ns", "subs", "value"]}
    },
    {
        "name": "pdb_get",
        "description": "Get value by path",
        "inputSchema": {"type": "object", "properties": {
            "ns": {"type": "string"},
            "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}
        }, "required": ["ns", "subs"]}
    },
    {
        "name": "pdb_has",
        "description": "Check if key exists — returns True/False (no ambigüedad)",
        "inputSchema": {"type": "object", "properties": {
            "ns": {"type": "string"},
            "subs": {"type": "array", "items": {"oneOf": [{"type": "string"}, {"type": "number"}]}}
        }, "required": ["ns", "subs"]}
    },

    {
        "name": "pdb_event_route_define",
        "description": "Define an event route: PDB mutations -> MVM mailbox delivery",
        "inputSchema": {"type": "object", "properties": {
            "ns": {"type": "string", "description": "Namespace to watch (* = all)"},
            "subkey_pattern": {"type": "string", "description": "Glob pattern for subs"},
            "event_type": {"type": "string", "description": "'SET', 'KILL', '*' (both)"},
            "target_type": {"type": "string", "description": "'mvm' (default)"},
            "target_id": {"type": "string", "description": "MVM PID to deliver to"}
        }, "required": ["target_id"]}
    },
    {
        "name": "pdb_event_route_remove",
        "description": "Remove an event route by id",
        "inputSchema": {"type": "object", "properties": {
            "route_id": {"type": "number", "description": "Route ID to remove"}
        }, "required": ["route_id"]}
    },
    {
        "name": "pdb_event_route_list",
        "description": "List event routes, optionally filtered by ns",
        "inputSchema": {"type": "object", "properties": {
            "ns": {"type": "string", "description": "Filter by namespace"}
        }}
    },
    {
        "name": "pdb_mvm_state_export",
        "description": "Export MVM process state as JSON-serializable dict",
        "inputSchema": {"type": "object", "properties": {
            "pid": {"type": "number", "description": "Process PID"}
        }, "required": ["pid"]}
    },
    {
        "name": "pdb_mvm_state_import",
        "description": "Import MVM process from exported state dict",
        "inputSchema": {"type": "object", "properties": {
            "state": {"type": "object", "description": "Exported state dict"}
        }, "required": ["state"]}
    },
    {
        "name": "pdb_mvm_state_save",
        "description": "Save process snapshot in ^STATE(pid, snapshot)",
        "inputSchema": {"type": "object", "properties": {
            "pid": {"type": "number", "description": "Process PID"}
        }, "required": ["pid"]}
    },
    {
        "name": "pdb_mvm_state_restore",
        "description": "Restore process from saved snapshot",
        "inputSchema": {"type": "object", "properties": {
            "pid": {"type": "number", "description": "Original PID"}
        }, "required": ["pid"]}
    },

    {
        "name": "pdb_mvm_app_define",
        "description": "Register an MVM app in ^APPS",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"},
            "code": {"type": "string"},
            "triggers": {"type": "object"},
            "schedule": {"type": "string"}
        }, "required": ["name"]}
    },
    {
        "name": "pdb_mvm_app_list",
        "description": "List registered MVM apps",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "pdb_mvm_app_run",
        "description": "Run an app as an MVM process",
        "inputSchema": {"type": "object", "properties": {
            "name": {"type": "string"}
        }, "required": ["name"]}
    },
    {
        "name": "pdb_mvm_app_generate",
        "description": "Generate MUMPS code from description",
        "inputSchema": {"type": "object", "properties": {
            "description": {"type": "string"},
            "name": {"type": "string"}
        }, "required": ["description"]}
    },

    {
        "name": "pdb_mvm_fork",
        "description": "Fork (clone) an MVM process — atomic copy for Tree-of-Thought",
        "inputSchema": {"type": "object", "properties": {
            "pid": {"type": "number", "description": "Process PID to clone"}
        }, "required": ["pid"]}
    },
    {
        "name": "pdb_mvm_diff",
        "description": "Compare state between two forked MVM processes",
        "inputSchema": {"type": "object", "properties": {
            "pid_a": {"type": "number"},
            "pid_b": {"type": "number"}
        }, "required": ["pid_a", "pid_b"]}
    },
    {
        "name": "pdb_mvm_promote",
        "description": "Promote a forked process — copy state to target, kill source",
        "inputSchema": {"type": "object", "properties": {
            "source_pid": {"type": "number"},
            "target_pid": {"type": "number", "description": "Optional target PID (default: auto-assign)"}
        }, "required": ["source_pid"]}
    },
]

HANDLERS = {
    "pdb_set": tool_set,
    "pdb_get": tool_get,
    "pdb_has": tool_has,
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
    "pdb_vec_search": tool_vec_search,
    "pdb_context_gc": tool_context_gc,
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
    "pdb_mvm_sleep": tool_mvm_sleep,
    "pdb_mvm_wake": tool_mvm_wake,
    "pdb_mvm_schedule_list": tool_mvm_schedule_list,
    "pdb_mvm_outbox": tool_mvm_outbox,
    "pdb_mvm_outbox_ack": tool_mvm_outbox_ack,
    "pdb_mvm_outbox_send": tool_mvm_outbox_send,
    "pdb_mvm_outbox_cleanup": tool_mvm_outbox_cleanup,
    "pdb_mvm_mailbox_send": tool_mvm_mailbox_send,
    "pdb_mvm_mailbox_read": tool_mvm_mailbox_read,
    "pdb_embed": tool_embed,
    "pdb_embed_search": tool_embed_search,
    "pdb_event_route_define": tool_event_route_define,
    "pdb_event_route_remove": tool_event_route_remove,
    "pdb_event_route_list": tool_event_route_list,

    "pdb_mvm_state_export": tool_mvm_state_export,
    "pdb_mvm_state_import": tool_mvm_state_import,
    "pdb_mvm_state_save": tool_mvm_state_save,
    "pdb_mvm_state_restore": tool_mvm_state_restore,

    "pdb_mvm_app_define": tool_mvm_app_define,
    "pdb_mvm_app_list": tool_mvm_app_list,
    "pdb_mvm_app_run": tool_mvm_app_run,
    "pdb_mvm_app_generate": tool_mvm_app_generate,

    "pdb_mvm_fork": tool_mvm_fork,
    "pdb_mvm_diff": tool_mvm_diff,
    "pdb_mvm_promote": tool_mvm_promote,

}
