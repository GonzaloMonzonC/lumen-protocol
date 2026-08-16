#!/usr/bin/env python3
"""
MVM Web Engine + DDP Server local

Endpoints:
  GET  /health              → estado general
  GET  /ddp/health          → estado DDP (HMAC status)
  GET  /ddp/pull?ns=X       → pull cambios desde PDB
  POST /ddp/push            → push entries a PDB
  POST /ddp/allocate        → asignación atómica de contador (lee+incrementa+devuelve)
  POST /vm/execute          → ejecutar script M → JSON
  POST /vm/register         → registrar rutina M
  POST /web/register        → registrar ruta web
  GET  /web/<ruta>          → HTML desde ^ROUTES
  GET  /web/admin/invites   → UI admin invitaciones
"""

import sys, os, json, time, hashlib, hmac, threading, subprocess, tempfile
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse
from datetime import datetime, timezone

# Add lumen_mlight to path
_mlight_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', 'mcp-servers', 'pdb')
if os.path.isdir(_mlight_path):
    sys.path.insert(0, os.path.normpath(_mlight_path))

import _paths  # noqa: F401
from m_routines import RoutineExecutor, register, get_routine

# ── DDP Auth ──

def _verify_ddp(body_str, headers):
    """Verify HMAC signature from DDP client. If no key configured, allow local."""
    ts = headers.get("X-DDP-Timestamp", "")
    sig = headers.get("X-DDP-HMAC", "")
    key = os.environ.get("DDP_HMAC_KEY", "")
    if not key:
        return True  # no auth → local-only mode
    msg = (ts + body_str + key).encode()
    expected = hmac.new(key.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)

# ── DDP Operations ──

def _m_order(ns, subs, direction=1):
    """\$O(^ns(subs...)) via Rust MVM SQLite direct. Returns next subscript or ''."""
    try:
        from lumen_mlight import execute_sqlite
        subs_m = ",".join(f'"{s}"' for s in subs) if subs else ""
        code = f'W $O(^{ns}({subs_m}))'
        r = execute_sqlite(code, sqlite_path=_get_db(), gas_limit=50000)
        if not r.get("ok"):
            import sys as _sys
            _sys.stderr.write(f"[M_ORDER FAIL] {ns}({subs_m}) -> {r.get('error','?')[:100]} zerror={r.get('state',{}).get('error',{}).get('zerror','')}\n")
            return ""
        return r.get('state', {}).get('output', '').strip()
    except Exception as e:
        import traceback, sys as _sys
        _sys.stderr.write(f"[M_ORDER ERROR] {e}\n{traceback.format_exc()}\n")
        return ""

def _m_get(ns, subs):
    """\$G(^ns(subs...)) via Rust MVM. Returns value string or ''."""
    try:
        from lumen_mlight import execute_sqlite
        subs_m = ",".join(f'"{s}"' for s in subs)
        code = f'W $G(^{ns}({subs_m}))'
        r = execute_sqlite(code, sqlite_path=_get_db(), gas_limit=50000)
        if not r.get("ok"):
            import sys as _sys
            _sys.stderr.write(f"[M_GET FAIL] {ns}({subs_m}) -> {r.get('error','?')[:100]}\n")
            return ""
        return r.get('state', {}).get('output', '').strip()
    except Exception as e:
        import traceback, sys as _sys
        _sys.stderr.write(f"[M_GET ERROR] {e}\n{traceback.format_exc()}\n")
        return ""

def _m_data(ns, subs):
    """\$D(^ns(subs...)) via Rust MVM. Returns 0/1/10/11."""
    try:
        from lumen_mlight import execute_sqlite
        subs_m = ",".join(f'"{s}"' for s in subs)
        code = f'W $D(^{ns}({subs_m}))'
        r = execute_sqlite(code, sqlite_path=_get_db(), gas_limit=50000)
        if not r.get("ok"):
            import sys as _sys
            _sys.stderr.write(f"[M_DATA FAIL] {ns}({subs_m}) -> {r.get('error','?')[:100]}\n")
            return 0
        d = r.get('state', {}).get('output', '').strip()
        try: return int(d)
        except: return 0
    except Exception as e:
        import traceback, sys as _sys
        _sys.stderr.write(f"[M_DATA ERROR] {e}\n{traceback.format_exc()}\n")
        return 0

def _m_set(ns, subs, value):
    """SET ^ns(subs...)=value via Rust MVM SQLite direct."""
    try:
        from lumen_mlight import execute_sqlite
        subs_m = ",".join(f'"{s}"' for s in subs)
        escaped = str(value).replace('"', '""')
        code = f'S ^{ns}({subs_m})="{escaped}"'
        r = execute_sqlite(code, sqlite_path=_get_db(), gas_limit=50000)
        return r.get("ok", False)
    except:
        return False

def _m_kill(ns, subs):
    """KILL ^ns(subs...) via Rust MVM SQLite direct."""
    try:
        from lumen_mlight import execute_sqlite
        subs_m = ",".join(f'"{s}"' for s in subs)
        code = f'K ^{ns}({subs_m})'
        r = execute_sqlite(code, sqlite_path=_get_db(), gas_limit=50000)
        return r.get("ok", False)
    except:
        return False

def _m_has(ns, subs):
    """Check if node has children via Rust MVM $D."""
    return _m_data(ns, subs) in (10, 11)

def _get_db():
    """Get DB path."""
    import os as _os
    db = _os.environ.get("PDB_PATH") or _os.environ.get("PDB_DB") or ""
    if not db:
        db = str(_paths.DB_PATH)
    return db or ""

def _list_all_routines():
    """List available routine names from PDB via Rust MVM."""
    try:
        from lumen_mlight import execute_sqlite
        routines = []
        key = ""
        for _ in range(2000):
            nxt = _m_order("ROUTINE", [key])
            if not nxt: break
            key = nxt
            routines.append(key)
        return routines
    except:
        return []

def _get_routine_code(name):
    """Get full source code of an MSM routine from PDB via Rust MVM."""
    try:
        from lumen_mlight import execute_sqlite
        lines = []
        key = ""
        while True:
            nxt = _m_order("ROUTINE", [name, key])
            if not nxt: break
            key = nxt
            val = _m_get("ROUTINE", [name, key])
            if val:
                lines.append(val)
        return "\n".join(lines)
    except:
        return ""

def _list_namespaces():
    """List all namespaces in PDB (SQL — no M equivalent for ^GLOBALS)."""
    try:
        import sqlite3
        db = _get_db()
        if not db:
            return ["STATE", "GLOBAL_SIZES", "HEARTBEAT", "TEST", "CONFIG", "ROUTES"]
        conn = sqlite3.connect(db)
        rows = conn.execute("SELECT DISTINCT ns FROM _globals ORDER BY ns").fetchall()
        conn.close()
        return [r[0] for r in rows if r[0]]
    except:
        return ["STATE", "GLOBAL_SIZES", "HEARTBEAT", "TEST", "CONFIG", "ROUTES"]

def _ddp_pull(ns, prefix=None, limit=500, offset=0, depth=0):
    """Pull entries. ns='_all_' = all namespaces. prefix=['asi'] = sub-tree.
    Sanitizes binary subscripts for readable JSON.
    depth=0 → 1 level (root+children), depth=1 → 2 levels, depth=-1 → full tree."""
    try:
        all_entries = []
        if ns == "_all_":
            all_ns = _list_namespaces()
            for n in all_ns:
                _collect(n, all_entries, depth=depth)
        else:
            _collect(ns, all_entries, prefix, depth=depth)
        # Sanitize subscripts before returning
        for e in all_entries:
            e["subs"] = _sanitize_subs(e["subs"])
        # Paginate
        total = len(all_entries)
        if offset > 0 or limit < total:
            entries = all_entries[offset:offset + limit]
        else:
            entries = all_entries
        return {"success": True, "entries": entries, "total": total, "ns": ns}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _sanitize_subs(subs):
    """Convert binary MSM subscripts to readable hex + visible chars.
    Also flattens nested lists from PDB."""
    result = []
    if not isinstance(subs, (list, tuple)):
        return [str(subs)]
    for s in subs:
        if isinstance(s, bytes):
            try:
                result.append(s.decode('utf-8', errors='replace'))
            except:
                result.append(s.hex())
            continue
        if not isinstance(s, str):
            if isinstance(s, (int, float)):
                result.append(str(s))
            else:
                result.append(repr(s))
            continue
        clean = ""
        has_binary = False
        for ch in s:
            o = ord(ch)
            if o < 32 or o > 126:
                clean += f"\\x{o:02x}"
                has_binary = True
            else:
                clean += ch
        # If the clean string is still too long and has binary, truncate with ...
        if has_binary and len(clean) > 60:
            clean = clean[:57] + "..."
        result.append(clean)
    return result

def _has_children(ns, base):
    """Check if a node has children via Rust MVM $D."""
    return _m_has(ns, base)

def _collect(ns, entries, prefix=None, depth=0, _cur_depth=0):
    """Collect entries from PDB via single M code execution."""
    base = prefix or []
    # Use a single M execution to get all entries at this level
    from lumen_mlight import execute_sqlite as _ex
    db = _get_db()
    if not db:
        return

    # Build M code that outputs all subkeys and values
    if base:
        # For sub-levels, need $O from the parent context
        base_m = ",".join(f'"{s}"' for s in base)
        code = (
            f'S k="" F  S k=$O(^{ns}({base_m},k)) Q:k=""  W k,!,$G(^{ns}({base_m},k)),!'
        )
        r = _ex(code, sqlite_path=db, gas_limit=100000)
        output = r.get('state', {}).get('output', '')
        if output:
            lines = output.strip().split('\n')
            for i in range(0, len(lines), 2):
                k = lines[i].strip()
                v = lines[i+1] if i+1 < len(lines) else ''
                has_kids = False  # depth-limited for now
                entries.append({"ns": ns, "subs": base + [k], "value": v,
                                "has_children": has_kids})
    else:
        # Root level: list top-level subscriptions via SQL (no M $O needed)
        if _cur_depth == 0:
            val = _m_get(ns, [])
            # Get all distinct first-level subscripts via SQL
            import os as _os2, sqlite3 as _sq3
            _dbp = _get_db()
            _kids = []
            try:
                _conn = _sq3.connect(_dbp)
                _rows = _conn.execute(
                    "SELECT DISTINCT substr(subkey, 2, instr(subkey||x'ff', x'ff')-2) FROM _globals WHERE ns=? AND length(subkey)>0",
                    (ns,)).fetchall()
                _kids = [r[0] for r in _rows if r[0]]
                _conn.close()
            except Exception as _e:
                pass
            # Decode bytes from SQLite
            _kids = [k.decode('utf-8', errors='replace') if isinstance(k, bytes) else k for k in _kids]
            entries.append({"ns": ns, "subs": [], "value": val or "",
                            "has_children": len(_kids) > 0})
            for k in _kids:
                k = k.strip()
                if not k:
                    continue
                val = _m_get(ns, [k])
                has_kids = _m_has(ns, [k])
                entries.append({"ns": ns, "subs": [k], "value": val or "",
                                "has_children": has_kids})
                if has_kids and (depth == -1 or _cur_depth + 1 <= depth):
                    _collect(ns, entries, [k], depth, _cur_depth + 1)

def _ddp_push(ns, entries):
    """Push entries to PDB via Rust MVM SQLite direct."""
    try:
        db = os.environ.get("PDB_PATH") or ""
        from lumen_mlight import execute_sqlite
        for e in entries:
            subs = e.get("subs", [])
            val = e.get("value", "")
            # Build M code: SET ^NS(sub1,sub2)=value
            subs_m = ",".join(f'"{s}"' for s in subs)
            escaped_val = str(val).replace('"', '""')
            code = f'S ^{ns}({subs_m})="{escaped_val}"'
            execute_sqlite(code, sqlite_path=db if db else None, gas_limit=10000)
        return {"success": True, "count": len(entries)}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── Raw DDP Operations (bypasses MUMPS subscript navigation) ──

def _ddp_allocate(ns, subs, step=1):
    """Asignación atómica de contador: lee, incrementa y devuelve el nuevo valor.

    El servidor HTTPServer es SINGLE-THREADED → read-modify-write dentro de un
    mismo handler es atómico entre clientes (dos peticiones concurrentes
    obtienen valores distintos). Resuelve el race del contador KANBAN
    (antes: GET /ddp/raw + POST /ddp/push eran 2 round-trips separados).
    """
    import sqlite3
    from pdb_tools import encode_subkey
    db = _get_db()
    if not db:
        return {"success": False, "error": "no db path"}
    key = encode_subkey(subs)
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT value FROM _globals WHERE ns=? AND subkey=?", (ns, key)).fetchone()
        cur = 0
        if row and row["value"] is not None:
            try:
                cur = int(json.loads(row["value"]))
            except Exception:
                cur = 0
        new = cur + step
        conn.execute("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                     (ns, key, json.dumps(new)))
        conn.commit()
        return {"success": True, "value": new}
    finally:
        conn.close()

def _decode_subkey(raw_subkey):
    """Decode encoded MUMPS subkey (bytes) to list of subscript strings.
    Format: \x02 + subscript_bytes + \xff for each level."""
    if isinstance(raw_subkey, str):
        raw_subkey = raw_subkey.encode('latin-1')
    subs = []
    i = 0
    while i < len(raw_subkey):
        if raw_subkey[i] == 0x02:  # string type marker
            i += 1
            end = raw_subkey.find(0xFF, i)
            if end == -1:
                subs.append(raw_subkey[i:].decode('utf-8', errors='replace'))
                break
            subs.append(raw_subkey[i:end].decode('utf-8', errors='replace'))
            i = end + 1
        elif raw_subkey[i] == 0xFF:
            i += 1  # skip terminator
        else:
            i += 1  # unknown byte, skip
    return subs

def _ddp_raw(ns, limit=100, offset=0):
    """Pull raw entries from PDB directly (bypasses MUMPS subscript encoding).
    Returns encoded subkeys and values as-is. Useful for namespaces with
    packed binary subkeys like old MSM clinical data."""
    try:
        import sqlite3
        db = _get_db()
        if not db:
            return {"success": False, "error": "no db path"}
        conn = sqlite3.connect(db)
        # Need to get bytes for subkey BLOB column
        conn.text_factory = lambda x: x  # return bytes for all text columns
        rows = conn.execute(
            "SELECT subkey, value FROM _globals WHERE ns=? ORDER BY subkey LIMIT ? OFFSET ?",
            (ns, limit, offset)).fetchall()
        conn.close()
        entries = []
        for row in rows:
            raw_subkey = row[0]
            raw_value = row[1]
            # Decode subkey
            try:
                decoded_subs = _decode_subkey(raw_subkey)
                subs_clean = _sanitize_subs(decoded_subs)
            except:
                subs_clean = [str(raw_subkey)[:80]]
            # Decode value
            val_str = None
            if raw_value and isinstance(raw_value, bytes):
                try:
                    val_str = raw_value.decode("utf-8", errors="replace")
                except:
                    val_str = str(raw_value)[:200]
            elif raw_value:
                val_str = str(raw_value)
            entries.append({
                "subs": subs_clean,
                "value": val_str,
                "subkey_hex": raw_subkey.hex() if isinstance(raw_subkey, bytes) else "",
                "value_bytes": len(raw_value) if raw_value else 0,
            })
        # Count total
        conn2 = sqlite3.connect(db)
        total = conn2.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", (ns,)).fetchone()[0]
        conn2.close()
        return {"success": True, "entries": entries, "total": total, "ns": ns}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── Web Router ──

_local_routes = {}

def register_web(name, routine_name):
    _local_routes[name] = routine_name
    try:
        _m_set("ROUTES", [name], routine_name)
    except:
        pass

def web_route(name):
    try:
        val = _m_get("ROUTES", [name])
        if val:
            return val
    except:
        pass
    return _local_routes.get(name)

def exec_m_full_output(name, args=None, vars_in=None):
    code = get_routine(name)
    if not code:
        return None, f"Routine {name} not found"
    from m_stackvm import StackVM
    vm = StackVM()
    if args:
        for i, arg in enumerate(args, 1):
            vm.vars[f"${i}"] = arg
        vm.vars["$ZARGS"] = len(args)
    if vars_in:
        vm.vars.update(vars_in)
    vm.compile(code)
    vm.vars[""] = name
    try:
        vm.exec()
        output = "".join(str(o) for o in vm.ops if o is not None)
        return output, None
    except Exception as e:
        return None, str(e)

# ── Auth (macaroons Fase 3, gporto) ──

def _auth_required():
    return os.environ.get("PDB_MACAROON_REQUIRED", "") == "1"

def _authorize(handler, ns, op):
    """→ (ok, reason). Gate activo solo con PDB_MACAROON_REQUIRED=1."""
    if not _auth_required():
        return True, "auth disabled (dev)"
    token = ""
    auth = handler.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:].strip()
    if not token:
        token = handler.headers.get("X-PDB-Macaroon", "").strip()
    if not token:
        qs = dict(p.split("=", 1) for p in urlparse(handler.path).query.split("&") if "=" in p)
        token = qs.get("mac", "")
    if not token:
        return False, "macaroon requerido"
    try:
        sp = _paths.PDB_DIR_S
        if sp not in sys.path:
            sys.path.insert(0, sp)
        from pdb_macaroon import check_access
        return check_access(token, ns, op)
    except Exception as e:
        return False, f"macaroon: {e}"

# ── Status / Dashboard unificado (Fase 3) ──

DASHBOARD_TOKEN_FILE = os.path.expanduser("~/.hermes/dashboard.token")

def _dashboard_token():
    """Token del dashboard: env DASHBOARD_TOKEN > fichero ~/.hermes/dashboard.token.
    Vacío = dashboard público (dev). El token NO es auth fuerte — es el gate
    temporal hasta Cloudflare Access (Google IdP)."""
    tok = os.environ.get("DASHBOARD_TOKEN", "").strip()
    if tok:
        return tok
    try:
        if os.path.isfile(DASHBOARD_TOKEN_FILE):
            return open(DASHBOARD_TOKEN_FILE, encoding="utf-8").read().strip()
    except Exception:
        pass
    return ""

def _dashboard_gate(self, qs):
    """401 si hay token configurado y la petición no lo trae (?t= o X-Dashboard-Token)."""
    tok = _dashboard_token()
    if not tok:
        return True
    if self.headers.get("X-Dashboard-Token", "").strip() == tok:
        return True
    if qs.get("t") == tok:
        return True
    self._json({"error": "token requerido"}, 401)
    return False

def _dashboard_token_ok(qs_t, headers):
    """True si el token de la query o el header coinciden con el del dashboard."""
    tok = _dashboard_token()
    if not tok:
        return True
    return headers.get("X-Dashboard-Token", "").strip() == tok or qs_t == tok

WORKERS = [
    ("angi", "https://angi.WORKER_INTERNAL_URL/"),
    ("campo", "https://campo.WORKER_INTERNAL_URL/"),
    ("gon", "https://gon.WORKER_INTERNAL_URL/"),
    ("zalo", "https://zalo.WORKER_INTERNAL_URL/"),
    ("lisa", "https://lisa.WORKER_INTERNAL_URL/"),
    ("tom", "https://tom.WORKER_INTERNAL_URL/"),
    ("eco", "https://eco.WORKER_INTERNAL_URL/"),
    ("pdb-edge", "https://pdb-edge.WORKER_INTERNAL_URL/"),
    ("poli-api", "https://poli-api.cadences.app/"),
]

def _dashboard_status():
    """Estado agregado del ecosistema (workers + PDB) para /api/status y /web/dashboard."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor

    def _check(name, url):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 lumen-dashboard"})
            t0 = time.time()
            with urllib.request.urlopen(req, timeout=3) as r:
                return {"name": name, "status": r.status, "ms": round((time.time() - t0) * 1000)}
        except urllib.error.HTTPError as e:
            return {"name": name, "status": e.code, "ms": None}  # 401/404 = vivo sin handler raíz
        except Exception as e:
            return {"name": name, "status": 0, "ms": None, "err": str(e)[:60]}

    # En paralelo: 9 workers × hasta 3s de timeout, secuencial serían 27s de página
    with ThreadPoolExecutor(max_workers=9) as ex:
        workers = list(ex.map(lambda w: _check(*w), WORKERS))

    db = _get_db()
    ns_counts = []
    kanban = {}
    product = xpub = decisions_recent = None
    if db:
        import sqlite3
        conn = sqlite3.connect(db)
        try:
            for ns, cnt in conn.execute("SELECT ns, COUNT(*) FROM _globals GROUP BY ns ORDER BY 2 DESC LIMIT 14"):
                entry = {"ns": ns, "count": cnt}
                if ns == "KANBAN":
                    entry["detail"] = "entries"  # los counts son subkeys; las tareas reales salen del meta
                ns_counts.append(entry)
            row = conn.execute("SELECT value FROM _globals WHERE ns='KANBAN' AND subkey=?", (b"\x02meta\xff",)).fetchone()
            if row:
                try:
                    m = json.loads(row[0])
                    if isinstance(m, str):
                        m = json.loads(m)  # legacy: valor doble-encodado en reposo
                    if isinstance(m, dict):
                        kanban.update(m)
                except Exception:
                    kanban["meta_raw"] = str(row[0])[:80]
            row = conn.execute("SELECT value FROM _globals WHERE ns='KANBAN' AND subkey=?", (b"\x02counter\xff\x02next_task\xff",)).fetchone()
            if row:
                try:
                    kanban["next_task"] = json.loads(row[0])
                except Exception:
                    kanban["next_task"] = row[0]
            if kanban.get("total") is not None:
                for e in ns_counts:
                    if e["ns"] == "KANBAN":
                        e["detail"] = f"{kanban['total']} tareas"
            for ns in ("PRODUCT", "X_PUB", "DECISIONS"):
                cnt = conn.execute("SELECT COUNT(*) FROM _globals WHERE ns=?", (ns,)).fetchone()[0]
                ns_counts.append({"ns": ns + " (canónico)", "count": cnt})

            # Secciones canónicas (Fase 3): conteos por tipo + muestras recientes
            def _by_prefix(ns, prefix):
                return conn.execute("SELECT COUNT(*) FROM _globals WHERE ns=? AND subkey LIKE ?",
                                    (ns, prefix.encode() + b"%")).fetchone()[0]

            product = {
                "roadmaps": _by_prefix("PRODUCT", "\x02roadmap\xff"),
                "requirements": _by_prefix("PRODUCT", "\x02requirement\xff"),
                "blockers": _by_prefix("PRODUCT", "\x02blocker\xff"),
            }
            xpub = {
                "queue": _by_prefix("X_PUB", "\x02queue\xff"),
                "agenda": _by_prefix("X_PUB", "\x02agenda\xff"),
            }
            decisions_recent = []
            for (sk,) in conn.execute("SELECT subkey FROM _globals WHERE ns='DECISIONS' ORDER BY rowid DESC LIMIT 300"):
                parts = [p.lstrip(b"\x02").decode("utf-8", "replace") for p in sk.split(b"\xff") if p.lstrip(b"\x02")]
                if len(parts) >= 2 and parts[1] not in [d[0] for d in decisions_recent]:
                    decisions_recent.append((parts[1], parts[0]))
                    if len(decisions_recent) >= 5:
                        break
        finally:
            conn.close()

    # Estado del sync diario (checkpoint con cursors por ns)
    sync = None
    cp = os.path.expanduser("~/.hermes/pdb-sync-daily-checkpoint.json")
    if os.path.isfile(cp):
        try:
            with open(cp, encoding="utf-8") as f:
                sync = {"file": cp, "mtime": datetime.fromtimestamp(os.path.getmtime(cp)).isoformat(timespec="seconds"),
                        "cursors": json.load(f)}
        except Exception as e:
            sync = {"error": str(e)[:80]}

    # Estado del backup local (backup_pdb.py)
    backup = None
    bk_dir = os.path.join(os.path.dirname(os.path.abspath(_get_db() or "")), "backups")
    try:
        if os.path.isdir(bk_dir):
            bks = sorted(f for f in os.listdir(bk_dir) if f.endswith(".db.gz"))
            if bks:
                latest = os.path.join(bk_dir, bks[-1])
                backup = {
                    "dir": bk_dir,
                    "latest": bks[-1],
                    "size_mb": round(os.path.getsize(latest) / 1e6, 2),
                    "mtime": datetime.fromtimestamp(os.path.getmtime(latest)).isoformat(timespec="seconds"),
                    "count": len(bks),
                }
    except Exception as e:
        backup = {"error": str(e)[:80]}

    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "workers": workers,
        "namespaces": ns_counts,
        "kanban": kanban,
        "product": product,
        "xpub": xpub,
        "decisions_recent": decisions_recent,
        "sync": sync,
        "backup": backup,
        "db": db,
    }

DASHBOARD_CSS = """
body{font-family:'Segoe UI',system-ui,sans-serif;background:#0d1117;color:#e6edf3;margin:0;padding:24px}
h1{font-size:20px;margin:0 0 4px} .sub{color:#8b949e;font-size:12px;margin-bottom:20px}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(210px,1fr));gap:12px;margin-bottom:24px}
.card{background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 14px}
.card h3{margin:0 0 8px;font-size:12px;text-transform:uppercase;color:#8b949e;letter-spacing:.05em}
.ok{color:#3fb950} .warn{color:#d29922} .bad{color:#f85149} .dim{color:#8b949e}
.big{font-size:26px;font-weight:700} table{width:100%;border-collapse:collapse;font-size:13px}
td,th{text-align:left;padding:5px 8px;border-bottom:1px solid #21262d}
.ns{display:flex;justify-content:space-between;padding:4px 0;border-bottom:1px solid #21262d;font-size:13px}
a{color:#58a6ff;text-decoration:none}
"""

def _web_dashboard(self):
    st = _dashboard_status()
    wrows = "".join(
        f'<div class="card"><h3>{w["name"]}</h3>'
        + ('<span class="ok big">{}</span> <span class="dim">{} ms</span>'.format(w["status"], w.get("ms") or "—")
           if w["status"] and w["status"] != 0
           else f'<span class="bad big">↓</span> <span class="dim">{w.get("err", "sin respuesta")}</span>')
        + "</div>" for w in st["workers"])
    nsrows = "".join(
        f'<div class="ns"><span>{n["ns"]}</span><span>{n["count"]} <span class="dim">{n.get("detail", "")}</span></span></div>'
        for n in st["namespaces"])
    k = st["kanban"]
    kanban_html = "".join(f'<div class="ns"><span>{key}</span><span>{k.get(key, "—")}</span></div>'
                          for key in ("total", "backlog", "in_progress", "done", "next_task"))
    p = st.get("product") or {}
    product_html = "".join(f'<div class="ns"><span>{key}</span><span>{p.get(key, 0)}</span></div>'
                           for key in ("roadmaps", "requirements", "blockers"))
    x = st.get("xpub") or {}
    xpub_html = "".join(f'<div class="ns"><span>{key}</span><span>{x.get(key, 0)}</span></div>'
                        for key in ("queue", "agenda"))
    dec_html = "".join(f'<div class="ns"><span class="dim">{src}</span><span>{dec_id}</span></div>'
                       for dec_id, src in (st.get("decisions_recent") or []))
    s = st.get("sync")
    if s and s.get("mtime"):
        curs = ", ".join(f'{ns}: {ts[:19]}' for ns, ts in (s.get("cursors") or {}).items())
        sync_html = f'<div class="ns"><span>última ejecución</span><span>{s["mtime"]}</span></div><div class="dim" style="font-size:11px">{curs}</div>'
    else:
        sync_html = '<div class="dim">sin checkpoint (el cron diario aún no ha corrido o falló)</div>'
    b = st.get("backup")
    if b and b.get("latest"):
        backup_html = (f'<div class="ns"><span>último</span><span class="ok">{b["latest"][10:17]}</span></div>'
                       f'<div class="ns"><span>tamaño</span><span>{b["size_mb"]} MB</span></div>'
                       f'<div class="ns"><span>copias</span><span>{b["count"]}</span></div>'
                       f'<div class="ns"><span>fecha</span><span>{b["mtime"][:16]}</span></div>')
    else:
        backup_html = '<div class="dim">sin backups aún</div>'
    html = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="60">
<title>LUMEN Dashboard</title><style>{DASHBOARD_CSS}</style></head><body>
<h1>⚡ LUMEN — Dashboard del ecosistema</h1>
<div class="sub">PDB local: {st["db"]} · generado: {st["generated_at"]} · auto-refresh 60s · <a href="/api/status">/api/status</a></div>
<h3>Workers</h3><div class="grid">{wrows}</div>
<div class="grid">
<div class="card"><h3>KANBAN (tareas)</h3>{kanban_html}</div>
<div class="card"><h3>PRODUCT (canónico)</h3>{product_html}</div>
<div class="card"><h3>X_PUB (canónico)</h3>{xpub_html}</div>
<div class="card"><h3>Decisiones recientes</h3>{dec_html or '<div class="dim">—</div>'}</div>
<div class="card"><h3>Sync edge ↔ local</h3>{sync_html}</div>
<div class="card"><h3>Backup local</h3>{backup_html}</div>
<div class="card"><h3>Namespaces top</h3>{nsrows}</div>
</div>
<div class="card"><h3>Fuentes canónicas SSOT</h3>
<div class="dim">KANBAN = tareas · PRODUCT = roadmaps/requirements/blockers · X_PUB = agenda + cola social · DECISIONS = decisiones.
Replicación: workers → túnel → PDB local → edge (sync diario 05:30) + backup local 05:40 (backup_pdb.py, retención 14).</div></div>
</body></html>"""
    payload = html.encode("utf-8")
    self.send_response(200)
    self.send_header("Content-Type", "text/html; charset=utf-8")
    self.send_header("Content-Length", str(len(payload)))
    self.end_headers()
    self.wfile.write(payload)

# ── Bitácora Inmutable (El Prisma → tecnología: "la luz que se cuenta") ──
# Log append-only con hash-chain. Físicamente imposible UPDATE/DELETE (JSONL).
# La integridad se verifica re-calculando la cadena (GET /ddp/bitacora/verify).

_BITACORA_LOCK = threading.Lock()
_BITACORA_DIR = os.environ.get("PDB_PATH", "").strip()
_BITACORA_FILE = os.path.join(os.path.dirname(_BITACORA_DIR), "lumen-bitacora.jsonl") if _BITACORA_DIR else os.path.expanduser("~/pdb-data/lumen-bitacora.jsonl")

def _bitacora_path():
    return _BITACORA_FILE

def _bitacora_append(agente, accion, estado):
    """Append atómico con hash-chain. Devuelve (ok, seq, hash) o (False, err, None)."""
    import hashlib
    with _BITACORA_LOCK:
        os.makedirs(os.path.dirname(_BITACORA_FILE), exist_ok=True)
        prev_hash = "GENESIS"
        seq = 0
        if os.path.isfile(_BITACORA_FILE):
            with open(_BITACORA_FILE, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            prev = json.loads(line)
                            prev_hash = prev.get("hash", prev_hash)
                            seq = int(prev.get("seq", seq))
                        except Exception:
                            pass
        seq += 1
        ts = datetime.now(timezone.utc).isoformat()
        estado_s = json.dumps(estado, ensure_ascii=False, sort_keys=True) if estado is not None else ""
        h = hashlib.sha256(f"{prev_hash}|{seq}|{ts}|{agente}|{accion}|{estado_s}".encode("utf-8")).hexdigest()
        entry = {"seq": seq, "ts": ts, "agente": agente, "accion": accion, "estado": estado, "prev_hash": prev_hash, "hash": h}
        with open(_BITACORA_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            f.flush()
            os.fsync(f.fileno())
        return True, seq, h

def _bitacora_verify():
    """Recorre TODA la cadena y verifica hashes. → {"ok": bool, "entries": n, "broken": [...]}"""
    import hashlib
    if not os.path.isfile(_BITACORA_FILE):
        return {"ok": True, "entries": 0, "broken": []}
    prev_hash = "GENESIS"
    seq = 0
    broken = []
    n = 0
    with open(_BITACORA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            n += 1
            try:
                e = json.loads(line)
            except Exception as ex:
                broken.append({"line": n, "error": f"json: {ex}"})
                continue
            expected_seq = seq + 1
            if int(e.get("seq", 0)) != expected_seq:
                broken.append({"line": n, "error": f"seq {e.get('seq')} != {expected_seq}"})
            estado_s = json.dumps(e.get("estado"), ensure_ascii=False, sort_keys=True) if e.get("estado") is not None else ""
            h = hashlib.sha256(f"{prev_hash}|{expected_seq}|{e.get('ts','')}|{e.get('agente','')}|{e.get('accion','')}|{estado_s}".encode("utf-8")).hexdigest()
            if h != e.get("hash"):
                broken.append({"line": n, "error": f"hash mismatch (cadena rota en seq {expected_seq})"})
            prev_hash = e.get("hash", prev_hash)
            seq = expected_seq
    return {"ok": len(broken) == 0, "entries": n, "last_seq": seq, "last_hash": prev_hash, "broken": broken[:10]}

def _bitacora_tail(tail, agente):
    if not os.path.isfile(_BITACORA_FILE):
        return []
    lines = []
    with open(_BITACORA_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if agente and e.get("agente") != agente:
                continue
            lines.append(e)
    return lines[-int(tail):] if tail else lines


# ── El Espectro: reconstrucción de estado desde los eventos de la bitácora ──
# El prisma descompone la luz: la bitácora guarda eventos crudos (append-only);
# el Espectro los recomponen en un snapshot del estado del ecosistema, con
# rollback: ?hasta_seq=N devuelve el estado reconstruido hasta ese punto.

def _espectro_rebuild(hasta_seq=None):
    """Reconstruye el estado del ecosistema desde la cadena de eventos.
    → {"ok", "cadena": verify, "eventos": n, "agentes": {...}, "snapshot": {...}}"""
    verify = _bitacora_verify()
    agentes = {}
    total = 0
    ultimo_seq = 0
    if os.path.isfile(_BITACORA_FILE):
        with open(_BITACORA_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                seq = int(e.get("seq", 0) or 0)
                if hasta_seq is not None and seq > hasta_seq:
                    break
                total += 1
                ultimo_seq = seq
                a = e.get("agente", "?")
                acc = e.get("accion", "?")
                info = agentes.setdefault(a, {"eventos": 0, "primera": None, "ultima": None,
                                              "ultima_accion": None, "ultimo_estado": None})
                info["eventos"] += 1
                ts = e.get("ts", "")
                if info["primera"] is None or ts < info["primera"]:
                    info["primera"] = ts
                if info["ultima"] is None or ts > info["ultima"]:
                    info["ultima"] = ts
                info["ultima_accion"] = acc
                info["ultimo_estado"] = e.get("estado")
    snapshot = {
        "version": ultimo_seq,
        "generado": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "hasta_seq": hasta_seq,
        "eventos": total,
        "agentes": {a: {"eventos": i["eventos"], "ultima_accion": i["ultima_accion"],
                        "ultima": i["ultima"]} for a, i in sorted(agentes.items())},
    }
    return {"ok": verify["ok"], "cadena": {k: verify[k] for k in ("ok", "entries", "last_seq", "last_hash")},
            "eventos": total, "agentes": agentes, "snapshot": snapshot}

# ── Puente Lumen Quantum (rutinas cQASM de la PDB → Quantum Inspire) ──
# El ecosistema M guarda las plantillas en ^quantum (ns quantum de la PDB);
# este puente las envía a QI vía la CLI (tokens ya autenticados del usuario).

QI_EXE = r"C:/Users/gonzalo/Documents/GitHub/lumen-mcp-quantum/.venv-q/Scripts/qi.exe"
QI_PY = r"C:/Users/gonzalo/Documents/GitHub/lumen-mcp-quantum/.venv-q/Scripts/python.exe"
QI_BACKENDS = {"qx": 1, "emulador": 1, "emulator": 1, "tuna5": 4, "tuna-5": 4, "ry": 5,
               "tuna9": 6, "tuna-9": 6, "tuna17": 7, "tuna-17": 7}
_QUANTUM_DIR = os.path.expanduser("~/pdb-data/quantum")
os.makedirs(_QUANTUM_DIR, exist_ok=True)

def _pdb_get(ns, key):
    """Lee un global de la PDB: W $G(^ns("key")) vía el MVM de Rust."""
    try:
        from lumen_mlight import execute_sqlite
        code = f'W $G(^{ns}("{key}"))'
        r = execute_sqlite(code, sqlite_path=_get_db(), gas_limit=50000)
        if not r.get("ok"):
            return ""
        return r.get("state", {}).get("output", "").strip()
    except Exception:
        return ""

def _qi_run(args, timeout=180):
    """Ejecuta la CLI de QI con el entorno limpio (sin PYTHONPATH de hermes)."""
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
    try:
        r = subprocess.run([QI_EXE] + args, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout, env=env)
        return r.returncode, r.stdout, r.stderr
    except Exception as e:
        return -1, "", str(e)

def _quantum_submit(cqasm_code, backend, shots):
    """Sube el cQASM a QI. → (ok, job_id|error)"""
    btype = QI_BACKENDS.get(str(backend).lower(), None)
    if btype is None:
        try:
            btype = int(backend)
        except Exception:
            return False, f"backend desconocido: {backend} (usa 1, 4, 5, 6, 7 o tuna9/tuna17)"
    path = os.path.join(_QUANTUM_DIR, "run_%d.cq" % int(time.time()))
    with open(path, "w", encoding="utf-8") as f:
        f.write(cqasm_code)
    code, out, err = _qi_run(["files", "upload", path, str(btype)])
    try:
        os.unlink(path)
    except Exception:
        pass
    import re
    m = re.search(r"job_id\s+(\d+)", out)
    if m:
        return True, m.group(1)
    return False, (err or out or "sin job_id")[:300]

def _quantum_result(job_id):
    """Consulta el resultado de un job vía el SDK (JSON puro)."""
    script = (
        "import sys, json\n"
        "sys.path.insert(0, r'C:/Users/gonzalo/Documents/GitHub/lumen-mcp-quantum/.venv-q/Lib/site-packages')\n"
        "from quantuminspire.util.api.remote_backend import RemoteBackend\n"
        "b = RemoteBackend()\n"
        "r = b.get_results(%s)\n"
        "d = r if isinstance(r, dict) else (r.to_dict() if hasattr(r, 'to_dict') else r.model_dump() if hasattr(r, 'model_dump') else vars(r))\n"
        "print(json.dumps(d, default=str))\n" % str(job_id)
    )
    env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "VIRTUAL_ENV")}
    try:
        r = subprocess.run([QI_PY, "-c", script], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, env=env)
    except Exception as e:
        return {"ok": False, "error": str(e)}
    out = r.stdout.strip()
    if r.returncode != 0 or not out:
        return {"ok": False, "error": (r.stderr or out or "sin salida")[:300]}
    try:
        data = json.loads(out)
        items = data.get("items", []) if isinstance(data, dict) else data
        if isinstance(items, list) and items:
            it = items[0]
            return {"ok": True, "status": str(it.get("status", "done")),
                    "message": str(it.get("message", ""))[:200],
                    "counts": it.get("results"), "shots_done": it.get("shots_done"),
                    "execution_time": it.get("execution_time_in_seconds"), "raw_data": it.get("raw_data")}
        return {"ok": True, "status": "done", "message": str(data)[:200]}
    except Exception as e:
        return {"ok": False, "error": f"parse: {e} | out: {out[:200]}"}

# ── Handler ──

class VMHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)

        if path == "/health":
            self._json({"ok": True, "agent": "m-light-vm+ddp", "version": "2.1.1", "fix": "recursive_walk+raw_endpoint"})
        elif path == "/ddp/health":
            self._json({"ok": True, "ddp": "local", "hmac": bool(os.environ.get("DDP_HMAC_KEY"))})
        elif path == "/ddp/pull":
            self._handle_ddp_pull(qs)
        elif path == "/ddp/namespaces":
            self._json({"success": True, "namespaces": _list_namespaces()})
        elif path == "/ddp/bitacora/verify":
            if _dashboard_gate(self, qs):
                self._json({"success": True, "bitacora": _bitacora_verify()})
        elif path == "/ddp/bitacora":
            if _dashboard_gate(self, qs):
                tail = qs.get("tail", "")
                agente = qs.get("agente", "")
                self._json({"success": True, "entries": _bitacora_tail(tail, agente), "verify": _bitacora_verify()})
        elif path == "/ddp/espectro":
            if _dashboard_gate(self, qs):
                hasta = qs.get("hasta_seq", "")
                try:
                    hasta_seq = int(hasta) if hasta else None
                except ValueError:
                    hasta_seq = None
                self._json({"success": True, "espectro": _espectro_rebuild(hasta_seq=hasta_seq)})
        elif path == "/quantum/result":
            if _dashboard_gate(self, qs):
                jid = qs.get("job_id", "")
                if not jid:
                    self._json({"error": "job_id required"}, 400)
                else:
                    self._json(_quantum_result(jid))
        elif path == "/api/status":
            if _dashboard_gate(self, qs):
                self._json(_dashboard_status())
        elif path == "/web/dashboard":
            if _dashboard_gate(self, qs):
                _web_dashboard(self)
        elif path == "/ddp/raw":
            self._handle_ddp_raw(qs)
        elif path.startswith("/ddp/routine"):
            self._handle_ddp_routine(qs)
        elif path.startswith("/web/admin/invites/approve"):
            self._handle_admin_approve(path)
        elif path.startswith("/web/admin/invites/reject"):
            self._handle_admin_reject(path)
        elif path.startswith("/web/admin/invites"):
            self._handle_web("admin/invites")
        elif path.startswith("/web/"):
            self._handle_web(path[5:])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/vm/execute":
            self._with_auth("vm", "execute", self._handle_execute)
        elif path == "/vm/register":
            self._with_auth("vm", "register", self._handle_register)
        elif path == "/web/register":
            self._with_auth("web", "register", self._handle_web_register)
        elif path == "/ddp/push":
            self._handle_ddp_push()
        elif path == "/ddp/allocate":
            self._handle_ddp_allocate()
        elif path == "/ddp/bitacora":
            self._handle_ddp_bitacora()
        elif path == "/quantum/run":
            self._handle_quantum_run()
        else:
            self._json({"error": "not found"}, 404)

    # ── Helpers ──

    def _with_auth(self, ns, op, fn, *args):
        """Ejecuta fn si auth pasa."""
        ok, reason = _authorize(self, ns, op)
        if ok:
            return fn(*args)
        self._json({"error": reason}, 403)

    # ── DDP handlers ──

    def _handle_ddp_pull(self, qs):
        try:
            ns = qs.get("ns", "")
            if not ns:
                self._json({"error": "ns required"}, 400)
                return
            # HMAC auth for pull too
            raw = self.path  # Use request path/query as body for GET
            if not _verify_ddp(raw, self.headers):
                self._json({"error": "HMAC auth failed"}, 403)
                return
            prefix_str = qs.get("prefix", "")
            prefix = prefix_str.split(",") if prefix_str else None
            limit = int(qs.get("limit", "500"))
            offset = int(qs.get("offset", "0"))
            depth = int(qs.get("depth", "0"))
            result = _ddp_pull(ns, prefix, limit, offset, depth)
            self._json(result)
        except Exception as e:
            import traceback as _tb
            self._json({"error": f"{e}\n{_tb.format_exc()}"}, 500)

    def _handle_ddp_raw(self, qs):
        """GET /ddp/raw?ns=clinica&limit=10&offset=0
        Returns raw PDB entries with encoded subkeys (bypasses MUMPS subscript
        navigation). Essential for namespaces with packed binary subkeys like
        old MSM clinical data."""
        try:
            ns = qs.get("ns", "")
            if not ns:
                self._json({"error": "ns required"}, 400)
                return
            # HMAC auth for raw too
            if not _verify_ddp(self.path, self.headers):
                self._json({"error": "HMAC auth failed"}, 403)
                return
            limit = int(qs.get("limit", "100"))
            offset = int(qs.get("offset", "0"))
            result = _ddp_raw(ns, limit, offset)
            self._json(result)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_ddp_routine(self, qs):
        """GET /ddp/routine?name=%SS → devuelve código fuente de rutina MSM."""
        name = qs.get("name", "")
        if not name:
            # Listar rutinas disponibles
            routines = _list_all_routines()
            self._json({"success": True, "routines": routines, "count": len(routines)})
            return
        code = _get_routine_code(name)
        if code:
            self._json({"success": True, "name": name, "code": code})
        else:
            self._json({"error": f"Routine {name} not found"}, 404)

    def _handle_ddp_push(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
            if not _verify_ddp(raw, self.headers):
                self._json({"error": "HMAC auth failed"}, 403)
                return
            body = json.loads(raw)
            # Support both old format (list of entries, ns in query) and new (ns+entries in body)
            qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
            if isinstance(body, list):
                entries = body
                ns = qs.get("ns", "")
            else:
                ns = body.get("ns", qs.get("ns", ""))
                entries = body.get("entries", [])
            if not ns or not entries:
                self._json({"error": "ns and entries required"}, 400)
                return
            result = _ddp_push(ns, entries)
            if isinstance(result, dict) and result.get("success") is False:
                print(f"[VM] DDP-PUSH-FAIL {ns}: {json.dumps(result)[:400]} | entries[0]={json.dumps(entries[0])[:200]}")
            self._json(result)
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_ddp_allocate(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
            if not _verify_ddp(raw, self.headers):
                self._json({"error": "HMAC auth failed"}, 403)
                return
            body = json.loads(raw)
            ns = body.get("ns", "")
            subs = body.get("subs", [])
            step = int(body.get("step", 1))
            if not ns or not subs:
                self._json({"error": "ns and subs required"}, 400)
                return
            self._json(_ddp_allocate(ns, subs, step))
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ── Bitácora Inmutable ──

    def _handle_ddp_bitacora(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
            if not _verify_ddp(raw, self.headers):
                self._json({"error": "HMAC auth failed"}, 403)
                return
            body = json.loads(raw)
            agente = str(body.get("agente", "")).strip()
            accion = str(body.get("accion", "")).strip()
            if not agente or not accion:
                self._json({"error": "agente and accion required"}, 400)
                return
            estado = body.get("estado")
            ok, seq, h = _bitacora_append(agente, accion, estado)
            if not ok:
                self._json({"error": "append failed"}, 500)
                return
            self._json({"success": True, "seq": seq, "hash": h, "verify": _bitacora_verify()})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ── Puente Lumen Quantum ──

    def _handle_quantum_run(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length).decode("utf-8", errors="replace") if length else "{}"
            # Auth: HMAC de DDP (workers) o token del dashboard (rutinas M / ecosistema)
            ok_hmac = _verify_ddp(raw, self.headers)
            qs_t = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
            ok_token = _dashboard_token_ok(qs_t.get("t", ""), self.headers)
            if not (ok_hmac or ok_token):
                self._json({"error": "auth failed (HMAC o token)"}, 403)
                return
            body = json.loads(raw)
            programa = body.get("programa") or body.get("cqasm") or ""
            backend = str(body.get("backend", "1"))
            shots = int(body.get("shots", 1024) or 1024)
            if not programa:
                self._json({"error": "programa o cqasm required"}, 400)
                return
            # Si es un NOMBRE de rutina → leer el cQASM de la PDB (^quantum(nombre))
            if not (programa.lstrip().startswith("version") or "qubit[" in programa):
                cq = _pdb_get("quantum", programa)
                if not cq:
                    self._json({"error": f"rutina '{programa}' no encontrada en ^quantum (PDB)"}, 404)
                    return
                programa = cq
            ok, job_id = _quantum_submit(programa, backend, shots)
            if not ok:
                self._json({"error": job_id}, 500)
                return
            self._json({"success": True, "job_id": job_id, "backend": backend,
                        "consulta": f"/quantum/result?job_id={job_id}"})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ── Admin ──

    def _handle_admin_approve(self, path):
        try:
            from invite_tool import approve_invite
            qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
            token = qs.get("token", "")
            if not token:
                self._json({"error": "token required"}, 400)
                return
            result = approve_invite(token)
            self._html(f"<html><body><h1>{result['status']}</h1><p>Token: {token[:20]}...</p><a href='/web/admin/invites'>← Volver</a></body></html>")
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_admin_reject(self, path):
        try:
            from invite_tool import reject_invite
            qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
            token = qs.get("token", "")
            if not token:
                self._json({"error": "token required"}, 400)
                return
            result = reject_invite(token)
            self._html(f"<html><body><h1>{result['status']}</h1><p>Token: {token[:20]}...</p><a href='/web/admin/invites'>← Volver</a></body></html>")
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ── Web handlers ──

    @staticmethod
    def _read_json(rfile, length):
        """Lee body JSON tolerando encodings rotos (Windows/MSYS curl manda
        cp1252 en vez de UTF-8). Nunca debe reventar el server."""
        raw = rfile.read(length) if length else b""
        if not raw:
            return {}
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return json.loads(raw.decode(enc))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
        return {}

    def _handle_web_register(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self._read_json(self.rfile, length)
            register_web(body.get("route", ""), body.get("routine", ""))
            self._json({"ok": True})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_register(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self._read_json(self.rfile, length)
            name, code = body.get("name", ""), body.get("code", "")
            if not name or not code:
                self._json({"error": "name and code required"}, 400)
                return
            register(name, code)
            self._json({"ok": True, "name": name})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_web(self, route_name):
        try:
            if route_name in ("pdbnav", "navepdb"):
                self._handle_pdb_browser()
                return
            routine = web_route(route_name)
            if not routine:
                self._html("<html><body><h1>404</h1><p>Ruta no encontrada</p></body></html>", 404)
                return
            qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
            args = [qs.get("ns", ""), qs.get("sub", "")]
            output, error = exec_m_full_output(routine, args=args)
            if error:
                self._html(f"<html><body><h1>Error</h1><pre>{error}</pre></body></html>", 500)
                return
            self._html(output)
        except Exception as e:
            self._html(f"<html><body><h1>Error</h1><pre>{e}</pre></body></html>", 500)

    def _handle_pdb_browser(self):
        """PDB Browser via Rust MVM + SQLite direct."""
        import json
        import os
        qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)
        ns = qs.get("ns", "").upper()
        sub = qs.get("sub", "")

        # Ruta a la PDB via entorno
        DB = os.environ.get("PDB_PATH") or os.environ.get("PDB_DB") or ""
        if not DB:
            try:
                from _paths import DB_PATH
                DB = str(DB_PATH)
            except ImportError:
                self._html("<html><body><h1>Error</h1><p>PDB_PATH no configurado</p></body></html>", 500)
                return

        # Importar Rust MVM
        try:
            from lumen_mlight import execute_sqlite
        except ImportError:
            self._html("<html><body><h1>Error</h1><p>lumen_mlight no disponible</p></body></html>", 500)
            return

        def esc(s):
            return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;") if s else ""

        h = ['<html><head><title>PDB Browser (Rust MVM)</title>']
        h.append('<style>body{font-family:monospace;margin:20px}')
        h.append('h1{color:#7c3aed;border-bottom:2px solid #7c3aed}')
        h.append('.nav{background:#f5f3ff;padding:10px;border-radius:8px}')
        h.append('a{color:#6366f1;text-decoration:none}')
        h.append('table{background:white;border-radius:8px;width:100%}')
        h.append('th{background:#7c3aed;color:white;padding:8px;text-align:left}')
        h.append('td{padding:4px 8px;border-bottom:1px solid #eee}')
        h.append('.val{color:#059669;max-width:400px;overflow:hidden;text-overflow:ellipsis}')
        h.append('</style></head><body>')
        h.append(f"<h1>🦀 PDB Browser <span style='font-size:14px;color:#999'>Rust MVM + SQLite directo</span></h1>")
        h.append(f"<div class='nav'><a href='/web/pdbnav'>🏠</a>")
        if ns: h.append(f" / <a href='/web/pdbnav?ns={esc(ns)}'>{esc(ns)}</a>")
        if sub: h.append(f" / {esc(sub)}")
        h.append("</div><hr>")

        try:
            if not ns:
                # ── Root: list namespaces via SQL (direct sqlite3) ──
                import sqlite3 as _sq3
                _dbp = DB or _get_db()
                h.append(f"<h2>📂 Namespaces</h2><div style='display:flex;flex-wrap:wrap;gap:8px'>")
                _total = 0
                try:
                    _c = _sq3.connect(_dbp)
                    _nrows = _c.execute("SELECT DISTINCT ns FROM _globals ORDER BY ns").fetchall()
                    for _r in _nrows:
                        _n = _r[0] or ""
                        h.append(f"<a href='/web/pdbnav?ns={esc(_n)}' style='background:#ede9fe;padding:6px 12px;border-radius:16px;font-size:14px'>{esc(_n)}</a>")
                    _total = _c.execute("SELECT COUNT(*) FROM _globals").fetchone()[0]
                    _c.close()
                except:
                    h.append("<p>Error conectando a DB</p>")
                h.append("</div>")
                h.append(f"<p style='color:#999;font-size:12px'>Total registros: {_total}</p>")

            else:
                # ── Navigation via M code on Rust MVM with SQLite direct ──
                h.append(f"<table><tr><th>Key</th><th>Valor</th></tr>")
                if sub:
                    # Browse sub-level of a specific key
                    code = f'''
 S k="" F  S k=$O(^{ns}("{sub}",k)) Q:k=""  W k,! W $G(^{ns}("{sub}",k)),!
'''
                    result = execute_sqlite(code, sqlite_path=DB, gas_limit=50000)
                    output = result.get('state', {}).get('output', '')
                    lines = output.strip().split('\n') if output else []
                    i = 0
                    while i < len(lines):
                        key2 = lines[i].strip()
                        i += 1
                        val = lines[i].strip() if i < len(lines) else ""
                        i += 1
                        val_short = val[:200]
                        h.append(f"<tr><td><b>{esc(key2)}</b></td><td><span class='val'>{esc(val_short)}</span></td></tr>")
                else:
                    # Browse namespace: list top-level keys via $O with SQLite direct
                    code = f'''
 S k="" F  S k=$O(^{ns}(k)) Q:k=""  W k,!
 S k="" F  S k=$O(^{ns}(k)) Q:k=""  W $D(^{ns}(k)),!
'''
                    result = execute_sqlite(code, sqlite_path=DB, gas_limit=50000)
                    output = result.get('state', {}).get('output', '')
                    lines = output.strip().split('\n') if output else []
                    # First half = keys, second half = $D values
                    mid = len(lines) // 2 if len(lines) % 2 == 0 else len(lines) // 2 + 1
                    keys = lines[:mid] if mid > 0 else []
                    dvals = lines[mid:] if mid < len(lines) else []

                    for idx, key1 in enumerate(keys):
                        if not key1.strip():
                            continue
                        d_val = dvals[idx].strip() if idx < len(dvals) else ""
                        has_subs = d_val in ("10", "11")
                        if has_subs:
                            h.append(f"<tr><td><a href='/web/pdbnav?ns={ns}&sub={esc(key1)}'>📂 {esc(key1)}</a></td><td></td></tr>")
                        else:
                            # Get value for leaf
                            val_code = f'W $G(^{ns}("{key1}"))'
                            vr = execute_sqlite(val_code, sqlite_path=DB, gas_limit=10000)
                            val = vr.get('state', {}).get('output', '').strip()[:200]
                            h.append(f"<tr><td><b>{esc(key1)}</b></td><td><span class='val'>{esc(val)}</span></td></tr>")

                h.append("</table>")

                # Error check
                if sub:
                    err_ns = result.get('state', {}).get('error', {}).get('zerror', '')
                    if err_ns:
                        h.append(f"<p style='color:red'>M error: {esc(err_ns)}</p>")

        except Exception as e:
            h.append(f"<p style='color:red'>Error: {esc(str(e))}</p>")

        h.append("</body></html>")
        self._html("\n".join(h))

    def _handle_execute(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            script = body.get("script", "")
            args = body.get("args", [])
            if not script:
                self._json({"error": "script required"}, 400)
                return
            start = time.time()
            
            # Usar Rust MVM si disponible, fallback a Python StackVM
            try:
                from m_rust_executor import RustExecutor, available as rust_avail
                if rust_avail():
                    executor = RustExecutor()
                    rust_mode = True
                else:
                    executor = RoutineExecutor()
                    rust_mode = False
            except Exception:
                executor = RoutineExecutor()
                rust_mode = False
            
            # Try as named routine first, fallback to inline execution
            result = executor.exec(script, args=args)
            if result.get("error") and "not found" in result["error"]:
                if rust_mode:
                    # Inline mode via Rust MVM
                    result = executor.exec_code(script, args=args)
                else:
                    # Inline mode via StackVM: register temp, execute, clean up
                    import random
                    tmp_name = f"_INLINE_{random.randint(10000,99999)}"
                    register(tmp_name, script)
                    result = executor.exec(tmp_name, args=args)
                    try:
                        _m_kill("ROUTINE", [tmp_name])
                    except:
                        pass
            elapsed = (time.time() - start) * 1000
            self._json({
                "ok": "error" not in result,
                "result": result.get("result"),
                "vars": result.get("vars", {}),
                "exec_ms": round(elapsed, 2),
                "script": script,
            })
        except Exception as e:
            self._json({"error": str(e)}, 500)

    # ── Response helpers ──

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def _html(self, content, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if isinstance(content, str):
            content = content.encode("utf-8")
        self.wfile.write(content)

    def log_message(self, format, *args):
        if args:
            print(f"[VM] {' '.join(str(a) for a in args)}", flush=True)
        else:
            print(f"[VM] {format}", flush=True)

# ── Main ──

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    register("SALUDO^%WEB", """SALUDO ; GET /web/saludo
 W "<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
 W "<style>*{margin:0;padding:0}body{font-family:system-ui,sans-serif;padding:16px;max-width:480px;margin:0 auto;background:#0a0a0f;color:#ddd}"
 W "h1{font-size:1.25rem;color:#51cf66}</style></head><body>"
 W "<h1>⬡ MVM Web Engine + DDP</h1>"
 W "<p>Puerto: 8081 | DDP: /ddp/pull /ddp/push</p>"
 W "</body></html>" Q
""")
    register_web("saludo", "SALUDO^%WEB")

    server = HTTPServer(("0.0.0.0", port), VMHandler)
    print(f"🚀 MVM Web Engine + DDP en http://localhost:{port}")
    print(f"   GET  /web/saludo   → HTML")
    print(f"   GET  /ddp/health   → DDP status")
    print(f"   GET  /ddp/pull?ns=X → sync pull")
    print(f"   POST /ddp/push     → sync push")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Cerrando...")
        server.server_close()
