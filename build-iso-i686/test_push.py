#!/usr/bin/env python3
"""PASO 1 end-to-end: configurar ddp_peer + registrar + push, TODO en una invocacion."""
import hashlib, hmac, json, re, socket, time, urllib.request, urllib.error
from pathlib import Path

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()


def hub_get(path):
    ts = str(int(time.time()))
    sig = hmac.new(KEY.encode(), (ts + path + KEY).encode(), hashlib.sha256).hexdigest()
    req = urllib.request.Request("http://127.0.0.1:8081" + path,
                                 headers={"X-DDP-Timestamp": ts, "X-DDP-HMAC": sig})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]
    except Exception as e:
        return "ERR", str(e)


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


c = T("192.168.1.20", 2323)
c.leer(4)
B = "/opt/mvm/mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e "

# configurar + registrar + empujar EN UNA SOLA invocacion (misma vista de la PDB)
m = (f'S ^CONFIG("ddp_peer")="http://192.168.1.10:8081" '
     f'S ^CONFIG("ddp_hmac_key")="{KEY}" D ^%NR("192.168.1.20")')
print("=== registrar + empujar al hub ===")
r = limpia(c.manda(B + "'" + m + "'", 25))
for x in r.split("\n"):
    if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #"):
        print("  ", x.strip())

print("\n=== DDP: estado del nodo ===")
r = limpia(c.manda(B + "'D ^%DS'", 18))
for x in r.split("\n"):
    if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #"):
        print("  ", x.strip())
c.s.close()

print("\n=== /ddp/nodes EN EL HUB ===")
st, d = hub_get("/ddp/nodes")
print(f"  HTTP {st}")
if isinstance(d, dict):
    print(f"  n = {d.get('n')}")
    for k, v in (d.get("nodos") or {}).items():
        print(f"    {k} -> {json.dumps(v, ensure_ascii=False)}")
else:
    print("  ", d)
