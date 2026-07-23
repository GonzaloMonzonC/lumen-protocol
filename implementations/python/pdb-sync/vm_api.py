#!/usr/bin/env python3
"""
MVM Web Engine + DDP Server local

Endpoints:
  GET  /health              → estado general
  GET  /ddp/health          → estado DDP (HMAC status)
  GET  /ddp/pull?ns=X       → pull cambios desde PDB
  POST /ddp/push            → push entries a PDB
  POST /vm/execute          → ejecutar script M → JSON
  POST /vm/register         → registrar rutina M
  POST /web/register        → registrar ruta web
  GET  /web/<ruta>          → HTML desde ^ROUTES
  GET  /web/admin/invites   → UI admin invitaciones
"""

import sys, os, json, time, hashlib, hmac
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
            raw = self.rfile.read(length).decode() if length else "{}"
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
            self._json(result)
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

    def _handle_web_register(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            register_web(body.get("route", ""), body.get("routine", ""))
            self._json({"ok": True})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_register(self):
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
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
