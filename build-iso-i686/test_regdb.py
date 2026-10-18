#!/usr/bin/env python3
"""Test decisivo SIN regrabar: copiar regulatory.db al Asus y recargar cfg80211."""
import base64, socket, time
from pathlib import Path

IP = "192.168.1.20"
REG = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/extra-bin")


def limpia(b):
    out, i = bytearray(), 0
    while i < len(b):
        if b[i] == 0xFF and i + 2 < len(b):
            i += 3
        else:
            out.append(b[i])
            i += 1
    return bytes(out).decode("utf-8", "replace").replace("\r", "")


def sh(cmd, seg=20):
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


print("=== 1. copiando regulatory.db al nodo ===")
b64 = base64.b64encode((REG / "regulatory.db").read_bytes()).decode()
b64s = base64.b64encode((REG / "regulatory.db.p7s").read_bytes()).decode()
sh("rm -f /tmp/r.b64 /tmp/r.p7s.b64; mkdir -p /lib/firmware", 5)
for i in range(0, len(b64), 700):
    sh("echo -n '" + b64[i:i + 700] + "' >> /tmp/r.b64", 3)
for i in range(0, len(b64s), 700):
    sh("echo -n '" + b64s[i:i + 700] + "' >> /tmp/r.p7s.b64", 3)
print(sh(
    "base64 -d /tmp/r.b64 > /lib/firmware/regulatory.db; "
    "base64 -d /tmp/r.p7s.b64 > /lib/firmware/regulatory.db.p7s; "
    "ls -la /lib/firmware/regulatory.db* ", 8))

print("\n=== 2. recargando cfg80211 (para que lea el regdb) ===")
print(sh(
    "killall wpa_supplicant 2>/dev/null; ifconfig wlan0 down 2>/dev/null; sleep 1; "
    "rmmod ath9k 2>&1; rmmod ath9k_common 2>&1; rmmod ath9k_hw 2>&1; "
    "rmmod mac80211 2>&1; rmmod cfg80211 2>&1; sleep 1; "
    "modprobe cfg80211 2>&1; modprobe mac80211 2>&1; modprobe ath9k 2>&1; sleep 2; "
    "echo '--- dmesg: cargo el regdb? ---'; "
    "dmesg | grep -iE 'regulatory|cfg80211' | tail -6", 40))

print("\n=== 3. ASOCIAR otra vez ===")
print(sh(
    "ifconfig wlan0 up; sleep 1; "
    "wpa_supplicant -B -i wlan0 -Dnl80211 -c/tmp/hex.conf -f/tmp/r2.log 2>&1 | head -2; "
    "sleep 24; echo EVENTOS:; tail -12 /tmp/r2.log; "
    "echo ESTADO:; cat /sys/class/net/wlan0/operstate; ip addr show wlan0 | grep inet", 60))
