#!/usr/bin/env python3
"""PASO 3 en caliente: guardar la memoria del Asus en el hub, BORRARLA local y restaurarla.
El dinero: la memoria vuelve -> persistencia sin disco."""
import hashlib, hmac, json, re, socket, time, urllib.request, urllib.error
from pathlib import Path

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()
NM = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%NM.m").read_bytes().decode("utf-8")


def hub_get(path):
    ts = str(int(time.time()))
    sig = hmac.new(KEY.encode(), (ts + path + KEY).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("http://127.0.0.1:8081" + path,
                                 headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode()[:150]}
    except Exception as e:
        return {"err": str(e)}


class T:
    def __init__(self, h, p, t=45):
        self.s = socket.create_connection((h, p), timeout=t)
        self.s.settimeout(t)

    def leer(self, seg=3.0):
        fin, out = time.time() + seg, b""
        while time.time() < fin:
            try:
                d = self.s.recv(8192)
                if not d:
                    break
                out += d
            except socket.timeout:
                break
        return out

    def manda(self, txt, seg=14.0):
        self.s.sendall(txt.encode() + b"\r\n")
        return self.leer(seg)


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def muestra(r, B):
    return [x.strip() for x in r.split("\n")
            if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #")]


c = T("192.168.1.20", 2323)
c.leer(4)
B = "/opt/mvm/mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e "

# copiar %NM
c.manda("cat > /opt/mvm/routines/%NM.m << 'LUMENEOF'", 3)
for linea in NM.split("\n"):
    c.s.sendall(linea.encode() + b"\r\n")
c.manda("LUMENEOF", 3)
print("=== %NM copiada al Asus ===")

cfg = f'S ^CONFIG("ddp_peer")="http://192.168.1.10:8081" S ^CONFIG("ddp_hmac_key")="{KEY}" '

print("\n=== 1) GUARDAR memoria en el hub ===")
r = limpia(c.manda(B + "'" + cfg + 'D ^%NM("S")\'', 30))
for x in muestra(r, B):
    print("  ", x)

print("\n=== 2) el hub la tiene? ===")
d = hub_get("/ddp/pull?ns=NODO&limit=50&depth=2")
ents = d.get("entries", []) if isinstance(d, dict) else []
print(f"  entradas en NODO: {len(ents)}")
for e in ents[:8]:
    print(f"    {e.get('subs')} = {str(e.get('value'))[:40]}")

print("\n=== 3) BORRAR la memoria local (simula apagon) ===")
r = limpia(c.manda(B + "'" + cfg + 'K ^NODO W "BORRADA",!\'', 20))
for x in muestra(r, B):
    print("  ", x)
r = limpia(c.manda(B + "'W \"memoria local: \"_$D(^NODO),!\'", 18))
for x in muestra(r, B):
    print("  ", x)

print("\n=== 4) RESTAURAR del hub ===")
r = limpia(c.manda(B + "'" + cfg + 'D ^%NM("R")\'', 30))
for x in muestra(r, B):
    print("  ", x)
r = limpia(c.manda(B + "'W \"restaurada: \"_$G(^NODO(\\\"Asus-1005HA\\\",\\\"memoria\\\",\\\"creada\\\")),!\'", 20))
for x in muestra(r, B):
    print("  ", x)
c.s.close()
