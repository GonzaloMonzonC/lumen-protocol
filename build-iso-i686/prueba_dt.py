#!/usr/bin/env python3
"""Sube %D y %T al nodo y PRUEBA $$HOY^%D y $$AHORA^%T en el metal."""
import base64, socket, time
from pathlib import Path

IP = "192.168.1.23"
ORIG = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines")
DEST = "/opt/mvm/routines"


def limpia(b):
    o, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            o.append(b[i])
            i += 1
    return bytes(o).decode("utf-8", "replace").replace("\r", "")


def sh(lineas, seg=8):
    s = socket.create_connection((IP, 2323), timeout=60)
    s.settimeout(60)
    time.sleep(0.5)
    s.recv(65536)
    s.sendall(("\n".join(lineas) + "\n").encode())
    out, fin = b"", time.time() + seg
    while time.time() < fin:
        try:
            d = s.recv(32768)
            if not d:
                break
            out += d
        except socket.timeout:
            break
    s.close()
    return limpia(out)


def cons(cmd, seg=8):
    s = socket.create_connection((IP, 23), timeout=40)
    s.settimeout(40)
    time.sleep(0.6)
    s.recv(65536)
    s.sendall((cmd + "\r\n").encode())
    out, fin = b"", time.time() + seg
    while time.time() < fin:
        try:
            d = s.recv(16384)
            if not d:
                break
            out += d
        except socket.timeout:
            break
    s.close()
    r = limpia(out)
    return [x.strip() for x in r.split("\n") if x.strip() and "/m" not in x and "nodo]" not in x and "»" not in x and "^CONFIG" not in x]


print("=== 1. subiendo %D.m y %T.m ===")
for f in ("%D.m", "%T.m"):
    b64 = base64.b64encode((ORIG / f).read_bytes()).decode()
    L = ["rm -f /tmp/r.b64"]
    for i in range(0, len(b64), 3000):
        L.append("printf '%s' '" + b64[i:i + 3000] + "' >> /tmp/r.b64")
    L.append(f"base64 -d /tmp/r.b64 > '{DEST}/{f}' && echo SUBIDO")
    out = sh(L, 8)
    print(f"   {f}: {'SUBIDO' if 'SUBIDO' in out else 'FALLO'}")

print("\n=== 2. LA PRUEBA EN EL METAL ===")
for etq, cmd in (("$$HOY^%D", '/m W "FECHA: ",$$HOY^%D,!'),
                 ("$$AHORA^%T", '/m W "HORA: ",$$AHORA^%T,!'),
                 ("DIV^%D(7,2)", '/m W "7/2 entero: ",$$DIV^%D(7,2),!')):
    r = cons(cmd, 8)
    print(f"   {etq:<14} -> {' | '.join(r[:3]) if r else '(vacio)'}")
