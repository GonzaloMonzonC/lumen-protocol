#!/usr/bin/env python3
"""Comprueba en el Asus: la WiFi del INIT (sin tocar nada) tiene IP?"""
import socket, time

IP = "192.168.1.23"


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def sh(cmd, seg=10):
    s = socket.create_connection((IP, 2323), timeout=40)
    s.settimeout(40)
    time.sleep(0.4)
    s.recv(65536)
    s.sendall(cmd.encode() + b"\r\n")
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
    return "\n     ".join(x.strip() for x in limpia(out).split("\n")
                          if x.strip() and cmd not in x and not x.startswith("/ #"))


for etq, c in [
    ("interfaces y estado", "cat /sys/class/net/wlan0/operstate; ls /sys/class/net"),
    ("IP de wlan0 (lo que buscamos)", "ip -4 addr show wlan0 2>&1 | head -6"),
    ("wpa_supplicant corriendo?", "ps | grep -c '[w]pa_supplicant'"),
    ("que dijo udhcpc", "cat /tmp/uw.log 2>/dev/null | tail -8 || echo '(no hay /tmp/uw.log)'"),
    ("que dijo el init del wifi", "grep -a 'wifi' /tmp/nodo.log 2>/dev/null | tail -12"),
    ("la ruta por defecto", "ip route 2>&1 | head -4"),
    ("alcanza el hub por wifi?", "ping -c 2 -W 3 192.168.1.10 2>&1 | tail -3"),
]:
    print(f"--- {etq}")
    print("     " + sh(c))
