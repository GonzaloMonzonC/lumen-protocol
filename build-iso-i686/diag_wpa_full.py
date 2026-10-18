#!/usr/bin/env python3
"""Asus: el wpa.log COMPLETO + prueba manual de asociacion (lo decisivo)."""
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


def sh(cmd, seg=14):
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


print("=== 1. EL LOG COMPLETO DE wpa ===")
print("     " + sh("cat /tmp/wpa.log"))
print("\n=== 2. el envoltorio que usa el init ===")
print("     " + sh("ls -la /usr/sbin/wpa_supplicant /bin/wpa_supplicant 2>&1 | head -4"))
print("     " + sh("head -30 /usr/sbin/wpa_supplicant 2>/dev/null | tail -20"))
print("\n=== 3. subir wlan0 a mano ===")
print("     " + sh("ifconfig wlan0 up 2>&1; cat /sys/class/net/wlan0/operstate"))
print("\n=== 4. ver la red (lo que escucha el ath9k) ===")
print("     " + sh("cat /proc/net/wireless"))
print("\n=== 5. PRUEBA MANUAL de wpa_supplicant con log ===")
print("     " + sh("cat > /tmp/t.conf <<'EOF'\nnetwork={\n ssid=\"PRUEBA-LUMEN\"\n psk=\"12345678\"\n}\nEOF\ntimeout 12 wpa_supplicant -i wlan0 -Dnl80211 -c/tmp/t.conf -d 2>&1 | grep -iE 'wlan0|nl80211|fail|error|rfkill|assoc' | head -18", 22))
