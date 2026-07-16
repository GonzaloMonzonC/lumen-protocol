#!/usr/bin/env python3
"""Tests para MVM Web Engine — sin mocks: arranca vm_api.py en un
subproceso con BD temporal y puerto libre, registra via API."""

import sys, os, json, time, http.client
import atexit, socket, subprocess, tempfile

# ── Servidor bajo test ──

def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port

PORT = _free_port()
_tmpdir = tempfile.mkdtemp(prefix="lumen-webtest-")
_server = subprocess.Popen(
    [sys.executable, os.path.join(os.path.dirname(os.path.abspath(__file__)), "vm_api.py"), str(PORT)],
    env=dict(os.environ, PDB_PATH=os.path.join(_tmpdir, "test.db")),
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
atexit.register(_server.terminate)

def _wait_ready(timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            conn = http.client.HTTPConnection("localhost", PORT, timeout=1)
            conn.request("GET", "/health")
            if conn.getresponse().status == 200:
                conn.close()
                return
        except OSError:
            time.sleep(0.15)
    raise RuntimeError(f"vm_api.py no responde en :{PORT}")

# ── Helpers ──

def curl(path, method="GET", body=None, expected_status=None):
    conn = http.client.HTTPConnection("localhost", PORT, timeout=5)
    conn.request(method, path, body=json.dumps(body) if body else None,
                 headers={"Content-Type": "application/json"} if body else {})
    resp = conn.getresponse()
    data = resp.read().decode()
    conn.close()
    if expected_status is not None and resp.status != expected_status:
        raise AssertionError(f"Expected {expected_status}, got {resp.status}: {data[:200]}")
    return resp.status, data

def ok(cond, msg):
    assert cond, msg
    print(f"  ✅ {msg}")

T = True

# ── Tests ──

def test_health():
    print("\n🏥 Health")
    s, d = curl("/health")
    data = json.loads(d)
    ok(s == 200, "status 200")
    ok(data["ok"] == T, "ok=true")
    ok(data["agent"] == "m-light-vm", "agent")

def test_web_saludo():
    print("\n🌐 /web/saludo (registrada al arrancar)")
    s, d = curl("/web/saludo")
    ok(s == 200, "status 200")
    ok("<h1>" in d, "HTML válido")
    ok("MVM Web Engine" in d, "contenido")
    ok("viewport" in d, "mobile-first")
    ok("#51cf66" in d, "tema LUMEN")
    ok("#0a0a0f" in d, "fondo oscuro")

def test_web_404():
    print("\n🚫 /web/noexiste")
    s, d = curl("/web/noexiste")
    ok(s == 404, "status 404")
    ok("Ruta no encontrada" in d, "mensaje HTML")

def test_register_and_serve():
    print("\n📝 Registrar ruta + rutina via API y servir")
    
    # 1. Registrar ruta
    s, d = curl("/web/register", method="POST", body={
        "route": "test/hola",
        "routine": "HOLA^%TEST"
    })
    ok(s == 200, f"POST /web/register (status {s})")
    
    # 2. Registrar rutina M
    s, d = curl("/vm/register", method="POST", body={
        "name": "HOLA^%TEST",
        "code": 'HOLA ; test\n W "<html><body><h1>Hola mundo</h1></body></html>"\n Q'
    })
    ok(s == 200, f"POST /vm/register (status {s})")
    
    # 3. Servir
    s, d = curl("/web/test/hola")
    ok(s == 200, f"GET /web/test/hola (status {s})")
    ok("Hola mundo" in d, "output M correcto")

def test_dashboard():
    print("\n📊 Dashboard con datos")
    
    # Registrar ruta
    curl("/web/register", method="POST", body={
        "route": "test/dashboard",
        "routine": "DASH^%TEST"
    })
    
    # Registrar rutina M que usa variables
    curl("/vm/register", method="POST", body={
        "name": "DASH^%TEST",
        "code": 'DASH ; dashboard\n W "<html><body>"\n N i\n F i=1:1:5 W "<p>Item ",i,"</p>"\n W "</body></html>"\n Q'
    })
    
    # Servir
    s, d = curl("/web/test/dashboard")
    ok(s == 200, "status 200")
    ok("Item 1" in d, "bucle FOR funciona")
    ok("Item 5" in d, "último item")
    ok("<html>" in d and "</html>" in d, "HTML completo")

def test_error_handling():
    print("\n💥 Manejo de errores")
    
    # Registrar rutina con error de compilación
    curl("/web/register", method="POST", body={
        "route": "test/mal",
        "routine": "MAL^%TEST"
    })
    curl("/vm/register", method="POST", body={
        "name": "MAL^%TEST",
        "code": "MAL ; rutina rota\n S x=UNDEFINED_ZZZ\n Q"
    })
    
    s, d = curl("/web/test/mal")
    ok(s == 500, f"status 500 en error (got {s})")
    ok("Error" in d, "página de error")

def test_post_execute():
    print("\n📡 POST /vm/execute (compatibilidad)")
    curl("/vm/register", method="POST", body={
        "name": "HELLO",
        "code": 'HELLO S result="Hola desde M-Light!" W result Q'
    })
    s, d = curl("/vm/execute", method="POST", body={"script": "HELLO"})
    data = json.loads(d)
    ok(s == 200, f"status 200 (got {s})")
    ok(data["ok"] == T, "ok=true")

def test_concurrent():
    print("\n⚡ 5 requests concurrentes")
    import concurrent.futures
    def do_req():
        s, d = curl("/web/saludo")
        return s == 200 and "MVM Web Engine" in d
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(lambda _: do_req(), range(5)))
    
    ok(all(results), f"5/5 exitosos (got {sum(results)}/5)")

# ── Main ──

if __name__ == "__main__":
    print("=" * 60)
    print(f"🧪 MVM Web Engine — Test Suite v2 (:{PORT})")
    print("=" * 60)
    _wait_ready()

    tests = [
        test_health,
        test_web_saludo,
        test_web_404,
        test_register_and_serve,
        test_dashboard,
        test_error_handling,
        test_post_execute,
        test_concurrent,
    ]
    
    errors = []
    for test_fn in tests:
        try:
            test_fn()
        except Exception as e:
            print(f"  ❌ {test_fn.__name__}: {e}")
            errors.append(test_fn.__name__)
    
    print("\n" + "=" * 60)
    if errors:
        print(f"❌ {len(errors)} errores: {', '.join(errors)}")
    else:
        print("🎉 Todos los tests pasan!")
    print("=" * 60)
    sys.exit(len(errors))
