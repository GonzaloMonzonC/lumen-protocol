#!/usr/bin/env python3
"""Sonda la consola M por telnet: que comandos acepta y si hay escape a shell.
OJO: telnet quiere CRLF (\\r\\n), no solo \\n."""
import socket, time

IAC, DO, DONT, WILL, WONT = 255, 253, 254, 251, 252


class Sesion:
    def __init__(self, host, port):
        self.s = socket.create_connection((host, port), timeout=10)
        self.s.settimeout(3)
        self.buf = b""

    def limpiar(self):
        return self.buf.decode("utf-8", "replace").replace("\r", "")

    def leer(self, segundos=7):
        t0 = time.time()
        while time.time() - t0 < segundos:
            try:
                d = self.s.recv(4096)
            except socket.timeout:
                continue
            if not d:
                break
            self.buf += d
            i = 0
            while i < len(d):
                if d[i] == IAC and i + 2 < len(d):
                    op, acc = d[i + 1], d[i + 2]
                    if op == DO:
                        self.s.sendall(bytes([IAC, WONT, acc]))
                    elif op == WILL:
                        self.s.sendall(bytes([IAC, DONT, acc]))
                    i += 3
                else:
                    i += 1
        return self.limpiar()

    def enviar(self, cmd, espera=7):
        self.buf = b""
        self.s.sendall(cmd.encode() + b"\r\n")
        return self.leer(espera)


s = Sesion("127.0.0.1", 2823)
print("### BANNER INICIAL ###")
print(s.leer(10)[-500:])

for cmd in ("/ayuda", "! echo HOLA_SHELL", "! uname -a", "! ls /opt/mvm | head -3",
            "/top 1", "estado"):
    print(f"\n### ENVIO: {cmd} ###")
    print(s.enviar(cmd)[-700:])

s.s.close()
