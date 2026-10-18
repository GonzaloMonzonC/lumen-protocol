#!/usr/bin/env python3
"""Asus (.20): 'fail to add interface wlan0' -> de donde sale y que pasa."""
import socket, time

IP = "192.168.1.20"


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
    try:
        s = socket.create_connection((IP, 2323), timeout=25)
        s.settimeout(25)
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
        r = limpia(out)
        return "\n     ".join(x.strip() for x in r.split("\n")
                              if x.strip() and cmd not in x and not x.startswith("/ #"))
    except Exception as e:
        return f"(ERR {e})"


CMDS = [
    ("de donde sale 'add interface'", "grep -rn 'add interface' /tmp/ 2>/dev/null | head -5"),
    ("log del init (wifi)", "tail -25 /tmp/wifi.log 2>/dev/null || echo '(no hay /tmp/wifi.log)'"),
    ("log del nodo (wifi)", "grep -a 'wifi\\|wlan' /tmp/nodo.log 2>/dev/null | tail -12"),
    ("interfaces", "ls /sys/class/net"),
    ("wlan0 existe en /sys?", "cat /sys/class/net/wlan0/operstate 2>&1; basename $(readlink -f /sys/class/net/wlan0/device/driver) 2>&1"),
    ("iwconfig (ya existe)", "iwconfig 2>&1 | head -10"),
    ("wpa_supplicant corriendo?", "ps | grep -c '[w]pa_supplicant'"),
    ("ath9k cargado?", "lsmod | grep -c ath9k"),
    ("dmesg wlan", "dmesg 2>/dev/null | grep -iE 'ath9k|wlan0|firmware|cfg80211' | tail -8"),
    ("que interfaz detecto el init", "grep -a 'interfaz detectada\\|FORZADO\\|asociando' /tmp/nodo.log 2>/dev/null | tail -6"),
    ("prueba directa", "wpa_supplicant -i wlan0 -Dnl80211 -C/tmp/wp 2>&1 | head -6 & sleep 3; kill %1 2>/dev/null"),
]

print(f"===== Asus {IP} =====")
for nombre, cmd in CMDS:
    print(f"\n-- {nombre}")
    print(f"     {sh(cmd)}")
