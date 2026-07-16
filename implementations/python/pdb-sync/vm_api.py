#!/usr/bin/env python3
"""
ML-VM-04: API /vm/execute + Web Engine /web/<ruta>

Ejecución remota de scripts M + servir páginas web desde ^ROUTES.

Endpoints:
  POST /vm/execute  → ejecutar script M, devuelve JSON
  GET  /web/<ruta>  → busca ^ROUTES(ruta), ejecuta M, devuelve HTML
  GET  /health      → estado

Uso:
  curl -X POST http://localhost:8081/vm/execute \
    -H "Content-Type: application/json" \
    -d '{"script": "HELLO"}'

  curl http://localhost:8081/web/saludo
"""

import sys, os, json, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import _paths  # noqa: F401  # sys.path del stack PDB

from m_routines import RoutineExecutor, register, get_routine

# ── Web Router ──

_local_routes = {}  # fallback cuando PDB no está disponible

def register_web(name, routine_name):
    """Registrar ruta web (siempre en local, intenta PDB)."""
    _local_routes[name] = routine_name
    try:
        from pdb_tools import tool_set
        tool_set({"ns": "ROUTES", "subs": [name], "value": routine_name})
    except:
        pass  # PDB offline, solo local

def web_route(name):
    """Busca ^ROUTES(name) → intenta PDB primero, luego fallback local."""
    try:
        from pdb_tools import tool_get
        r = tool_get({"ns": "ROUTES", "subs": [name]})
        if r.get("success") and r.get("value"):
            return r["value"]
    except:
        pass
    # Fallback local
    return _local_routes.get(name)

def exec_m_full_output(name, args=None, vars_in=None):
    """Ejecuta rutina M y devuelve TODO el WRITE output concatenado."""
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
        result = vm.exec()  # noqa: F841
        output = "".join(str(o) for o in vm.ops if o is not None)
        return output, None
    except Exception as e:
        return None, str(e)

# ── Handler ──

class VMHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/health":
            self._json({"ok": True, "agent": "m-light-vm", "version": "2.0.0"})
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
        print(f"[DEBUG] POST {path}", flush=True)  # DEBUG

        if path == "/vm/execute":
            self._handle_execute()
        elif path == "/vm/register":
            self._handle_register()
        elif path == "/web/register":
            self._handle_web_register()
        else:
            self._json({"error": "not found"}, 404)

    def _handle_admin_approve(self, path):
        """GET/POST /web/admin/invites/approve?token=X → aprobar invitación."""
        try:
            from invite_tool import approve_invite
            parsed = urlparse(self.path)
            qs = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            token = qs.get("token", "")
            if not token:
                self._json({"error": "token required"}, 400)
                return
            result = approve_invite(token)
            if self.headers.get("Accept", "").startswith("application/json"):
                self._json(result)
            else:
                self._html(f"<html><body><h1>{result['status']}</h1><p>Token: {token[:20]}...</p><a href='/web/admin/invites'>← Volver</a></body></html>")
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_admin_reject(self, path):
        """GET/POST /web/admin/invites/reject?token=X → rechazar invitación."""
        try:
            from invite_tool import reject_invite
            parsed = urlparse(self.path)
            qs = dict(p.split("=", 1) for p in parsed.query.split("&") if "=" in p)
            token = qs.get("token", "")
            if not token:
                self._json({"error": "token required"}, 400)
                return
            result = reject_invite(token)
            if self.headers.get("Accept", "").startswith("application/json"):
                self._json(result)
            else:
                self._html(f"<html><body><h1>{result['status']}</h1><p>Token: {token[:20]}...</p><a href='/web/admin/invites'>← Volver</a></body></html>")
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_web_register(self):
        """POST /web/register → registrar ruta web en el servidor."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            route = body.get("route", "")
            routine = body.get("routine", "")
            register_web(route, routine)
            self._json({"ok": True, "route": route, "routine": routine})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_register(self):
        """POST /vm/register → registrar rutina M en el servidor."""
        try:
            length = int(self.headers.get("Content-Length", 0))
            body = json.loads(self.rfile.read(length)) if length else {}
            name = body.get("name", "")
            code = body.get("code", "")
            if not name or not code:
                self._json({"error": "name and code required"}, 400)
                return
            register(name, code)
            self._json({"ok": True, "name": name})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_web(self, route_name):
        """GET /web/<ruta> → busca ^ROUTES(ruta) → ejecuta M → devuelve HTML."""
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
        print(f"[VM] {args[0]} {args[1]} {args[2]}")


# ── Rutas M de ejemplo ──

SALUDO_M = """
SALUDO ; GET /web/saludo
 W "<html><head>"
 W "<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
 W "<style>"
 W "*{margin:0;padding:0;box-sizing:border-box}"
 W "body{font-family:system-ui,sans-serif;padding:16px;max-width:480px;margin:0 auto;background:#0a0a0f;color:#ddd}"
 W "h1{font-size:1.25rem;margin-bottom:1rem}"
 W ".card{background:#13131a;border:1px solid #333;border-radius:8px;padding:12px;margin-bottom:8px}"
 W ".num{font-size:1.5rem;font-weight:700;color:#51cf66}"
 W ".lbl{font-size:.75rem;color:#888}"
 W "</style></head><body>"
 W "<h1>👋 MVM Web Engine</h1>"
 W "<div class='card'><div class='num'>8081</div><div class='lbl'>Puerto</div></div>"
 W "<div class='card'><div class='num'>",$G(^ROUTES),"/ROUTES</div><div class='lbl'>Rutas registradas</div></div>"
 W "</body></html>"
 Q
"""

# ── Main ──

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081

    # Registrar rutas y scripts
    register("SALUDO^%WEB", SALUDO_M)
    register_web("saludo", "SALUDO^%WEB")

    server = HTTPServer(("0.0.0.0", port), VMHandler)
    print(f"🚀 VM API + Web Engine en http://localhost:{port}")
    print(f"   POST /vm/execute  {json.dumps({'script':'HELLO'})}")
    print(f"   GET  /web/saludo   → HTML desde M")
    print(f"   GET  /health       → estado")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Cerrando...")
        server.server_close()
