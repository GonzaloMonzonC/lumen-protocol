#!/usr/bin/env python3
"""PRUEBA COMPLETA del paso 3: guardar -> BORRAR -> restaurar (memoria persistente sin disco)."""
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
        with urllib.request.urlopen(req, timeout=25) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"http": e.code, "body": e.read().decode()[:150]}
    except Exception as e:
        return {"err": str(e)}


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


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

    def manda(self, txt, seg=16.0):
        self.s.sendall(txt.encode() + b"\r\n")
        return self.leer(seg)


c = T("192.168.1.20", 2323)
c.leer(4)
B = "/opt/mvm/mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e "
CFG = f'S ^CONFIG("ddp_peer")="http://192.168.1.10:8081" S ^CONFIG("ddp_hmac_key")="{KEY}" '


def muestra(r):
    return [x.strip() for x in r.split("\n")
            if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #")]


def run(m, seg=20):
    for x in muestra(limpia(c.manda(B + "'" + m + "'", seg))):
        print("   ", x)


print("=== 0) partir en limpio: borrar la memoria local ===")
run(CFG + 'K ^NODO W "borrada",!')

print("\n=== 1) GUARDAR (crea + empuja al hub) ===")
run(CFG + 'D ^%NM("S")', 30)

print("\n=== 2) que hay en la memoria local? ===")
run('S k="" F  S k=$O(^NODO("Asus-1005HA","memoria",k)) Q:k=""  W "    "_k_" = "_$G(^NODO("Asus-1005HA","memoria",k)),!')

print("\n=== 3) el hub la guarda? ===")
d = hub_get("/ddp/pull?ns=NODO&limit=50&depth=2")
ents = d.get("entries", []) if isinstance(d, dict) else []
mios = [e for e in ents if e.get("subs") and e["subs"][0] == "Asus-1005HA" and e.get("value")]
print(f"    entradas con VALOR bajo Asus-1005HA: {len(mios)}")
for e in mios[:6]:
    print(f"      {e['subs']} = {str(e['value'])[:44]}")

print("\n=== 4) APAGON: borrar TODO local ===")
run(CFG + 'K ^NODO W "memoria local borrada",!')
run('W "    $D(^NODO) = ",$D(^NODO),!')

print("\n=== 5) RESTAURAR del hub ===")
run(CFG + 'D ^%NM("R")', 30)

print("\n=== 6) LA MEMORIA HA VUELTO? ===")
run('W "    $D(^NODO) = ",$D(^NODO),!')
run('S k="" F  S k=$O(^NODO("Asus-1005HA","memoria",k)) Q:k=""  W "    "_k_" = "_$G(^NODO("Asus-1005HA","memoria",k)),!')
c.s.close()
