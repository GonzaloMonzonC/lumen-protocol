#!/usr/bin/env python3
"""La ISO x86_64 lleva los cambios? Extrae el initramfs y busca las marcas."""
import gzip, io, os, re

import pycdlib

ISO = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/lumenos-v0.1.25.iso"
iso = pycdlib.PyCdlib()
iso.open(ISO)

# localizar el initramfs dentro de la ISO (recorriendo el arbol)
hallado = None
for root, dirs, files in iso.walk(rr_path="/"):
    for f in files:
        if "initramfs" in f.lower():
            hallado = (root.rstrip("/") + "/" + f).replace("//", "/")
            break
    if hallado:
        break
print("initramfs en la ISO:", hallado)

buf = io.BytesIO()
iso.get_file_from_iso_fp(buf, rr_path=hallado)
raw = buf.getvalue()
print(f"  comprimido: {len(raw)} bytes")

gz = gzip.GzipFile(fileobj=io.BytesIO(raw))
blob = gz.read()
print(f"  descomprimido: {len(blob)} bytes")

marcas = [
    (b"[ddp] nodo configurado para hablar DDP", "config DDP en el init"),
    (b"ddp_peer", "ddp_peer"),
    (b"mem_creada", "rutina %NM (paso 3)"),
    (b"X-DDP-HMAC2", "firma con identidad"),
    (b"%NR", "rutina %NR (paso 1)"),
]
print("\n--- marcas dentro del initramfs ---")
for m, q in marcas:
    print(f"  {q:<32} {'SI' if m in blob else 'NO'}")

# el binario del nodo tambien
idx = blob.find(b"\x7fELF\x02\x01\x01")
print(f"\n  ELF64 presente en el initramfs: {'SI' if idx > 0 else 'no'}")
iso.close()
