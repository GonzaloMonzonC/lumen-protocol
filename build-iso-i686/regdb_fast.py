#!/usr/bin/env python3
"""regdb en UNA conexion + recarga cfg80211 + asociar. Rapido."""
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


s = socket.create_connection((IP, 2323), timeout=120)
s.settimeout(120)
time.sleep(0.5)
s.recv(65536)

buf = bytearray()
lineas = []
lineas.append("killall wpa_supplicant 2>/dev/null; ifconfig wlan0 down 2>/dev/null")
lineas.append("mkdir -p /lib/firmware")
# escribir el regdb con un solo 'echo' por trozo grande
for f in ("regulatory.db", "regulatory.db.p7s"):
    b64 = base64.b64encode((REG / f).read_bytes()).decode()
    lineas.append(f"rm -f /tmp/x.b64")
    for i in range(0, len(b64), 3000):
        lineas.append("echo -n '" + b64[i:i + 3000] + "' >> /tmp/x.b64")
    lineas.append(f"base64 -d /tmp/x.b64 > /lib/firmware/{f}")

lineas += [
    "ls -la /lib/firmware/regulatory.db*",
    "rmmod ath9k; rmmod ath9k_common; rmmod ath9k_hw; rmmod mac80211; rmmod cfg80211",
    "sleep 1",
    "modprobe cfg80211; modprobe mac80211; modprobe ath9k; sleep 2",
    "echo '--- DMESG REGDB ---'; dmesg | grep -iE 'regulatory' | tail -4",
    "ifconfig wlan0 up; sleep 1",
    "wpa_supplicant -B -i wlan0 -Dnl80211 -c/tmp/hex.conf -f/tmp/r2.log 2>&1 | head -2",
    "sleep 20",
    "echo '--- EVENTOS ---'; tail -12 /tmp/r2.log",
    "echo '--- ESTADO ---'; cat /sys/class/net/wlan0/operstate",
    "ip addr show wlan0 | grep inet",
    "echo FIN",
]
s.sendall(("\n".join(lineas) + "\n").encode())

out, fin = b"", time.time() + 190
while time.time() < fin:
    try:
        d = s.recv(32768)
        if not d:
            break
        out += d
        if b"FIN" in out:
            break
    except socket.timeout:
        break
s.close()
r = limpia(out)
print(r[-2600:])
