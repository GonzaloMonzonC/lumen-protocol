#!/usr/bin/env python3
"""1) copia wpa_passphrase (el init lo usa para el PSK en hex)
   2) envoltorio /bin/wpa_supplicant: fuerza -D wext SOLO en chipsets viejos
      (ipw2200 no habla nl80211). El ELF real va a /usr/sbin/wpa_supplicant
      para que 'pidof wpa_supplicant' siga funcionando (mismo basename)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''    # wpa_cli comparte las mismas libs
    if os.path.isfile(cli):
        shutil.copy2(cli, f"{OUT}/bin/wpa_cli")'''
new = '''    # wpa_cli comparte las mismas libs
    if os.path.isfile(cli):
        shutil.copy2(cli, f"{OUT}/bin/wpa_cli")
    # wpa_passphrase: el init lo usa para convertir la clave a PSK hex
    wp = f"{WPA_ROOT}/usr/bin/wpa_passphrase"
    if os.path.isfile(wp):
        shutil.copy2(wp, f"{OUT}/bin/wpa_passphrase")
    # --- Envoltorio para chipsets VIEJOS ---------------------------------
    # ipw2200 (TravelMate) es PRE-mac80211: no habla nl80211. El binario prueba
    # "nl80211,wext" y si el fallback no ocurre, no asocia NUNCA.
    # El ELF real va a /usr/sbin/ (mismo basename -> pidof sigue funcionando).
    os.makedirs(f"{OUT}/usr/sbin", exist_ok=True)
    shutil.move(f"{OUT}/bin/wpa_supplicant", f"{OUT}/usr/sbin/wpa_supplicant")
    envoltorio = """#!/bin/busybox sh
# LUMEN i686: fuerza -D wext en chipsets PRE-mac80211 (no soportan nl80211).
REAL=/usr/sbin/wpa_supplicant
IF=""; PREV=""
for a in "$@"; do
    [ "$PREV" = "-i" ] && IF="$a"
    PREV="$a"
done
EXTRA=""
if [ -n "$IF" ]; then
    DRV=$(basename "$(readlink -f /sys/class/net/$IF/device/driver 2>/dev/null)" 2>/dev/null)
    case "$DRV" in
        ipw2200|ipw2100|hostap|orinoco|airo|atmel|zd1201|prism54|wavelan)
            EXTRA="-D wext" ;;
    esac
    echo "[wifi]   envoltorio: driver='$DRV' -> ${EXTRA:-nl80211,wext (por defecto)}"
fi
exec "$REAL" $EXTRA "$@"
"""
    with open(f"{OUT}/bin/wpa_supplicant", "w", newline="\\n") as f:
        f.write(envoltorio)'''
assert old in s, "no encontre el bloque de wpa_cli"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK y compila")
