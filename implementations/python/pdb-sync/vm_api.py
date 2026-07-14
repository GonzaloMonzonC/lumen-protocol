#!/usr/bin/env python3
"""
ML-VM-04: API /vm/execute — Ejecución remota de scripts M.

Endpoint POST /vm/execute para que Zalo, Lisa, Tom, Angi ejecuten
scripts M desde cualquier lado.

Modos:
1. Local (HTTP): POST http://localhost:8081/vm/execute
2. Vía edge (DDP): edge worker redirige a local

Uso:
  curl -X POST http://localhost:8081/vm/execute \\
    -H "Content-Type: application/json" \\
    -d '{"script": "MI_SCRIPT", "args": ["arg1", "arg2"]}'

Respuesta:
  {"ok": true, "result": 42, "vars": {...}, "exec_ms": 1.2}
"""

import sys, os, json, time
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse

import _paths  # noqa: F401  # sys.path del stack PDB

from m_routines import RoutineExecutor, register, get_routine

# ── Handler ──
class VMHandler(BaseHTTPRequestHandler):
    """HTTP handler para /vm/execute."""
    
    def do_POST(self):
        path = urlparse(self.path).path
        
        if path == "/vm/execute":
            self._handle_execute()
        elif path == "/health":
            self._json({"ok": True, "agent": "m-light-vm", "version": "2.0.0"})
        else:
            self._json({"error": "not found"}, 404)
    
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
    
    def log_message(self, format, *args):
        print(f"[VM] {args[0]} {args[1]} {args[2]}")


# ── Main ──
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    
    # Registrar scripts de prueba
    register("ECHO", 'S result=$1 W result Q')
    register("HELLO", 'S result="Hola desde M-Light!" W result Q')
    register("SUM", 'S a=$1 S b=$2 S result=a+b W result Q')
    
    server = HTTPServer(("0.0.0.0", port), VMHandler)
    print(f"🚀 VM API en http://localhost:{port}")
    print(f"   POST /vm/execute  {json.dumps({'script':'HELLO'})}")
    print(f"   POST /vm/execute  {json.dumps({'script':'SUM','args':[3,4]})}")
    print(f"   GET  /health")
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n👋 Cerrando VM API...")
        server.server_close()
