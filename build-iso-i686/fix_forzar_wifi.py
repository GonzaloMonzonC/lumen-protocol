#!/usr/bin/env python3
"""PUNTO 2: poder FORZAR la prueba de WiFi aunque el cable ya haya dado red.

Hoy:  if [ -z "$NETIF" ] && [ -x /bin/wpa_supplicant ]; then   ... intenta WiFi
=> con cable, NETIF esta puesto y la WiFi NO se intenta NUNCA. Medido en el
   Asus: radio perfecta (soft=0 hard=0), wlan0+ath9k OK, y cero intentos.
Ahora: se puede forzar con  FORZAR=si  en /etc/wifi.conf  o con  lumenwifi
   en la linea de comandos del kernel (util para probar sin tocar ficheros).
"""
from pathlib import Path

pi = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/init")
s = open(pi, encoding="utf-8", newline="").read()

old = '''    if [ -z "$NETIF" ] && [ -x /bin/wpa_supplicant ]; then'''
new = '''    # ⚠️ 02-oct-2026: con cable NO se probaba la WiFi nunca. Para poder probarla
    # (el Asus tiene la radio perfecta y no se intentaba) se añade un FORZADO:
    #   FORZAR=si en /etc/wifi.conf   ·   o   lumenwifi en el cmdline del kernel
    FORZARWIFI="no"
    [ -f /etc/wifi.conf ] && grep -qi '^[[:space:]]*FORZAR=si' /etc/wifi.conf && FORZARWIFI="si"
    grep -q lumenwifi /proc/cmdline 2>/dev/null && FORZARWIFI="si"
    if [ "$FORZARWIFI" = "si" ]; then
        echo "[wifi] FORZADO: se prueba la WiFi aunque haya cable"
    fi
    if { [ -z "$NETIF" ] || [ "$FORZARWIFI" = "si" ]; } && [ -x /bin/wpa_supplicant ]; then'''
assert old in s, "no encontre la condicion del wifi"
s = s.replace(old, new, 1)
open(pi, "w", encoding="utf-8", newline="").write(s)
print("init OK: WiFi forzable (FORZAR=si o lumenwifi)")

# documentar en el ejemplo de wifi.conf
pe = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/wifi.conf.EJEMPLO")
if pe.exists():
    t = open(pe, encoding="utf-8", newline="").read()
    if "FORZAR" not in t:
        t = t.rstrip() + "\n\n# Forzar la prueba de WiFi aunque el cable ya de red (util para\n# diagnosticar; tambien vale 'lumenwifi' en el cmdline del kernel).\n# FORZAR=si\n"
        open(pe, "w", encoding="utf-8", newline="").write(t)
        print("wifi.conf.EJEMPLO documentado")
