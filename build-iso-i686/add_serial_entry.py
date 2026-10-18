#!/usr/bin/env python3
"""Anade una entrada 'serie' al isolinux.cfg y permite elegir DEFAULT por env
(ISO_SERIAL=1 -> arranca por serie, para verificar la ISO en QEMU sin pantalla)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_iso_i686.py"
s = open(P, encoding="utf-8").read()

# 1) anadir entrada serie al cfg
old_tail = """LABEL sonda
  MENU LABEL LUMEN OS  ·  sonda de diagnostico (automatica)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k lumentest
\"\"\""""
new_tail = """LABEL sonda
  MENU LABEL LUMEN OS  ·  sonda de diagnostico (automatica)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k lumentest

LABEL serie
  MENU LABEL LUMEN OS  ·  consola por SERIE (depuracion)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 console=ttyS0,115200 fbcon=scrollback:512k
\"\"\""""
if old_tail in s:
    s = s.replace(old_tail, new_tail)
    print("  + entrada 'serie' anadida")
else:
    print("  !! no encontre el final del cfg (revisar)")

# 2) DEFAULT y salida por env
s = s.replace(
    'OUT_ISO = f"{B}/lumenos-i686.iso"',
    'import os as _os\n'
    '_SER = _os.environ.get("ISO_SERIAL", "") == "1"\n'
    'OUT_ISO = f"{B}/lumenos-i686-serial.iso" if _SER else f"{B}/lumenos-i686.iso"'
)
s = s.replace('ISOLINUX_CFG = f"""DEFAULT lumenos',
              'ISOLINUX_CFG = f"""DEFAULT {"serie" if _SER else "lumenos"}')
open(P, "w", encoding="utf-8", newline="").write(s)
print("OK: ISO_SERIAL=1 -> DEFAULT=serie y salida lumenos-i686-serial.iso")
