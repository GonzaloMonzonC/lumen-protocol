import sys, os, subprocess, tempfile, re, threading, time, shutil
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BIN = r'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/sim_flota.exe'
os.environ['LUMEN_LMDB_MAPSIZE_MB'] = '1024'

print('==================================================================')
print('FLOTA CON DEFENSAS: un intruso con epoch imposible')
print('==================================================================')
print()

def raiz():
    r = subprocess.run([BIN, 'raiz'], capture_output=True, text=True)
    for ln in r.stdout.splitlines():
        ln = ln.strip()
        if len(ln) == 64:
            return ln
    raise RuntimeError('sin raiz')

R = raiz()
print('1. raiz del armador:', R[:16], '...')

# Hub esperando 3 barcos: 2 normales y 1 con epoch imposible.
base = tempfile.mkdtemp(prefix='def-')
puerto = '47981'
hub = subprocess.Popen([BIN, 'hub', puerto, base + '/H', '3', R],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)

lineas_hub = []
addr = huella = None
t0 = time.time()
while time.time() - t0 < 30:
    ln = hub.stdout.readline()
    if not ln:
        break
    lineas_hub.append(ln.rstrip())
    m = re.match(r'LISTO\s+(\S+)\s+(\S+)', ln.strip())
    if m:
        addr, huella = m.group(1), m.group(2)
        break

print('2. hub escuchando en', addr)
print()

def barco(nombre, epoch_extra=0):
    d = base + '/' + nombre
    os.makedirs(d, exist_ok=True)
    env = dict(os.environ)
    env['LUMEN_RAIZ_ARMADOR'] = R
    if epoch_extra:
        env['LUMEN_EPOCH'] = str(epoch_extra)
    r = subprocess.run([BIN, 'barco', addr, huella, d, '50', nombre, R],
                       capture_output=True, text=True, timeout=200, env=env)
    return r

# 2 barcos normales y 1 INTRUSO con epoch imposible.
hilos = []
for i, extra in [(0, 0), (1, 0), (2, 999999)]:
    nombre = 'B%d' % i
    h = threading.Thread(target=lambda n=nombre, e=extra: barco(n, e))
    h.start()
    hilos.append(h)
for h in hilos:
    h.join()

print('3. tres barcos enviados')
time.sleep(2)
hub.terminate()
try:
    hub.wait(timeout=15)
except Exception:
    hub.kill()

out = hub.stdout.read()
print()
print('4. lo que dijo el hub:')
for ln in out.splitlines():
    if any(k in ln for k in ['FIN', 'RECHAZ', 'cuarentena', 'conflicto']):
        print('  ', ln[:140])

shutil.rmtree(base, ignore_errors=True)
