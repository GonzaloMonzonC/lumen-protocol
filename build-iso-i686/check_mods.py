#!/usr/bin/env python3
"""Comprueba si los modulos base entraron y como quedo modules.dep."""
import gzip

P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/initramfs-lumenos-i686.gz"
raw = gzip.decompress(open(P, "rb").read())


def a4(x):
    return (x + 3) & ~3


pos, ents = 0, {}
while pos + 110 <= len(raw) and raw[pos:pos+6] == b"070701":
    size = int(raw[pos+54:pos+62], 16)
    nsz = int(raw[pos+94:pos+102], 16)
    name = raw[pos+110:pos+110 + nsz - 1].decode("utf-8", "replace")
    d0 = pos + a4(110 + nsz)
    ents[name] = raw[d0:d0 + size]
    pos = d0 + a4(size)
    if name == "TRAILER!!!":
        break

print("modulos clave presentes?")
for m in ("usbcore", "usb-common", "ehci-hcd", "ehci-pci", "hid", "libata", "scsi_mod"):
    hits = [k for k in ents if k.endswith(f"/{m}.ko") or k == f"{m}.ko"]
    print(f"  {m:<12} {'SI -> ' + hits[0] if hits else 'NO'}")
print(f"\ntotal .ko en el initramfs: {sum(1 for k in ents if k.endswith('.ko'))}")

dep = ents.get("lib/modules/6.1.0-50-686/modules.dep", b"").decode("utf-8", "replace")
print(f"\nmodules.dep: {len(dep.splitlines())} lineas")
print("primeras 3 lineas:")
for l in dep.splitlines()[:3]:
    print("   ", l[:130])
print("\nlineas de ehci / usbcore:")
for l in dep.splitlines():
    if "ehci" in l or "usbcore" in l:
        print("   ", l[:150])
