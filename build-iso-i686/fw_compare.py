#!/usr/bin/env python3
"""Compara el CONTENIDO de firmware entre la ISO x86_64 del repo (que arranca en
metal con WiFi) y el initramfs i686 nuestro."""
import gzip

def scan(path, label):
    raw = gzip.decompress(open(path, "rb").read())
    def a4(x):
        return (x + 3) & ~3
    pos, fw, kos = 0, 0, 0
    while pos + 110 <= len(raw) and raw[pos:pos+6] == b"070701":
        size = int(raw[pos+54:pos+62], 16)
        nsz = int(raw[pos+94:pos+102], 16)
        nm = raw[pos+110:pos+110 + nsz - 1].decode("utf-8", "replace")
        if "/firmware/" in nm or nm.startswith("lib/firmware"):
            fw += 1
        if nm.endswith(".ko"):
            kos += 1
        pos = pos + a4(110 + nsz) + a4(size)
        if nm == "TRAILER!!!":
            break
    print(f"  {label}")
    print(f"    descomprimido: {len(raw)/1048576:.0f} MB · .ko: {kos} · ficheros de firmware: {fw}")
    return fw

repo = scan("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/initramfs-lumenos.gz",
            "REPO x86_64 (la que se usa en metal)")
mine = scan("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/initramfs-lumenos-i686.gz",
            "NUESTRA i686")
print(f"\n  => el repo lleva {repo} ficheros de firmware; la nuestra {mine}")
