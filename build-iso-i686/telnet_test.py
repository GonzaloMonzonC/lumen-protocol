#!/usr/bin/env python3
"""Cliente telnet minimo: conecta, rechaza opciones (IAC) y lee la consola M."""
import socket, time

IAC, DO, DONT, WILL, WONT, SB, SE = 255, 253, 254, 251, 252, 250, 240


def conectar(host, port, cmd=b"\n", espera=12):
    s = socket.create_connection((host, port), timeout=10)
    s.settimeout(2)
    salida = b""
    t0 = time.time()
    enviado = False
    while time.time() - t0 < espera:
        try:
            datos = s.recv(4096)
        except socket.timeout:
            if not enviado and salida:
                s.sendall(cmd)
                enviado = True
            continue
        if not datos:
            break
        salida += datos
        # rechazar cualquier negociacion telnet (evita quedarse colgado)
        i = 0
        while i < len(datos):
            if datos[i] == IAC and i + 2 < len(datos):
                op, acc = datos[i + 1], datos[i + 2]
                if op == DO:
                    s.sendall(bytes([IAC, WONT, acc]))
                elif op == WILL:
                    s.sendall(bytes([IAC, DONT, acc]))
                i += 3
            else:
                i += 1
        if not enviado and b"consola M" in salida:
            time.sleep(1)
            s.sendall(cmd)
            enviado = True
    s.close()
    # limpiar IAC para leer
    limpio = bytearray()
    i = 0
    while i < len(salida):
        if salida[i] == IAC and i + 2 < len(salida):
            i += 3
        else:
            limpio.append(salida[i])
            i += 1
    return limpio.decode("utf-8", "replace")


if __name__ == "__main__":
    txt = conectar("127.0.0.1", 2823, b"/ayuda\n", espera=25)
    print("===== LO QUE DEVUELVE EL NODO POR TELNET =====")
    print(txt[:2500])
    print("===== FIN =====")
