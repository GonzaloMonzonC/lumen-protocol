#!/usr/bin/env python3
"""
ML-VM-04: API /vm/execute + Web Engine /web/<ruta>

Ejecución remota de scripts M + servir páginas web desde ^ROUTES.

Endpoints:
  POST /vm/execute  → ejecutar script M, devuelve JSON        [protegido]
  POST /vm/register → registrar rutina M                       [protegido]
  POST /web/register → registrar ruta web → rutina             [protegido]
  POST /web/admin/invites/approve?token=X → aprobar invitación [protegido]
  POST /web/admin/invites/reject?token=X  → rechazar           [protegido]
  GET  /web/<ruta>  → busca ^ROUTES(ruta), ejecuta M, devuelve HTML
  GET  /health      → estado

Auth (convención Fase 3, igual que bridge_plugin.py): con
PDB_MACAROON_REQUIRED=1 los endpoints protegidos exigen un macaroon
(Authorization: Bearer <b64> | X-PDB-Macaroon | ?mac=). Sin esa env el
gate está abierto (modo dev) y el servidor solo escucha en 127.0.0.1.

Uso:
  python3 vm_api.py [puerto] [--host 0.0.0.0]

  curl -X POST http://localhost:8081/vm/execute \
    -H "Content-Type: application/json" \
    -d '{"script": "HELLO"}'

  curl http://localhost:8081/web/saludo
"""

import sys, os, json, time, html
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

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
    except Exception:
        pass  # PDB offline, solo local

def web_route(name):
    """Busca ^ROUTES(name) → intenta PDB primero, luego fallback local."""
    try:
        from pdb_tools import tool_get
        r = tool_get({"ns": "ROUTES", "subs": [name]})
        if r.get("success") and r.get("value"):
            return r["value"]
    except Exception:
        pass
    return _local_routes.get(name)

def exec_m_full_output(name, args=None, vars_in=None):
    """Ejecuta rutina M y devuelve TODO el WRITE output concatenado.

    → (output, None) | (None, error). El output se captura con el hook
    _on_write del StackVM (la pila vm.ops mezcla operandos de SET/GET)."""
    code = get_routine(name)
    if not code:
        return None, f"Routine {name} not found"

    from m_stackvm import StackVM
    vm = StackVM()
    chunks = []
    vm._on_write = chunks.append
    if args:
        for i, arg in enumerate(args, 1):
            vm.vars[f"${i}"] = arg
        vm.vars["$ZARGS"] = len(args)
    if vars_in:
        vm.vars.update(vars_in)

    vm.compile(code)
    try:
        result = vm.exec()
        if isinstance(result, dict) and result.get("error"):
            return None, f"{result['error']}: {result.get('msg', '')}"
        return "".join(chunks), None
    except Exception as e:
        return None, str(e)

# ── Auth (macaroons Fase 3) ──

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
        qs = parse_qs(urlparse(handler.path).query)
        token = (qs.get("mac") or [""])[0]
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

_ERROR_PAGE = "<html><body><h1>{title}</h1><pre>{detail}</pre></body></html>"

class VMHandler(BaseHTTPRequestHandler):

    def do_GET(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/health":
            self._json({"ok": True, "agent": "m-light-vm", "version": "2.1.0"})
        elif path.startswith("/web/admin/invites/"):
            # approve/reject mutan estado: solo POST
            self._json({"error": "method not allowed, use POST"}, 405)
        elif path.startswith("/web/"):
            self._handle_web(path[5:])
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        path = urlparse(self.path).path.rstrip("/")

        if path == "/vm/execute":
            self._with_auth("ROUTINE", "write", self._handle_execute)
        elif path == "/vm/register":
            self._with_auth("ROUTINE", "write", self._handle_register)
        elif path == "/web/register":
            self._with_auth("ROUTES", "write", self._handle_web_register)
        elif path == "/web/admin/invites/approve":
            self._with_auth("INVITACION", "write", self._handle_admin_action, "approve")
        elif path == "/web/admin/invites/reject":
            self._with_auth("INVITACION", "write", self._handle_admin_action, "reject")
        else:
            self._json({"error": "not found"}, 404)

    def _with_auth(self, ns, op, fn, *args):
        ok, reason = _authorize(self, ns, op)
        if not ok:
            self._json({"error": f"unauthorized: {reason}"}, 401)
            return
        fn(*args)

    def _handle_admin_action(self, action):
        """POST /web/admin/invites/{approve|reject}?token=X."""
        try:
            from invite_tool import approve_invite, reject_invite
            qs = parse_qs(urlparse(self.path).query)
            token = (qs.get("token") or [""])[0]
            if not token:
                self._json({"error": "token required"}, 400)
                return
            result = approve_invite(token) if action == "approve" else reject_invite(token)
            if self.headers.get("Accept", "").startswith("application/json"):
                self._json(result)
            else:
                safe_status = html.escape(str(result.get("status", "")))
                safe_token = html.escape(token[:20])
                self._html(
                    f"<html><body><h1>{safe_status}</h1>"
                    f"<p>Token: {safe_token}...</p>"
                    f"<a href='/web/admin/invites'>← Volver</a></body></html>"
                )
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_web_register(self):
        """POST /web/register → registrar ruta web en el servidor."""
        try:
            body = self._read_json()
            route = body.get("route", "")
            routine = body.get("routine", "")
            if not route or not routine:
                self._json({"error": "route and routine required"}, 400)
                return
            register_web(route, routine)
            self._json({"ok": True, "route": route, "routine": routine})
        except Exception as e:
            self._json({"error": str(e)}, 500)

    def _handle_register(self):
        """POST /vm/register → registrar rutina M en el servidor."""
        try:
            body = self._read_json()
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
                self._html(_ERROR_PAGE.format(title="Error", detail=html.escape(str(error))), 500)
                return

            self._html(output)

        except Exception as e:
            self._html(_ERROR_PAGE.format(title="Error", detail=html.escape(str(e))), 500)

    def _handle_execute(self):
        try:
            body = self._read_json()
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

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length)) if length else {}

    def _json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
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


def register_builtin_routes():
    """Rutas que el servidor registra al arrancar."""
    register("SALUDO^%WEB", SALUDO_M)
    register_web("saludo", "SALUDO^%WEB")

    # UI admin de invitaciones (rutina M en routines/admin_invites.m)
    admin_m = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "routines", "admin_invites.m")
    if os.path.exists(admin_m):
        with open(admin_m) as f:
            register("ADMIN_INVITES", f.read())
        register_web("admin/invites", "ADMIN_INVITES")


# ── Main ──

if __name__ == "__main__":
    argv = [a for a in sys.argv[1:]]
    host = "127.0.0.1"
    if "--host" in argv:
        i = argv.index("--host")
        host = argv[i + 1]
        del argv[i:i + 2]
    port = int(argv[0]) if argv else 8081

    register_builtin_routes()

    if host not in ("127.0.0.1", "localhost") and not _auth_required():
        print("⚠️  Escuchando fuera de localhost SIN auth. "
              "Exporta PDB_MACAROON_REQUIRED=1 para exigir macaroons.")

    server = HTTPServer((host, port), VMHandler)
    print(f"🚀 VM API + Web Engine en http://{host}:{port}")
    print(f"   POST /vm/execute  {json.dumps({'script': 'HELLO'})}")
    print(f"   GET  /web/saludo   → HTML desde M")
    print(f"   GET  /web/admin/invites → UI de invitaciones")
    print(f"   GET  /health       → estado")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Cerrando...")
        server.server_close()
