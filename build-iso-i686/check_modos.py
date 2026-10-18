#!/usr/bin/env python3
"""Comprueba el MODO REAL en el cpio de las credenciales."""
import gzip

f = gzip.open("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/initramfs-lumenos-i686.gz", "rb")
objetivo = {"etc/wifi.conf", "etc/nodo.conf", "etc/teclado.conf", "etc/hub.conf",
            "bin/loadkeys", "bin/wpa_supplicant", "usr/sbin/wpa_supplicant", "opt/mvm/seed-local.m"}
while True:
    h = f.read(110)
    if len(h) < 110 or h[:6] not in (b"070701", b"070702"):
        break
    mode = int(h[14:22], 16)
    namesize = int(h[94:102], 16)
    filesize = int(h[54:62], 16)
    nombre = f.read(namesize).rstrip(b"\x00").decode("utf-8", "replace")
    f.read((-(110 + namesize)) % 4)
    if nombre in objetivo:
        print(f"  {oct(mode)[2:]:>7}  {nombre}")
    f.read(filesize)
    f.read((-filesize) % 4)
    if nombre == "TRAILER!!!":
        break
f.close()
