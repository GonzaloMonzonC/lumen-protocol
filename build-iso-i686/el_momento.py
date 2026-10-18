#!/usr/bin/env python3
"""Con el regdb YA cargado: generar hex.conf y asociar. El momento de la verdad."""
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


s = socket.create_connection((IP, 2323), timeout=120)
s.settimeout(120)
time.sleep(0.5)
s.recv(65536)

lineas = [
    "SSID=GMC",
    "PSK=$(sed -n 's/^[[:space:]]*PSK=//p' /etc/wifi.conf | head -1 | tr -d '\\r')",
    "HEX=$(wpa_passphrase \"$SSID\" \"$PSK\" | sed -n 's/^[[:space:]]*psk=\\([0-9a-f]\\{64\\}\\)$/\\1/p' | head -1)",
    "echo \"hex=${#HEX}\"",
    "{ echo disassoc_low_ack=0; echo 'bgscan=\"\"'; echo 'network={'; "
    "echo \"  ssid=\\\"$SSID\\\"\"; echo \"  psk=$HEX\"; echo '  key_mgmt=WPA-PSK'; "
    "echo '  proto=RSN'; echo '  pairwise=CCMP'; echo '  group=CCMP'; "
    "echo '  scan_ssid=1'; echo '}'; } > /tmp/hex.conf",
    "ls -la /tmp/hex.conf",
    "killall wpa_supplicant 2>/dev/null; sleep 1; ifconfig wlan0 up; sleep 1",
    "wpa_supplicant -B -i wlan0 -Dnl80211 -c/tmp/hex.conf -f/tmp/final2.log 2>&1 | head -2",
    "sleep 22",
    "echo '=== EVENTOS ==='; tail -16 /tmp/final2.log",
    "echo '=== ESTADO ==='; cat /sys/class/net/wlan0/operstate",
    "ip addr show wlan0 | grep inet",
    "echo FIN",
]
s.sendall(("\n".join(lineas) + "\n").encode())
out, fin = b"", time.time() + 120
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
print(limpia(out)[-2200:])
