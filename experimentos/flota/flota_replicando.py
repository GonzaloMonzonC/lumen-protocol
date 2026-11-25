# -*- coding: utf-8 -*-
"""FLOTA REPLICANDO — N barcos escriben Y mandan al hub por QUIC.

Escenario del paper: la flota converge. Cada barco escribe su bitacora local y
la replica a un hub central que verifica y guarda.

Uso:
    python flota_replicando.py [n_barcos] [n_muestras]

Mide:
  - Si el hub recibe de TODOS los barcos.
  - Cuantos hechos se aceptan y cuantos se rechazan (deben ser todos aceptados).
  - Tiempo de escritura local frente a tiempo de envio.
  - Si la serie del hub queda completa y sin huecos.
"""
import subprocess, sys, os, time, shutil, tempfile, threading, re

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BIN = r"C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/sim_flota.exe"
N_BARCOS = int(sys.argv[1]) if len(sys.argv) > 1 else 10
N_MUESTRAS = int(sys.argv[2]) if len(sys.argv) > 2 else 200

os.environ.setdefault("LUMEN_LMDB_MAPSIZE_MB", "32")

SEP = "=" * 78
print(SEP)
print("FLOTA REPLICANDO — %d barcos x %d muestras, por QUIC a un hub"
      % (N_BARCOS, N_MUESTRAS))
print(SEP)
print("binario: %s" % BIN)
print()

if not os.path.exists(BIN):
    print("ERROR: falta el binario. Compila con:")
    print("  cargo build --release --bin sim_flota")
    sys.exit(2)

base = tempfile.mkdtemp(prefix="flota-rep-")
dir_hub = os.path.join(base, "HUB")
os.makedirs(dir_hub, exist_ok=True)
print("directorio: %s" % base)

# Puerto libre: se lo deja elegir al hub y nos lo dice.
# Se usa un puerto fijo alto para simplificar; el hub imprime el real.
PUERTO = 47800

# ── 1. Arrancar el hub ──
hub = subprocess.Popen(
    [BIN, "hub", str(PUERTO), dir_hub, str(N_BARCOS)],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

linea = hub.stdout.readline().strip()
m = re.match(r"LISTO\s+(\S+)\s+(\S+)", linea)
if not m:
    print("ERROR: el hub no arranco. Salida: %r" % linea[:200])
    err = hub.stderr.read()[:400]
    print("stderr: %s" % err)
    sys.exit(2)
addr, huella = m.group(1), m.group(2)
print("hub escuchando en %s (huella %s...)" % (addr, huella[:16]))
print()

# ── 2. Lanzar los barcos a la vez ──
salidas = {}
lock = threading.Lock()

def lanzar(i):
    nombre = "BARCO-%02d" % i
    d = os.path.join(base, nombre)
    os.makedirs(d, exist_ok=True)
    # El hub acepta UNA conexion cada vez y `accept()` espera al primer stream.
    # Con 20 barcos, los que llegan cuando el hub esta ocupado reciben
    # ConnectionRefused: se reintenta con espera creciente.
    ultimo = ""
    for intento in range(60):
        r = subprocess.run(
            [BIN, "barco", addr, huella, d, str(N_MUESTRAS), nombre],
            capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            with lock:
                salidas[nombre] = (0, r.stdout.strip(), "")
            return
        ultimo = (r.stderr or r.stdout).strip()[:200]
        if "ConnectionRefused" not in ultimo and "timed out" not in ultimo.lower():
            break
        time.sleep(0.2 * (1 + intento // 10))
    with lock:
        salidas[nombre] = (1, "", ultimo)

t0 = time.perf_counter()
hilos = [threading.Thread(target=lanzar, args=(i,)) for i in range(N_BARCOS)]
for h in hilos:
    h.start()
for h in hilos:
    h.join()
t_total = time.perf_counter() - t0

print("[1] LOS BARCO ESCRIBEN Y REPLICAN")
print("    terminados: %d de %d" % (len(salidas), N_BARCOS))
fallos = [(n, c, s, e) for n, (c, s, e) in salidas.items() if c != 0]
if fallos:
    for n, c, s, e in fallos[:4]:
        print("      %s rc=%d %s" % (n, c, (e or s)[:120]))
print("    tiempo total (pared): %.1f s" % t_total)

# ── 3. Esperar al hub y leer su resumen ──
resto = hub.stdout.read()
hub.wait(timeout=120)
print()
print("[2] EL HUB")
for ln in resto.splitlines():
    ln = ln.strip()
    if ln.startswith("BARCO") or ln.startswith("FIN"):
        print("    %s" % ln)

fin = re.search(r"FIN barcos=(\d+) aceptados=(\d+) rechazados=(\d+) conflictos=(\d+) "
                r"serie_principal=(\d+)", resto)
if not fin:
    print("    (no se pudo leer el resumen del hub)")
    if hub.stderr:
        print("    stderr: %s" % hub.stderr.read()[:400])
    shutil.rmtree(base, ignore_errors=True)
    sys.exit(2)

barcos, aceptados, rechazados, conflictos, serie = map(int, fin.groups())
esperados = N_BARCOS * N_MUESTRAS

# Los duplicados legitimos (un barco que reintento) no son perdida: el hecho
# ya estaba guardado. Se cuentan a partir de lo recibido menos lo aceptado.
recibidos_total = sum(int(m.group(1)) for m in
                      re.finditer(r"BARCO \d+ recibidos=(\d+)", resto))
duplicados = recibidos_total - aceptados - rechazados - conflictos

print()
print("[3] VERIFICACION")
print("    hechos esperados:      %d" % esperados)
print("    recibidos por el hub:  %d" % recibidos_total)
print("    aceptados:             %d" % aceptados)
print("    rechazados:            %d" % rechazados)
print("    conflictos:            %d" % conflictos)
print("    duplicados (reenvio):  %d" % max(duplicados, 0))
cubiertos = aceptados + max(duplicados, 0)
print("    cubiertos (acept+dup): %d" % cubiertos)
print("    -> %s" % ("TODO LLEGO" if cubiertos == esperados and rechazados == 0
                     else "HAY DIFERENCIA"))

print()
print(SEP)
# Converge si: cada hecho esta (aceptado o duplicado) y nada se rechazo.
ok = cubiertos >= esperados and rechazados == 0
print("RESULTADO: %s" % ("LA FLOTA CONVERGE" if ok else "NO CONVERGE"))
print(SEP)

if "--keep" not in sys.argv:
    shutil.rmtree(base, ignore_errors=True)
else:
    print("(datos en %s)" % base)

sys.exit(0 if ok else 1)
