#!/usr/bin/env python3
"""Sube las rutinas nuevas al nodo (.23) y las PRUEBA de verdad."""
import base64
import socket
import time
from pathlib import Path

IP = "192.168.1.20"  # se sobreescribe abajo
IP = "192.168.1.23"
DEST = "/opt/mvm/routines"
ORIG = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines")
RUTINAS = ["%UTL.m", "%PAGE.m", "%D.m", "%T.m", "%SS.m", "%HELP.m"]


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def sesion(lineas, espera=6.0):
    """Una conexion, manda varias lineas, devuelve todo lo leido."""
    s = socket.create_connection((IP, 2323), timeout=90)
    s.settimeout(90)
    time.sleep(0.4)
    s.recv(65536)
    s.sendall(("\n".join(lineas) + "\n").encode())
    out, fin = b"", time.time() + espera
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


print("=== 1. que rutinas tiene el nodo AHORA ===")
r = sesion(["ls /opt/mvm/routines/ | wc -l",
            "ls /opt/mvm/routines/ | grep -E 'UTL|PAGE|SS|HELP'"], 8)
print("   " + r.replace("\n", "\n   ")[:600])

print("\n=== 2. subiendo las 6 rutinas nuevas (si faltan) ===")
for f in RUTINAS:
    b64 = base64.b64encode((ORIG / f).read_bytes()).decode()
    L = [f"rm -f /tmp/r.b64"]
    for i in range(0, len(b64), 2500):
        L.append("echo -n '" + b64[i:i + 2500] + "' >> /tmp/r.b64")
    L.append(f"base64 -d /tmp/r.b64 > '{DEST}/{f}'")
    L.append(f"ls -la '{DEST}/{f}' | awk '{{print $5}}'")
    out = sesion(L, 6)
    ok = "no" if "No such" in out or "error" in out.lower() else "si"
    print(f"   {f}: subida? {ok}")

print("\n=== 3. LAS PRUEBAS (esto es lo que importa) ===")
for etq, cmd in [
    ("%D (fecha)", 'D ^%D'),
    ("fecha directa", 'mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e \'W $$HOY^%D,!\''),
    ("hora directa", 'mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e \'W $$AHORA^%T,!\''),
    ("%UTL banner", 'mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e \'D BANNER^%UTL("PRUEBA"),!\''),
    ("%SS", 'mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e \'D ^%SS\''),
    ("%HELP zonas", 'mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e \'D ^%HELP\''),
]:
    print(f"\n--- {etq}")
    out = sesion([cmd], 12)
    lineas = [x for x in out.split("\n") if x.strip() and cmd not in x and not x.startswith("/ #")]
    for x in lineas[:18]:
        print("     " + x.rstrip())
