#!/usr/bin/env python3
"""Test decisivo: PSK en HEX (elimina el '#' de la ecuacion)."""
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


print("=== 0. estado del arranque limpio ===")
print(sh("echo 'wpa.log del arranque:'; grep -aiE 'add interface|parse|associat|CONNECTED' /tmp/wpa.log | tail -6", 12))

print("\n=== 1. PSK a HEX ===")
print(sh(
    "SSID=GMC; PSK=$(sed -n 's/^[[:space:]]*PSK=//p' /etc/wifi.conf | head -1 | tr -d '\\r'); "
    "HEX=$(wpa_passphrase \"$SSID\" \"$PSK\" 2>/dev/null | sed -n 's/^[[:space:]]*psk=\\([0-9a-f]\\{64\\}\\)$/\\1/p' | head -1); "
    "echo \"longitud del hex: ${#HEX} (64 = bien)\"; "
    "{ echo disassoc_low_ack=0; echo 'bgscan=\"\"'; echo 'network={'; "
    "echo \"  ssid=\\\"$SSID\\\"\"; echo \"  psk=$HEX\"; "
    "echo '  key_mgmt=WPA-PSK'; echo '  proto=RSN'; echo '  pairwise=CCMP'; echo '  group=CCMP'; "
    "echo '  scan_ssid=1'; echo '}'; } > /tmp/hex.conf; "
    "echo '--- hex.conf (sin clave) ---'; sed 's/^  psk=.*/  psk=<hex>/' /tmp/hex.conf", 20))

print("\n=== 2. ASOCIAR con el hex ===")
print(sh(
    "killall wpa_supplicant 2>/dev/null; sleep 1; ifconfig wlan0 up; sleep 1; "
    "wpa_supplicant -B -i wlan0 -Dnl80211 -c/tmp/hex.conf -f/tmp/hex.log 2>&1 | head -2; "
    "sleep 24; echo EVENTOS:; tail -14 /tmp/hex.log; "
    "echo ESTADO:; cat /sys/class/net/wlan0/operstate; ip addr show wlan0 | grep inet", 65))
