#!/usr/bin/env python3
"""Extrae /etc/keymaps/*.map.gz del initramfs x86_64 ya construido.
Los mapas son TEXTO -> independientes de arquitectura (sirven para i686)."""
import gzip, os

SRC = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/initramfs-lumenos.gz"
DST = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/keymaps"
os.makedirs(DST, exist_ok=True)

QUIERO = {f"etc/keymaps/{k}.map.gz" for k in ("es", "uk", "de", "fr", "it", "pt")}
encontrados = {}

f = gzip.open(SRC, "rb")
while True:
    hdr = f.read(110)
    if len(hdr) < 110:
        break
    if hdr[:6] not in (b"070701", b"070702"):
        break
    namesize = int(hdr[94:102], 16)
    filesize = int(hdr[54:62], 16)  # offset 54-62 (102-110 es el checksum)
    nombre = f.read(namesize).rstrip(b"\x00").decode("utf-8", "replace")
    # alinear: (110 + namesize) a multiplo de 4
    pad = (-(110 + namesize)) % 4
    if pad:
        f.read(pad)
    if nombre == "TRAILER!!!":
        break
    datos = f.read(filesize)
    f.read((-filesize) % 4)
    if nombre in QUIERO:
        with open(f"{DST}/{os.path.basename(nombre)}", "wb") as o:
            o.write(datos)
        encontrados[nombre] = len(datos)
f.close()

print("extraidos:")
for k, v in sorted(encontrados.items()):
    print(f"  {os.path.basename(k):<14} {v} bytes")
faltan = QUIERO - set(encontrados)
if faltan:
    print("FALTAN:", sorted(faltan))
