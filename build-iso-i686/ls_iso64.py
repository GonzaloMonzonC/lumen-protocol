#!/usr/bin/env python3
"""Lista el arbol de la ISO x86_64 para localizar el initramfs."""
import pycdlib

ISO = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/lumenos-v0.1.25.iso"
iso = pycdlib.PyCdlib()
iso.open(ISO)

rutas = []
for root, dirs, files in iso.walk(rr_path="/"):
    for f in files:
        rutas.append((root.rstrip("/") + "/" + f).replace("//", "/"))
print(f"ficheros en la ISO: {len(rutas)}")
for r in rutas[:25]:
    print("  ", r)
cand = [r for r in rutas if "initramfs" in r.lower() or r.lower().endswith(".gz")]
print("\ncandidatos initramfs:", cand[:5])
iso.close()
