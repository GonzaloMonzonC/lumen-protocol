#!/usr/bin/env python3
"""Prueba los DOS puertos: consola M (gestionar) y shell (diagnosticar)."""
import socket, time

IAC, DO, DONT, WILL, WONT = 255, 253, 254, 251, 252


class S:
    def __init__(s, h, p):
        s.s = socket.create_connection((h, p), timeout=10)
        s.s.settimeout(2)
        s.buf = b""

    def leer(s, seg=6):
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

    def cmd(s, c, seg=8):
        s.s.sendall(c.encode() + b"\r\n")
        return s.leer(seg)


print("========== PUERTO 2923 -> CONSOLA M (gestionar) ==========")
try:
    a = S("127.0.0.1", 2923)
    a.leer(8)
    print("--- /m D ^%SS (estado) ---")
    print(a.cmd('/m D ^%SS')[:700])
    a.s.close()
except Exception as e:
    print("FALLO:", type(e).__name__, e)

print("\n========== PUERTO 2924 -> SHELL DEL SISTEMA (diagnosticar) ==========")
try:
    b = S("127.0.0.1", 2924)
    b.leer(8)
    for c in ("uname -a", "cat /proc/cpuinfo | grep -m1 'model name'",
              "ls /tmp/ | head -8", "dmesg | grep -i ipw2200 | head -2 || echo '(sin ipw2200 en este QEMU)'"):
        print(f"--- $ {c}")
        print(b.cmd(c)[-500:])
    b.s.close()
except Exception as e:
    print("FALLO:", type(e).__name__, e)
