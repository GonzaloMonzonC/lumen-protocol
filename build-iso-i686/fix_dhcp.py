#!/usr/bin/env python3
"""2b: DHCP en wlan0. La WiFi asocia pero se queda sin IPv4 (solo link-local).
Hay que pedir IP con udhcpc despues de que wpa_supplicant asocie."""
import re
from pathlib import Path

pi = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/init")
s = open(pi, encoding="utf-8", newline="").read()

if "udhcpc -i \"$WIFIIF\"" in s:
    print("(ya estaba)")
    raise SystemExit(0)

# buscar la invocacion de wpa_supplicant en el init
lineas = s.split("\n")
idx = None
for i, l in enumerate(lineas):
    if "wpa_supplicant" in l and ("-i" in l or "-B" in l) and not l.strip().startswith("#"):
        idx = i
print("wpa_supplicant en la linea", idx)
if idx is None:
    for i, l in enumerate(lineas):
        if "wpa_supplicant" in l and not l.strip().startswith("#"):
            print("   (candidata)", i, l.strip()[:90])
    raise SystemExit("no encontre el arranque de wpa_supplicant")

# el bloque de DHCP, con sangria parecida a la de esa linea
sang = re.match(r"^(\s*)", lineas[idx]).group(1)
BLOQUE = f'''
{sang}# ⚠️ 03-oct-2026: la WiFi ASOCIABA pero se quedaba SIN IP (solo link-local).
{sang}# wpa_supplicant no pide direccion: hay que pedirla aparte, y DESPUES de
{sang}# que asocie. Medido en el Asus: "operstate: up" e "inet6 fe80::..." pero
{sang}# ningun "inet 192.168.x.x" -> el nodo era inalcanzable por WiFi.
{sang}if command -v udhcpc >/dev/null 2>&1; then
{sang}    _w=0
{sang}    while [ "$_w" -lt 15 ]; do
{sang}        if grep -q 'CTRL-EVENT-CONNECTED' /tmp/wpa.log 2>/dev/null; then
{sang}            break
{sang}        fi
{sang}        _w=$((_w+1)); sleep 1
{sang}    done
{sang}    echo "[wifi] asociado en ${{_w}}s -> pidiendo IP por DHCP (udhcpc)"
{sang}    udhcpc -i "$WIFIIF" -q -n -t 6 -T 3 >/tmp/udhcpc.log 2>&1
{sang}    _ip=$(ip -4 addr show "$WIFIIF" 2>/dev/null | sed -n 's/.*inet \\([0-9.]*\\).*/\\1/p' | head -1)
{sang}    if [ -n "$_ip" ]; then
{sang}        echo "[wifi] IP obtenida: $_ip"
{sang}        S_IP="$_ip"
{sang}    else
{sang}        echo "[wifi] AVISO: el DHCP no dio IP (ver /tmp/udhcpc.log)"
{sang}    fi
{sang}fi'''

lineas.insert(idx + 1, BLOQUE)
open(pi, "w", encoding="utf-8", newline="").write("\n".join(lineas))
print("init OK: DHCP tras la asociacion")

# comprobar que el init sigue siendo shell valido
import subprocess
r = subprocess.run(["bash", "-n", str(pi)], capture_output=True, text=True)
print("sintaxis del init:", "OK" if r.returncode == 0 else f"ERROR: {r.stderr[:200]}")
