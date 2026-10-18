#!/usr/bin/env python3
"""Diagnostico: el reenvio de puerto llega al telnetd del invitado?"""
import socket, time

print("1) TCP a 127.0.0.1:2323 ...")
try:
    s = socket.create_connection(("127.0.0.1", 2323), timeout=8)
    print("   CONECTADO")
    s.settimeout(6)
    # leer lo que mande el telnetd (negociacion IAC)
    try:
        d = s.recv(512)
        print(f"   recv {len(d)} bytes: {d[:80]!r}")
    except socket.timeout:
        print("   (no manda nada al conectar)")
    # probar a enviar un comando tras la negociacion
    time.sleep(1)
    s.sendall(b"\n")
    time.sleep(3)
    try:
        d2 = s.recv(2048)
        print(f"   tras ENTER: {len(d2)} bytes: {d2[:300]!r}")
    except socket.timeout:
        print("   tras ENTER: (nada)")
    s.close()
except Exception as e:
    print(f"   FALLO: {type(e).__name__}: {e}")

print("\n2) el puerto 23 del invitado esta reenviado? (hostfwd 2323->23)")
print("   (si el paso 1 fallo, el problema es el reenvio o que telnetd no escucha)")
