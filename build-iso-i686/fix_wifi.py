#!/usr/bin/env python3
"""FIX WiFi:
 1) Deteccion de interfaz: hoy SOLO valida /sys/class/net/X/wireless (mac80211).
    Los drivers viejos (ipw2200, hostap, orinoco) NO crean ese dir -> WIFIIF vacio
    -> NUNCA se intenta WiFi (el TravelMate veia 'WIFI: eth0').
    Ahora: wireless O driver conocido O iwconfig dice 802.11.
 2) rfkill unblock antes de intentar (bloqueo de radio = causa clasica).
 3) Rutina %WIFI: volcado de diagnostico completo, lanzable por el telnet.
"""
from pathlib import Path

pi = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs/init")
s = open(pi, encoding="utf-8", newline="").read()

old = '''# ── WiFi si el cable no dio red ──
WIFIIF=""
for i in $(ls /sys/class/net 2>/dev/null | grep -v '^lo$'); do
    [ -d "/sys/class/net/$i/wireless" ] && { WIFIIF="$i"; break; }
done
WDRV=""'''
new = '''# ── WiFi si el cable no dio red ──
# ⚠️⚠️ 02-oct-2026 — LA DETECCION SOLO MIRABA mac80211 ⚠️⚠️
#   Antes: [ -d /sys/class/net/$i/wireless ]
#   Los drivers VIEJOS (ipw2200 del TravelMate, hostap, orinoco) son
#   pre-mac80211 y NO crean /sys/class/net/X/wireless. Resultado medido: el
#   TravelMate decia "WIFI: eth0 (ipw2200)" y WIFIIF quedaba VACIO -> el nodo
#   NO intentaba WiFi nunca, y el sintoma parecia "no funciona el wifi".
#   Ademas wpa_supplicant no puede "attach" a una interfaz que no se le da.
#   Ahora se acepta si: hay dir wireless O el driver es conocido O iwconfig
#   dice 802.11. Se prueban TODAS y se queda la primera que valga.
WIFIIF=""
WDRVCONOCIDO="ath9k ath9k_htc ath5k iwl3945 iwl4965 iwlwifi iwlmvm iwldvm iwlegacy b43 b43legacy brcmsmac brcmfmac bcma ssb rtl8187 rtl8192cu rtl8xxxu rt2800usb rt2800pci rt73usb rt2500usb rt61pci p54pci p54usb mwl8k libertas_usb libertas_cs hostap orinoco orinoco_cs airo airo_cs ipw2100 ipw2200 prism54 zd1211rw rt2400pci rt2500pci carl9170 ar5523 wl"
for i in $(ls /sys/class/net 2>/dev/null | grep -v '^lo$'); do
    _drv=$(basename "$(readlink -f "/sys/class/net/$i/device/driver" 2>/dev/null)" 2>/dev/null)
    _es="no"
    [ -d "/sys/class/net/$i/wireless" ] && _es="si"
    for _d in $WDRVCONOCIDO; do
        [ "$_drv" = "$_d" ] && _es="si"
    done
    if [ "$_es" != "si" ] && command -v iwconfig >/dev/null 2>&1; then
        iwconfig "$i" 2>/dev/null | grep -q "802\\.11" && _es="si"
    fi
    if [ "$_es" = "si" ]; then
        WIFIIF="$i"
        WDRV="$_drv"
        echo "[wifi] interfaz detectada: $i (driver ${_drv:-?})"
        break
    fi
done
# desbloquear la radio: si rfkill deja la wifi 'blocked' nada asocia y no se ve por que
if command -v rfkill >/dev/null 2>&1; then
    rfkill unblock all 2>/dev/null && echo "[wifi] rfkill: radio desbloqueada"
fi
WDRV=""'''
assert old in s, "no encontre el bloque de deteccion wifi"
s = s.replace(old, new, 1)
open(pi, "w", encoding="utf-8", newline="").write(s)
print("init OK: deteccion ampliada + rfkill")

# ── rutina %WIFI: diagnostico completo, lanzable por telnet ──
WIFI = r'''%WIFI ; %WIFI - DIAGNOSTICO de WiFi (lanzar por telnet: D ^%WIFI)
 ; Volca TODO lo que hace falta para saber por que no asocia, y prueba un
 ; escaneo. No cambia nada: solo informa. Lanzable desde el shell por Ethernet:
 ;     /opt/mvm/mvm-nas -p /tmp/pdb.db -r /opt/mvm/routines -e 'D ^%WIFI'
 W "===== %WIFI - diagnostico =====",!
 W "^CAPACIDAD(""wifi"") = ",$G(^CAPACIDAD("wifi")),"   red=",$G(^CAPACIDAD("red")),!
 W "^CAPACIDAD(""hub"")  = ",$G(^CAPACIDAD("hub")),"   ddp_clave=",$G(^CAPACIDAD("ddp_clave")),!
 W "NODO = ",$G(^SYS("NODO")),!
 W "-- config WiFi (^CONFIG) --",!
 W "  wifi_ssid  = ",$G(^CONFIG("wifi_ssid")),!
 W "  wifi_oculta= ",$G(^CONFIG("wifi_oculta")),!
 W "  wifi_drv   = ",$G(^CONFIG("wifi_drv")),!
 W "  llm_url    = ",$G(^CONFIG("llm_url_openrouter")),!
 W "  ddp_peer   = ",$G(^CONFIG("ddp_peer")),!
 W "-- DDP: el hub responde? --",!
 I $G(^CONFIG("ddp_peer"))="" W "  (sin hub configurado)",!
 I $G(^CONFIG("ddp_peer"))'="" W "  ",$E($DEVICE("ddp:health"),1,120),!
 W "",!
 W "Para ver el SISTEMA (driver, firmware, rfkill, escaneo) usa el shell :2323:",!
 W "  iwconfig",!
 W "  dmesg | grep -iE 'wifi|wlan|firmware|ath|iwl|b43|ipw'",!
 W "  cat /tmp/wifi.log   (lo que hizo el init)",!
 W "  rfkill list",!
 W "  iwlist wlan0 scan | head -40",!
 Q
'''
Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/routines/%WIFI.m").write_text(
    WIFI.replace("\n", "\r\n"), encoding="utf-8", newline="")
print("deploy/routines/%WIFI.m escrita")
