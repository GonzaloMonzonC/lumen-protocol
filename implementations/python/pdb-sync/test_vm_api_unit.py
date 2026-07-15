#!/usr/bin/env python3
"""Test unitario de MVM Web Engine — tests con M real (sintaxis MSM)."""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

import vm_api
from m_routines import register

ok_count = 0
fail_count = 0

def ok(cond, msg):
    global ok_count, fail_count
    if cond:
        ok_count += 1
        print(f"  ✅ {msg}")
    else:
        fail_count += 1
        print(f"  ❌ {msg}")

print("=" * 60)
print("🧪 Unit Tests — MVM Web Engine (MSM syntax)")
print("=" * 60)

# ── 1. register_web ──
print("\n📝 register_web / web_route")
vm_api.register_web("test/hola", "HOLA^%T")
r = vm_api.web_route("test/hola")
ok(r == "HOLA^%T", f"route (got '{r}')")
r2 = vm_api.web_route("noexiste")
ok(r2 is None, f"no existe → None (got {r2})")

# ── 2. Salida simple ──
print("\n⚙️ WRITE básico")
register("SIMPLE^%T", 'SIMPLE W "hello" Q')
out, err = vm_api.exec_m_full_output("SIMPLE^%T")
ok(err is None, f"sin error (err={err})")
ok(out == "hello", f"output='{out}'")

# ── 3. Nuevas líneas con ! ──
print("\n↩️ WRITE con ! (newline)")
register("NL^%T", 'NL W "linea1",!,"linea2" Q')
out, err = vm_api.exec_m_full_output("NL^%T")
ok(err is None, f"sin error (err={err})")
ok("linea1" in out and "linea2" in out, f"nuevas líneas (out={repr(out)})")
ok("\n" in out, "contiene newline real")

# ── 4. Variables y args ──
print("\n🔢 Args ($1, $2)")
register("VARS^%T", 'VARS W $1," + ",$2," = ",$1+$2 Q')
out, err = vm_api.exec_m_full_output("VARS^%T", args=[3, 4])
ok(err is None, "sin error")
ok(out == "3 + 4 = 7", f"args (got '{out}')")

# ── 5. FOR loop ──
print("\n🔁 FOR loop")
register("LOOP^%T", 'LOOP N i F i=1:1:3 W i," " Q')
out, err = vm_api.exec_m_full_output("LOOP^%T")
ok(err is None, f"sin error (err={err})")
ok(out == "1 2 3 ", f"FOR loop (got '{out}')")

# ── 6. IF ──
print("\n🔀 IF condicional")
register("IF^%T", 'IF N x S x=10 I x>5 W "MAYOR" E  W "MENOR" Q')
out, err = vm_api.exec_m_full_output("IF^%T")
ok(err is None, "sin error")
ok(out == "MAYOR", f"IF (got '{out}')")

# ── 7. HTML simple ──
print("\n🖥️ HTML básico")
register("HTML^%T", 'HTML W "<html>",!,"<body>",!,"<h1>Hola</h1>",!,"</body>",!,"</html>" Q')
out, err = vm_api.exec_m_full_output("HTML^%T")
ok(err is None, "sin error")
ok("<html>" in out, "HTML válido")
ok("<h1>Hola</h1>" in out, "contenido")
print(f"  📏 {len(out)} bytes")

# ── 8. HTML con CSS inline (como los de cf-monitor) ──
print("\n🎨 HTML + CSS (estilo LUMEN)")
register("DASH^%T", """DASH
W "<!DOCTYPE html>"
W "<html><head>"
W "<meta charset='utf-8'>"
W "<meta name='viewport' content='width=device-width,initial-scale=1'>"
W "<style>"
W "*{margin:0;padding:0;box-sizing:border-box}"
W "body{font-family:system-ui,sans-serif;padding:16px;max-width:640px;margin:0 auto;background:#0a0a0f;color:#ddd}"
W "h1{font-size:1.25rem;margin-bottom:1rem;border-bottom:2px solid #222;padding-bottom:.5rem}"
W ".card{background:#13131a;border:1px solid #333;border-radius:8px;padding:12px;margin-bottom:8px}"
W "</style></head><body>"
W "<h1>Test Dashboard</h1>"
W "<div class='card'><strong>Status:</strong> OK</div>"
W "</body></html>"
Q
""")
out, err = vm_api.exec_m_full_output("DASH^%T")
ok(err is None, f"sin error (err={err})")
ok("<!DOCTYPE html>" in out, "DOCTYPE")
ok("viewport" in out, "mobile-first")
ok("#0a0a0f" in out, "fondo oscuro")
ok("#13131a" in out, "tarjetas oscuras")
ok("Test Dashboard" in out, "título")
ok("<strong>Status:</strong> OK" in out, "datos inline")
print(f"  📏 {len(out)} bytes HTML")

# ── 9. Error de compilación ──
print("\n💥 Rutina rota")
register("ERR^%T", 'ERR W "ok" S x=ZZZZ_UNDEFINED Q')
out, err = vm_api.exec_m_full_output("ERR^%T")
ok(err is not None, f"debe fallar (err='{err}')")
ok(out is None, "output None con error")

# ── 10. Rutina inexistente ──
print("\n❓ Rutina no encontrada")
out, err = vm_api.exec_m_full_output("NOEXISTO")
ok(out is None, "output None")
ok(err is not None and "not found" in str(err), f"error descriptivo (err='{err}')")

# ── 11. Registro y lookup masivo ──
print("\n📋 10 rutas + lookup")
for i in range(10):
    rname = f"R{i}^%MASS"
    register(rname, f"{rname} W '{i}' Q")
    vm_api.register_web(f"mass/{i}", rname)
ok(len(vm_api._local_routes) >= 10, f"{len(vm_api._local_routes)} rutas registradas")
r = vm_api.web_route("mass/5")
ok(r == "R5^%MASS", f"lookup masivo (got '{r}')")

# ── Resultado ──
print("\n" + "=" * 60)
total = ok_count + fail_count
print(f"Resultados: {ok_count}/{total} OK  |  {fail_count} errores")
if fail_count:
    print(f"❌ FALLAN {fail_count}")
else:
    print("🎉 TODOS PASAN")
print("=" * 60)
sys.exit(fail_count)
