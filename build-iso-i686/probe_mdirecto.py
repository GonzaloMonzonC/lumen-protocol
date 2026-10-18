#!/usr/bin/env python3
"""Prueba /m (M directo) — la via REAL para gestionar el nodo por telnet."""
import socket, time

IAC, DO, DONT, WILL, WONT = 255, 253, 254, 251, 252


class S:
    def __init__(s, h, p):
        s.s = socket.create_connection((h, p), timeout=10)
        s.s.settimeout(2)
        s.buf = b""

    def leer(s, seg=8):
        t0 = time.time()
        while time.time() - t0 < seg:
            try:
                d = s.s.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            s.buf += d
            i = 0
            while i < len(d):
                if d[i] == IAC and i + 2 < len(d):
                    op, acc = d[i + 1], d[i + 2]
                    if op == DO:
                        s.s.sendall(bytes([IAC, WONT, acc]))
                    elif op == WILL:
                        s.s.sendall(bytes([IAC, DONT, acc]))
                    i += 3
                else:
                    i += 1
        r = s.buf.decode("utf-8", "replace").replace("\r", "")
        s.buf = b""
        return r

    def cmd(s, c, seg=10):
        s.s.sendall(c.encode() + b"\r\n")
        return s.leer(seg)


x = S("127.0.0.1", 2823)
x.leer(8)

print("### /m W \"...\",!  (escribir texto desde M) ###")
print(x.cmd('/m W "HOLA DESDE M DIRECTO",!'))

print("\n### /m D ^SYS(\"NODO\")  (leer el nombre del nodo) ###")
print(x.cmd('/m D ^SYS("NODO")'))

print("\n### /m S ^PRUEBA(1)=\"visto por telnet\"  (ESCRIBIR en la PDB) ###")
print(x.cmd('/m S ^PRUEBA(1)="visto por telnet"'))

print("\n### /m W $G(^PRUEBA(1)),!  (comprobar que se escribio) ###")
print(x.cmd('/m W $G(^PRUEBA(1)),!'))

print("\n### /m D ^%SS  (estado del nodo) ###")
print(x.cmd('/m D ^%SS')[:800])

x.s.close()
