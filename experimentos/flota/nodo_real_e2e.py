import sys, subprocess, os, tempfile, re, time, shutil, sqlite3
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _perfil_sqlite import crear_perfil, subkey

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

BIN = r'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/lumen-nodo.exe'
base = tempfile.mkdtemp(prefix='nodo-real-')

def run(*args, timeout=120):
    return subprocess.run([BIN] + list(args), capture_output=True, text=True, timeout=timeout)

def campo(texto, nombre):
    m = re.search(nombre + r'\s*:\s*([0-9a-f]{64})', texto)
    return m.group(1) if m else None

print('=== NODO REAL, de punta a punta ===')
print()

r = run('--nueva-raiz')
raiz_priv = campo(r.stdout + r.stderr, 'semilla')
raiz_pub = campo(r.stdout + r.stderr, 'clave_publica')
print('1. raiz del armador:  %s...' % (raiz_pub or '?')[:16])

r = run('--nueva-identidad')
barco_priv = campo(r.stdout + r.stderr, 'semilla')
barco_pub = campo(r.stdout + r.stderr, 'clave_publica')
print('2. barco (publica):   %s...' % (barco_pub or '?')[:16])

if not (raiz_priv and barco_pub):
    print('FALTAN CLAVES'); sys.exit(2)

# El hub necesita identidad propia: es la unica forma de que lea la raiz.
r = run('--nueva-identidad')
hub_priv = campo(r.stdout + r.stderr, 'semilla')
hub_pub = campo(r.stdout + r.stderr, 'clave_publica')

# 3. Perfiles con el subkey BINARIO correcto
pdb_barco = base + '/barco.db'
pdb_hub = base + '/hub.db'
crear_perfil(pdb_barco, {
    ('SYS','role'):'Store', ('SYS','mode'):'Lan', ('SYS','transport'):'Quic',
    ('SYS','storage'):'Lmdb', ('SYS','identity'):'pubkey', ('SYS','sign'):'hash-chain',
    ('SYS','raiz_armador'):raiz_pub, ('SYS','clave_publica'):barco_pub})
crear_perfil(pdb_hub, {
    ('SYS','role'):'Hub', ('SYS','mode'):'Lan', ('SYS','transport'):'Quic',
    ('SYS','storage'):'Lmdb', ('SYS','identity'):'pubkey', ('SYS','sign'):'hash-chain',
    ('SYS','raiz_armador'):raiz_pub, ('SYS','clave_publica'):hub_pub})
print('3. perfiles escritos (subkey binario)')

# 4. Certificado
r = run('--emitir-certificado', '--raiz-semilla', raiz_priv,
        '--armador', 'ARMADOR-T', '--barco', 'BARCO-T', '--clave-barco', barco_pub)
print('4. certificado: rc=%d' % r.returncode)
cert_linea = ''
for ln in (r.stdout + r.stderr).splitlines():
    if '|' in ln and len(ln) > 40:
        cert_linea = ln.strip()
print('   linea:', (cert_linea[:60] + '...') if cert_linea else '(no encontrada)')

# 5. Registrar el barco en ^FLOTA del hub
r = run('--registrar-barco', '--pdb', pdb_hub, '--almacen', base + '/alm-hub',
        '--barco', 'BARCO-T', '--clave-barco', barco_pub, '--certificado', cert_linea)
print('5. registro de flota: rc=%d' % r.returncode)
if r.returncode != 0:
    print('   ', (r.stdout + r.stderr).strip().splitlines()[-1][:140])

# 6. Arrancar hub
addr = '127.0.0.1:47972'
hub = subprocess.Popen(
    [BIN, '--escuchar', '--pdb', pdb_hub, '--almacen', base + '/alm-hub',
     '--set', 'listen=' + addr, '--semilla', hub_priv],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
huella = None
salida_hub = []
t0 = time.time()
while time.time() - t0 < 30:
    ln = hub.stdout.readline()
    if not ln:
        break
    salida_hub.append(ln.rstrip())
    m = re.search(r'huella de mi certificado:\s*([0-9a-f]{64})', ln)
    if m:
        huella = m.group(1)
    if 'listo' in ln:
        break
print('6. hub escuchando, huella: %s...' % (huella or '?')[:16])

# 7. Enviar
print('7. el barco envia una escritura firmada')
r = run('--enviar', addr, '^FLOTA(BARCO-T,lat,1)=41.38',
        '--pdb', pdb_barco, '--almacen', base + '/alm-barco',
        '--set', 'identity=pin', '--set', 'pin=' + (huella or ''),
        '--semilla', barco_priv)
print('   rc=%d' % r.returncode)
for ln in (r.stdout + r.stderr).splitlines():
    if 'respuesta' in ln or 'ERROR' in ln or 'rechaz' in ln:
        print('   ', ln[:140])

time.sleep(1)
hub.terminate()
try:
    hub.wait(timeout=10)
except Exception:
    hub.kill()
print()
print('8. lo que hizo el hub:')
for ln in hub.stdout.read().splitlines()[:20]:
    print('   ', ln[:135])

shutil.rmtree(base, ignore_errors=True)
