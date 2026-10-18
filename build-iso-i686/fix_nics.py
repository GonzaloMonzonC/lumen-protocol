#!/usr/bin/env python3
"""Arregla la RED POR CABLE en portatiles viejos:
   1) anade NICs heredadas a MODS (para que los .ko entren en el initramfs)
   2) el hook de preload tambien las MODPROBEA (el init no las lista)
   3) entrada 'lumenhw' en isolinux para diagnosticar hardware
"""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

# 1) NICs heredadas en MODS
old = "8139too 8139cp sky2 tg3 via-rhine sis900 forcedeth e100 e1000 e1000e r8169 b44"
new = ("8139too 8139cp sky2 tg3 via-rhine sis900 forcedeth e100 e1000 e1000e r8169 b44\n"
       "3c59x pcnet32 tulip ne2k-pci 8390 depca hp100 sundance fealnx ns83820")
assert old in s, "no encontre la linea de NICs de MODS"
s = s.replace(old, new, 1)

# 2) el hook tambien modprobea las NICs heredadas
old2 = '''            "for m in " + " ".join(preload) + "; do modprobe \\"$m\\" 2>/dev/null; done",'''
new2 = ('''            "for m in " + " ".join(preload) + "; do modprobe \\"$m\\" 2>/dev/null; done",
            "# NICs heredadas de portatiles 2003-2007 que el init NO lista",
            "for m in e100 b44 3c59x pcnet32 tulip ne2k-pci 8390 via-rhine sis900 "
            "8139too r8169 forcedeth sky2; do modprobe \\"$m\\" 2>/dev/null; done",''')
assert old2 in s, "no encontre el bucle del preload"
s = s.replace(old2, new2, 1)

open(P, "w", encoding="utf-8", newline="").write(s)

# 3) entrada lumenhw en isolinux.cfg
P2 = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_iso_i686.py"
t = open(P2, encoding="utf-8").read()
oldc = """LABEL serie
  MENU LABEL LUMEN OS  ·  consola por SERIE (depuracion)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 console=ttyS0,115200 fbcon=scrollback:512k
\"\"\""""
newc = """LABEL serie
  MENU LABEL LUMEN OS  ·  consola por SERIE (depuracion)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 console=ttyS0,115200 fbcon=scrollback:512k

LABEL hw
  MENU LABEL LUMEN OS  ·  SONDA DE HARDWARE (drivers/modprobe/firmware)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k lumenhw
\"\"\""""
assert oldc in t, "no encontre el bloque serie del isolinux"
t = t.replace(oldc, newc, 1)
open(P2, "w", encoding="utf-8", newline="").write(t)

import py_compile
py_compile.compile(P, doraise=True)
py_compile.compile(P2, doraise=True)
print("PATCH OK (NICs heredadas + entrada lumenhw) y compilan")
