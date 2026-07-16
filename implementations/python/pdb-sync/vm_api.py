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

def _list_all_routines():
    """List available routine names from PDB."""
    try:
        from pdb_tools import tool_order
        routines = []
        key = ""
        for _ in range(500):
            r = tool_order({"ns": "ROUTINE", "subs": [key], "direction": 1})
            if not r.get("success") or r.get("value") is None:
                break
            key = r["value"]
            routines.append(key)
        return routines
    except:
        return []

def _get_routine_code(name):
    """Get full source code of an MSM routine from PDB."""
    try:
        from pdb_tools import tool_order, tool_get
        lines = []
        key = ""
        while True:
            r = tool_order({"ns": "ROUTINE", "subs": [name, key], "direction": 1})
            if not r.get("success") or r.get("value") is None:
                break
            key = r["value"]
            val = tool_get({"ns": "ROUTINE", "subs": [name, key]})
            if val.get("success") and val.get("value") is not None:
                lines.append(str(val["value"]))
        return "\n".join(lines)
    except:
        return ""
    """List all namespaces in PDB."""
    try:
        from pdb_tools import tool_query
        r = tool_query({"sql": "SELECT DISTINCT ns FROM _globals ORDER BY ns", "limit": 500})
        if r.get("success"):
            return [row["ns"] for row in r.get("rows", [])]
        return []
    except:
        return ["STATE", "GLOBAL_SIZES", "HEARTBEAT", "TEST", "CONFIG", "ROUTES"]

def _ddp_pull(ns, prefix=None):
    """Pull entries. ns='_all_' = all namespaces. prefix=['asi'] = sub-tree."""
    try:
        entries = []
        if ns == "_all_":
            all_ns = _list_namespaces()
            for n in all_ns:
                _collect(n, entries)
        else:
            _collect(ns, entries, prefix)
        return {"success": True, "entries": entries, "ns": ns}
    except Exception as e:
        return {"success": False, "error": str(e)}

def _collect(ns, entries, prefix=None):
    """Collect one level from PDB (non-recursive)."""
    from pdb_tools import tool_order, tool_get
    base = prefix or []
    # Root at this level
    val = tool_get({"ns": ns, "subs": list(base)})
    if val.get("success") and val.get("value") is not None:
        entries.append({"ns": ns, "subs": list(base), "value": val["value"]})
    # Children at this level only
    key = ""
    while True:
        r = tool_order({"ns": ns, "subs": base + [key], "direction": 1})
        if not r.get("success") or r.get("value") is None:
            break
        key = r["value"]
        child_val = tool_get({"ns": ns, "subs": base + [key]})
        if child_val.get("success") and child_val.get("value") is not None:
            entries.append({"ns": ns, "subs": base + [key], "value": child_val["value"]})

def _ddp_push(ns, entries):
    """Push entries to PDB."""
    try:
        from pdb_tools import tool_set
        for e in entries:
            tool_set({"ns": ns, "subs": e["subs"], "value": e["value"]})
        return {"success": True, "count": len(entries)}
    except Exception as e:
        return {"success": False, "error": str(e)}

# ── Web Router ──

_local_routes = {}

def register_web(name, routine_name):
    _local_routes[name] = routine_name
    try:
        from pdb_tools import tool_set
        tool_set({"ns": "ROUTES", "subs": [name], "value": routine_name})
    except:
        pass

def web_route(name):
    try:
        from pdb_tools import tool_get
        r = tool_get({"ns": "ROUTES", "subs": [name]})
        if r.get("success") and r.get("value"):
            return r["value"]
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

# ── Handler ──

class VMHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")
        qs = dict(p.split("=", 1) for p in urlparse(self.path).query.split("&") if "=" in p)

        if path == "/health":
            self._json({"ok": True, "agent": "m-light-vm+ddp", "version": "2.0.0"})
        elif path == "/ddp/health":
            self._json({"ok": True, "ddp": "local", "hmac": bool(os.environ.get("DDP_HMAC_KEY"))})
        elif path == "/ddp/pull":
            self._handle_ddp_pull(qs)
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
            self._handle_execute()
        elif path == "/vm/register":
            self._handle_register()
        elif path == "/web/register":
            self._handle_web_register()
        elif path == "/ddp/push":
            self._handle_ddp_push()
        else:
            self._json({"error": "not found"}, 404)

    # ── DDP handlers ──

    def _handle_ddp_pull(self, qs):
        try:
            ns = qs.get("ns", "")
            if not ns:
                self._json({"error": "ns required"}, 400)
                return
            result = _ddp_pull(ns)
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
            ns = body.get("ns", "")
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
            routine = web_route(route_name)
            if not routine:
                self._html("<html><body><h1>404</h1><p>Ruta no encontrada</p></body></html>", 404)
                return
            output, error = exec_m_full_output(routine)
            if error:
                self._html(f"<html><body><h1>Error</h1><pre>{error}</pre></body></html>", 500)
                return
            self._html(output)
        except Exception as e:
            self._html(f"<html><body><h1>Error</h1><pre>{e}</pre></body></html>", 500)

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
            executor = RoutineExecutor()
            result = executor.exec(script, args=args)
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
        print(f"[VM] {args[0]} {args[1]} {args[2]}", flush=True)

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
