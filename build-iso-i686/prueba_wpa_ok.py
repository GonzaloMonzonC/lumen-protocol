#!/usr/bin/env python3
"""PRUEBA DECISIVA en el Asus: el config corregido (disassoc_low_ack FUERA) ->
wpa_supplicant lo acepta? Se acaba el 'Failed to add interface wlan0'?"""
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


def sh(cmd, seg=16):
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
        return limpia(out)
    except Exception as e:
        return f"(ERR {e})"


# el config CORREGIDO: disassoc_low_ack FUERA del bloque network={}
gen = (
    "cat > /tmp/ok.conf <<'EOF'\n"
    "disassoc_low_ack=0\n"
    "bgscan=\"\"\n"
    "network={\n"
    "  ssid=\"PRUEBA-LUMEN\"\n"
    "  psk=\"12345678\"\n"
    "  key_mgmt=WPA-PSK\n"
    "  proto=WPA RSN\n"
    "  pairwise=CCMP TKIP\n"
    "  group=CCMP TKIP\n"
    "  scan_ssid=1\n"
    "}\n"
    "EOF\n"
    "echo '--- fichero escrito ---'; cat -n /tmp/ok.conf"
)
print("=== EL CONFIG CORREGIDO ===")
print(sh(gen, 8))

print("\n=== wpa_supplicant CON ESTE CONFIG (lo decisivo) ===")
r = sh("timeout 10 wpa_supplicant -i wlan0 -Dnl80211 -c/tmp/ok.conf -f/tmp/ok.log; grep -iE 'failed|successfully|add interface|parse|associating|scan' /tmp/ok.log | head -14", 20)
print(r)

print("\n=== y con el config MALO (para comparar) ===")
r2 = sh("timeout 8 wpa_supplicant -i wlan0 -Dnl80211 -c/tmp/wpa.conf -f/tmp/mal.log; grep -iE 'failed|parse|add interface' /tmp/mal.log | head -6", 18)
print(r2)
