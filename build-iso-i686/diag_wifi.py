#!/usr/bin/env python3
"""Diagnostico WiFi REAL en el Asus: que dice el driver, hay interfaz, intento wpa?"""
import socket, time

HOST, PORT = "192.168.1.20", 2323


class T:
    def __init__(self, h, p, t=40):
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

    def manda(self, txt, seg=12.0):
        self.s.sendall(txt.encode() + b"\r\n")
        return self.leer(seg)


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


c = T(HOST, PORT)
c.leer(4)
pruebas = [
    ("interfaces de red", "ip -o link show | awk '{print $2, $9}'"),
    ("drivers wifi cargados", "lsmod | grep -iE 'ath9k|iwl|b43|brcm|rtl|rt2|mac80211|cfg80211' | head -8"),
    ("wpa_supplicant corriendo?", "ps | grep -c '[w]pa_supplicant'"),
    ("iwconfig", "iwconfig 2>&1 | head -12"),
    ("wifi.conf existe?", "ls -la /etc/wifi.conf 2>&1"),
    ("wifi.conf: que campos", "sed 's/=.*/=<valor>/' /etc/wifi.conf 2>/dev/null"),
    ("log de wpa", "cat /tmp/wpa.log 2>/dev/null | tail -12 || echo '(no hay /tmp/wpa.log)'"),
    ("que dijo el init del wifi", "grep -a 'wifi' /tmp/nodo.log | head -12"),
    ("dmesg wifi", "dmesg 2>/dev/null | grep -iE 'ath9k|iwl|firmware|wlan' | tail -8"),
]
for etq, cmd in pruebas:
    print(f"\n=== {etq} ===")
    r = limpia(c.manda(cmd, 14))
    for x in r.split("\n"):
        if x.strip() and cmd not in x and not x.startswith("/ #"):
            print("  ", x.rstrip())
c.s.close()
