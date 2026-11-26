import sys, subprocess, os, tempfile, re, time
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BIN = r'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/sim_flota.exe'
os.environ['LUMEN_LMDB_MAPSIZE_MB'] = '512'

# Raiz
r = subprocess.run([BIN, 'raiz'], capture_output=True, text=True)
raiz = [l.strip() for l in r.stdout.splitlines() if len(l.strip()) == 64][0]
print('raiz:', raiz[:16], '...')

base = tempfile.mkdtemp(prefix='diag-flota-')
hub = subprocess.Popen([BIN, 'hub', '47998', base + '/H', '1', raiz],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
l = hub.stdout.readline().strip()
m = re.match(r'LISTO\s+(\S+)\s+(\S+)', l)
addr, hu = m.group(1), m.group(2)
print('hub:', addr)

os.makedirs(base + '/B', exist_ok=True)
rb = subprocess.run([BIN, 'barco', addr, hu, base + '/B', '5', 'BARCO-T', raiz],
                    capture_output=True, text=True, timeout=120)
print('barco rc=%d' % rb.returncode)
print('  stdout:', rb.stdout.strip()[:200])
if rb.stderr.strip():
    print('  stderr:', rb.stderr.strip()[:200])

try:
    hub.wait(timeout=60)
except Exception:
    hub.kill()
out = hub.stdout.read()
print()
print('hub:')
for ln in out.splitlines():
    print('  ', ln[:160])
err = hub.stderr.read()
if err.strip():
    print('hub stderr:', err[:300])
