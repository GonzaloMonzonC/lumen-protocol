#!/usr/bin/env python3
"""Comprueba el shebang de telnet-m.sh (posible CR que rompe la 1a linea)."""
B = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686"
R = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/rootfs"
CR = b"\r"

for etiqueta, p in (
    ("repo     ", R + "/telnet-m.sh"),
    ("initramfs", B + "/initramfs-i686/etc/telnet-m.sh"),
):
    d = open(p, "rb").read(60)
    tiene = b"\r" in d
    print(etiqueta + ": " + repr(d))
    print("            tiene CR: " + ("SI  <-- ROMPE EL SHEBANG" if tiene else "no"))
