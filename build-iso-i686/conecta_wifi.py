#!/usr/bin/env python3
"""Conecta al Asus y prueba la WiFi DE VERDAD con el config corregido.
NO imprime la clave (solo su longitud)."""
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
        r = limpia(out)
        return "\n     ".join(x.strip() for x in r.split("\n")
                              if x.strip() and cmd not in x and not x.startswith("/ #"))
    except Exception as e:
        return f"(ERR {e})"


print("=== 1. ¿qué hay en /etc/wifi.conf? (clave OCULTA) ===")
r = sh("sed 's/^\\(PSK=\\).*/\\1<oculta>/' /etc/wifi.conf 2>/dev/null || echo '(no hay wifi.conf)'", 8)
print("     " + r)

print("\n=== 2. ¿está el nodo en la versión con el arreglo? ===")
print("     " + sh("grep -c 'echo \"  disassoc_low_ack' /init 2>/dev/null; echo '(0 = ya tiene el arreglo)'"))

print("\n=== 3. generando wpa.conf CORREGIDO con tus datos ===")
gen = r"""cd /tmp
SSID=$(sed -n 's/^[[:space:]]*SSID=//p' /etc/wifi.conf | head -1 | tr -d '\r')
PSK=$(sed -n 's/^[[:space:]]*PSK=//p' /etc/wifi.conf | head -1 | tr -d '\r')
OCULTA=$(sed -n 's/^[[:space:]]*OCULTA=//p' /etc/wifi.conf | head -1 | tr -d '\r')
echo "ssid leido (long): ${#SSID} · clave (long): ${#PSK} · oculta: ${OCULTA:-no}"
{
  echo "disassoc_low_ack=0"
  echo 'bgscan=""'
  echo "network={"
  echo "  ssid=\"$SSID\""
  echo "  psk=\"$PSK\""
  echo "  key_mgmt=WPA-PSK"
  echo "  proto=WPA RSN"
  echo "  pairwise=CCMP TKIP"
  echo "  group=CCMP TKIP"
  echo "  scan_ssid=1"
  echo "}"
} > /tmp/ok.conf
echo "--- ok.conf generado (lineas: $(wc -l < /tmp/ok.conf)) ---"
sed 's/^  psk=.*/  psk=<oculta>/' /tmp/ok.conf"""
print("     " + sh(gen, 12))

print("\n=== 4. ASOCIANDO de verdad (esto es lo que nunca se pudo probar) ===")
asoc = (
    "ifconfig wlan0 up 2>/dev/null; "
    "killall wpa_supplicant 2>/dev/null; sleep 1; "
    "wpa_supplicant -B -i wlan0 -Dnl80211 -c/tmp/ok.conf -f/tmp/ok2.log 2>&1 | head -3; "
    "sleep 12; "
    "echo '--- resultado ---'; "
    "grep -iE 'associat|connected|4-way|handshake|CTRL-EVENT|fail|denied|timeout' /tmp/ok2.log | head -14; "
    "echo '--- estado de la interfaz ---'; "
    "cat /sys/class/net/wlan0/operstate; ip addr show wlan0 2>/dev/null | grep -E 'inet |state'"
)
print("     " + sh(asoc, 30))
