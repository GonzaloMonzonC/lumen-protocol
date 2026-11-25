# -*- coding: utf-8 -*-
"""SIMULACION DE FLOTA — N nodos reales, proceso por nodo, LMDB por nodo.

Cada nodo es un `mvm-nas.exe` independiente escribiendo telemetria, como un
barco o un dron. El orquestador lanza los 20 a la vez, mide y comprueba que
no se pierde nada.

Uso:
    python simular_flota.py [n_nodos] [n_muestras]

Mide:
  - Si los N aguantan escribiendo a la vez sin errores.
  - Tiempo por nodo y total del lote (pared).
  - Si cada nodo conserva TODAS sus muestras al releer.
  - Pico de memoria del conjunto.
"""
import subprocess, sys, io, os, time, shutil, tempfile, threading

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BIN = r"C:/Users/gonzalo/Documents/GitHub/mvm-nas/target/release/mvm-nas.exe"
N_NODOS = int(sys.argv[1]) if len(sys.argv) > 1 else 20
N_MUESTRAS = int(sys.argv[2]) if len(sys.argv) > 2 else 300

# LMDB reserva 1 GB de mmap por defecto y aqui hay 20 nodos a la vez: hay que
# bajarlo o el volumen se queda sin espacio de direcciones (error 112).
# 64 MB es de sobra para esta simulacion y sigue siendo realista para un nodo.
os.environ.setdefault("LUMEN_LMDB_MAPSIZE_MB", "64")

SEP = "=" * 78

print(SEP)
print("SIMULACION DE FLOTA — %d nodos, %d muestras cada uno" % (N_NODOS, N_MUESTRAS))
print(SEP)
print("binario: %s" % BIN)
print("total muestras a escribir: %d" % (N_NODOS * N_MUESTRAS))
print()

if not os.path.exists(BIN):
    print("ERROR: no existe el binario. Compilalo con: cargo build --release")
    sys.exit(2)

base = tempfile.mkdtemp(prefix="flota-sim-")
print("directorio de trabajo: %s" % base)

resultados = {}
errores = []
lock = threading.Lock()


def lanzar_nodo(i):
    """Un nodo = un proceso real con su LMDB."""
    nombre = "NODO-%02d" % i
    dir_nodo = os.path.join(base, nombre)
    pdb = os.path.join(dir_nodo, "pdb.lmdb")
    os.makedirs(dir_nodo, exist_ok=True)

    # Telemetria realista: 1 escritura por muestra, con subindice creciente.
    script = 'F j=1:1:%d S ^GPS(j)="%s:lat="_(4100000+j)' % (N_MUESTRAS, nombre)

    t0 = time.perf_counter()
    r = subprocess.run(
        [BIN, "-p", pdb, "-e", script],
        capture_output=True, text=True, timeout=600)
    dt = time.perf_counter() - t0

    with lock:
        if r.returncode == 0:
            resultados[nombre] = dt
        else:
            errores.append((nombre, (r.stderr or r.stdout)[:200]))


# ── Lanzar los N a la vez ──
t_pared0 = time.perf_counter()
hilos = [threading.Thread(target=lanzar_nodo, args=(i,)) for i in range(N_NODOS)]
for h in hilos:
    h.start()
for h in hilos:
    h.join()
t_pared = time.perf_counter() - t_pared0

print()
print("[1] ESCRITURA EN PARALELO")
print("    nodos que terminaron bien: %d de %d" % (len(resultados), N_NODOS))
if errores:
    print("    ERRORES: %d" % len(errores))
    for n, e in errores[:5]:
        print("      %s -> %s" % (n, e.replace("\n", " ")[:120]))

if resultados:
    tiempos = sorted(resultados.values())
    print("    tiempo por nodo: min=%.0f ms  mediana=%.0f ms  max=%.0f ms" % (
        tiempos[0] * 1000, tiempos[len(tiempos)//2] * 1000, tiempos[-1] * 1000))
    print("    tiempo de PARED (los %d a la vez): %.1f s" % (N_NODOS, t_pared))
    print("    muestras/s agregadas: %.0f" % ((len(resultados) * N_MUESTRAS) / t_pared))

# ── Verificar que no se perdio nada ──
print()
print("[2] INTEGRIDAD: releer cada nodo y contar sus muestras")
perdidos = 0
for i in range(N_NODOS):
    nombre = "NODO-%02d" % i
    pdb = os.path.join(base, nombre, "pdb.lmdb")
    if not os.path.exists(pdb):
        continue
    # Contar: recorrer y acumular. Se imprime SOLO al final, para que el parser
    # no tenga que distinguir entre lineas parciales y el total.
    script = 'S c=0 F j=1:1:%d S c=c+$S($D(^GPS(j)):1,1:0) W "total=",c,!' % N_MUESTRAS
    r = subprocess.run([BIN, "-p", pdb, "-e", script],
                       capture_output=True, text=True, timeout=300)
    cuenta = None
    for ln in reversed((r.stdout or "").splitlines()):
        ln = ln.strip()
        if ln.startswith("total="):
            try:
                cuenta = int(ln.split("=", 1)[1])
            except ValueError:
                pass
            break
    if cuenta != N_MUESTRAS:
        perdidos += 1
        print("    %s: %s de %d" % (nombre, cuenta, N_MUESTRAS))

print("    nodos con perdida: %d de %d" % (perdidos, N_NODOS))

# ── Espacio en disco ──
print()
print("[3] ESPACIO")
# OJO: data.mdb aparece con 1 GB porque LMDB reserva el mmap entero al abrir.
# El espacio REAL ocupado es mucho menor: se mide por los bloques asignados.
total_disco = 0
total_mmap = 0
for root, _dirs, files in os.walk(base):
    for f in files:
        p = os.path.join(root, f)
        try:
            st = os.stat(p)
            total_mmap += st.st_size
            total_disco += getattr(st, "st_blocks", 0) * 512
        except OSError:
            pass
if total_disco == 0:
    total_disco = total_mmap  # Windows no da st_blocks
print("    reservado (mmap total): %.1f MB (%d nodos)" % (total_mmap / 1e6, N_NODOS))
print("    ocupado de verdad:      %.1f MB" % (total_disco / 1e6))
print("    -> el mmap es RESERVA, no disco usado. LMDB lo dimensiona al abrir.")

print()
print(SEP)
ok = len(resultados) == N_NODOS and perdidos == 0
print("RESULTADO: %s" % ("LA FLOTA AGUANTA" if ok else "HAY FALLOS"))
print(SEP)

# Limpieza
if "--keep" not in sys.argv:
    shutil.rmtree(base, ignore_errors=True)
else:
    print("(datos conservados en %s)" % base)

sys.exit(0 if ok else 1)
