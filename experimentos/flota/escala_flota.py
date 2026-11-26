import sys, subprocess, os, tempfile, re, time, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BIN = r'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/sim_flota.exe'
# El hub necesita mapa para TODOS los hechos: 2048 MB con margen.
os.environ['LUMEN_LMDB_MAPSIZE_MB'] = '2048'

CASOS = [(20, 12000), (40, 6000), (40, 12000)]

for idx, (N, M) in enumerate(CASOS):
    base = tempfile.mkdtemp(prefix='esc-')
    puerto = 47940 + idx
    hub = subprocess.Popen([BIN, 'hub', str(puerto), base + '/H', str(N)],
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                           text=True, bufsize=1)
    l = hub.stdout.readline().strip()
    m = re.match(r'LISTO\s+(\S+)\s+(\S+)', l)
    if not m:
        print('%d x %d -> ERROR al arrancar el hub: %r' % (N, M, l[:150]))
        hub.kill(); continue
    addr, hu = m.group(1), m.group(2)

    def b(i, addr=addr, hu=hu, base=base, M=M):
        d = base + '/B%d' % i
        os.makedirs(d, exist_ok=True)
        for _ in range(30):
            r = subprocess.run([BIN, 'barco', addr, hu, d, str(M), 'B%d' % i],
                               capture_output=True, text=True, timeout=900)
            if r.returncode == 0:
                return
            time.sleep(0.2)

    ts = [threading.Thread(target=b, args=(i,)) for i in range(N)]
    for x in ts: x.start()
    for x in ts: x.join()
    try:
        hub.wait(timeout=900)
    except Exception:
        hub.kill()
    out = hub.stdout.read()
    fin = [l for l in out.splitlines() if l.startswith('FIN')]
    esperados = N * M
    print('=== %d barcos x %d = %d hechos ===' % (N, M, esperados))
    print('   ', fin[0] if fin else '(sin FIN)')
    for l in out.splitlines():
        if 'motivo=' in l or 'error=' in l:
            print('    ', l[:150])
    import shutil
    shutil.rmtree(base, ignore_errors=True)
