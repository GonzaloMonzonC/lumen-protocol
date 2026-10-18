#!/usr/bin/env python3
"""Verifica el RESTAURADO: la memoria volvio al nodo tras borrarla?"""
import re, socket, time
from pathlib import Path

KEY = re.search(r"^DDP_KEY=(.+)$",
                Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/hub.conf")
                .read_text(encoding="utf-8"), re.M).group(1).strip()


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
cfg = f'S ^CONFIG("ddp_peer")="http://192.168.1.10:8081" S ^CONFIG("ddp_hmac_key")="{KEY}" '


def muestra(r):
    return [x.strip() for x in r.split("\n")
            if x.strip() and "[rutina" not in x and B not in x and not x.startswith("/ #")]


print("=== memoria local AHORA (deberia estar vacia tras el K) ===")
r = limpia(c.manda(B + "'W \"$D=\",$D(^NODO),!\'", 18))
for x in muestra(r):
    print("  ", x)

print("\n=== RESTAURAR del hub ===")
r = limpia(c.manda(B + "'" + cfg + 'D ^%NM("R")\'', 30))
for x in muestra(r):
    print("  ", x)

print("\n=== que hay ahora en la memoria local? ===")
r = limpia(c.manda(B + "'S k=\"\" F  S k=$O(^NODO(\"Asus-1005HA\",k)) Q:k=\"\"  W k_\"=\",$G(^NODO(\"Asus-1005HA\",k)),!\'", 20))
for x in muestra(r):
    print("  ", x)

print("\n=== y el contenido de 'memoria' ===")
r = limpia(c.manda(B + "'S k=\"\" F  S k=$O(^NODO(\"Asus-1005HA\",\"memoria\",k)) Q:k=\"\"  W \"  \"_k_\" = \"_$G(^NODO(\"Asus-1005HA\",\"memoria\",k)),!\'", 20))
for x in muestra(r):
    print(x)
c.s.close()
