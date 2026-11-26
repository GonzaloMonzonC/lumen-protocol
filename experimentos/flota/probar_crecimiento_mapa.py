import sys, subprocess, os, tempfile, re, time, threading, shutil
sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BIN = r'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/sim_flota.exe'
# A PROPOSITO pequeño: 32 MB no da para 240.000 hechos. Si crece solo, funciona.
os.environ['LUMEN_LMDB_MAPSIZE_MB'] = '32'

N, M = 20, 12000
base = tempfile.mkdtemp(prefix='crece-')
hub = subprocess.Popen([BIN, 'hub', '47955', base + '/H', str(N)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                       text=True, bufsize=1)
l = hub.stdout.readline().strip()
m = re.match(r'LISTO\s+(\S+)\s+(\S+)', l)
addr, hu = m.group(1), m.group(2)
print('hub en %s · MAPSIZE inicial 32 MB · %d barcos x %d = %d hechos'
      % (addr, N, M, N*M))

def b(i):
    d = base + '/B%d' % i
    os.makedirs(d, exist_ok=True)
    for _ in range(40):
        r = subprocess.run([BIN, 'barco', addr, hu, d, str(M), 'B%d' % i],
                           capture_output=True, text=True, timeout=900)
        if r.returncode == 0:
            return
        time.sleep(0.2)

t0 = time.perf_counter()
ts = [threading.Thread(target=b, args=(i,)) for i in range(N)]
for x in ts: x.start()
for x in ts: x.join()
try:
    hub.wait(timeout=900)
except Exception:
    hub.kill()
dt = time.perf_counter() - t0

out = hub.stdout.read()
err = hub.stderr.read()

print()
print('=== CRECIMIENTOS DEL MAPA ===')
crec = [l for l in err.splitlines() if 'ampliado' in l]
for l in crec:
    print('   ', l.strip())
print('   total: %d ampliaciones' % len(crec))

print()
print('=== RESULTADO ===')
for l in out.splitlines():
    if l.startswith('FIN'):
        print('   ', l)
fallos = [l for l in out.splitlines() if 'MDB_MAP_FULL' in l or 'techo' in l]
if fallos:
    print('   FALLOS DE MAPA: %d' % len(fallos))
    for l in fallos[:3]:
        print('     ', l[:140])
print('    tiempo: %.1f s' % dt)

shutil.rmtree(base, ignore_errors=True)
