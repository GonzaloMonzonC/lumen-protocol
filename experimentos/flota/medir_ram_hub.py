import sys, subprocess, os, tempfile, re, time, threading
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
BIN = r'C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-nodo/target/release/sim_flota.exe'
os.environ['LUMEN_LMDB_MAPSIZE_MB'] = '64'
base = tempfile.mkdtemp(prefix='ram-')
N, M = 20, 6000
hub = subprocess.Popen([BIN,'hub','47911',base+'/H',str(N)],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1)
l = hub.stdout.readline().strip()
m = re.match(r'LISTO\s+(\S+)\s+(\S+)', l)
addr, hu = m.group(1), m.group(2)
print('hub %s · %d barcos x %d = %d hechos' % (addr, N, M, N*M))

# Memoria via WMI (mas fiable que tasklist /FO CSV)
pico = {'kb': 0}
def medir():
    ps = ("Get-Process -Id %d | Select-Object -ExpandProperty WorkingSet64" % hub.pid)
    while hub.poll() is None:
        try:
            r = subprocess.run(['powershell','-NoProfile','-Command',ps],
                               capture_output=True, text=True, timeout=10)
            v = r.stdout.strip()
            if v.isdigit():
                pico['kb'] = max(pico['kb'], int(v)//1024)
        except Exception:
            pass
        time.sleep(0.2)
t = threading.Thread(target=medir, daemon=True); t.start()

def b(i):
    d = base + '/B%d' % i; os.makedirs(d, exist_ok=True)
    for _ in range(30):
        r = subprocess.run([BIN,'barco',addr,hu,d,str(M),'B%d'%i],
                           capture_output=True, text=True, timeout=600)
        if r.returncode == 0: return
        time.sleep(0.2)

ts = [threading.Thread(target=b, args=(i,)) for i in range(N)]
for x in ts: x.start()
for x in ts: x.join()
try: hub.wait(timeout=300)
except Exception: hub.kill()
time.sleep(0.3)
print([l for l in hub.stdout.read().splitlines() if l.startswith('FIN')])
print('PICO RAM del hub: %.1f MB  (%.2f KB por hecho)' % (pico['kb']/1024, pico['kb']/(N*M)))
