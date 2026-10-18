#!/usr/bin/env python3
"""Prueba -Dwext con ath9k (limpio, sin comillas raras)."""
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


def sh(cmd, seg=55):
    s = socket.create_connection((IP, 2323), timeout=90)
    s.settimeout(90)
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
    return limpia(out)


cmd = (
    "killall wpa_supplicant 2>/dev/null; sleep 1; ifconfig wlan0 up; sleep 1; "
    "wpa_supplicant -B -i wlan0 -Dwext -c/tmp/ok.conf -f/tmp/wx.log 2>&1 | head -2; "
    "sleep 25; echo EVENTOS:; tail -18 /tmp/wx.log; "
    "echo ESTADO:; cat /sys/class/net/wlan0/operstate; ip addr show wlan0 | grep inet"
)
print(sh(cmd, 70))
