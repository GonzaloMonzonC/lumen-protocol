#!/usr/bin/env python3
"""%NR v2: sin postcondicionales dentro de WRITE (M-Light no los traga ahi)."""
import hashlib, hmac, json, re, socket, time, urllib.request, urllib.error
from pathlib import Path

NR = r'''%NR(IP) ; %NR - Registro del NODO en el ecosistema (namespace ^NODOS)
 ; D ^%NR("192.168.1.20") -> escribe ^NODOS(<id>,...) y lo EMPUJA al hub.
 ; Lo llama el init al arrancar. Sirve tambien como LATIDO (actualiza "ultima").
 ; ID: ^CONFIG("nodo_id") manda; si no, el nombre del DMI ^SYS("NODO") saneado.
 N ID,TS,TXT
 S ID=$G(^CONFIG("nodo_id"))
 I ID="" S ID=$TR($G(^SYS("NODO"))," ./()","-")
 I ID="" S ID="nodo-desconocido"
 S TS=$H
 I '$D(^NODOS(ID,"primera")) S ^NODOS(ID,"primera")=TS
 S ^NODOS(ID,"nombre")=$G(^SYS("NODO"))
 S ^NODOS(ID,"id")=ID
 I $G(IP)'="" S ^NODOS(ID,"ip")=$G(IP)
 I $G(^CAPACIDAD("ram_mb"))'="" S ^NODOS(ID,"ram_mb")=$G(^CAPACIDAD("ram_mb"))
 I $G(^CAPACIDAD("cpu"))'="" S ^NODOS(ID,"cpu")=$G(^CAPACIDAD("cpu"))
 S ^NODOS(ID,"ultima")=TS
 S TXT="registrado: "_ID
 I $G(IP)'="" S TXT=TXT_" ("_$G(IP)_")"
 W TXT,!
 I $G(^CONFIG("ddp_peer"))="" W "sin hub: no se envia",! Q
 W "hub: ",$DEVICE("ddp:push","NODOS"),!
 Q
'''
Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%NR.m").write_text(
    NR, encoding="utf-8", newline="")
print("%NR.m v2 escrita")

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
    def __init__(self, h, p, t=40):
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

    def manda(self, txt, seg=12.0):
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
c.manda("cat > /opt/mvm/routines/%NR.m << 'LUMENEOF'", 3)
for linea in NR.split("\n"):
    c.s.sendall(linea.encode() + b"\r\n")
c.manda("LUMENEOF", 3)
print("routine v2 copiada al Asus")

B = "/opt/mvm/mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e "
print("\n=== registrar el Asus ===")
r = limpia(c.manda(B + "'D ^%NR(\"192.168.1.20\")'", 20))
for x in r.split("\n"):
    if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #"):
        print("  ", x.strip())
c.s.close()

print("\n=== /ddp/nodes en el hub ===")
st, d = hub_get("/ddp/nodes")
print(f"  HTTP {st}")
if isinstance(d, dict):
    print(f"  n = {d.get('n')}")
    for k, v in (d.get("nodos") or {}).items():
        print(f"    {k} -> {json.dumps(v, ensure_ascii=False)}")
else:
    print("  ", d)
