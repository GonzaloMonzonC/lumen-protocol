#!/usr/bin/env python3
"""Verifica el initramfs i686 (cpio newc).
Layout kernel initramfs: next = pos + 110 + ALIGN(namelen,4) + ALIGN(size,4)
"""
import gzip

P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/initramfs-lumenos-i686.gz"
raw = gzip.decompress(open(P, "rb").read())
print(f"initramfs descomprimido: {len(raw)} bytes ({len(raw)/1048576:.1f} MB)")


def align4(x):
    return (x + 3) & ~3


pos, ents = 0, []
while pos + 110 <= len(raw) and raw[pos:pos+6] == b"070701":
    mode = int(raw[pos+14:pos+22], 16)
    size = int(raw[pos+54:pos+62], 16)
    nsz = int(raw[pos+94:pos+102], 16)
    name = raw[pos+110:pos+110 + nsz - 1].decode("utf-8", "replace")
    data_off = pos + 110 + align4(nsz)
    data = raw[data_off:data_off + size]
    ents.append((name, mode, data))
    pos = data_off + align4(size)
    if name == "TRAILER!!!":
        break

print(f"entradas cpio: {len(ents)}")
names = {e[0]: e for e in ents}
print(f"modulos .ko: {sum(1 for e in ents if e[0].endswith('.ko'))}")
print(f"rutinas: {sum(1 for e in ents if e[0].startswith('opt/mvm/routines/'))}")
for k in ["init", "bin/busybox", "opt/mvm/mvm-nas", "opt/mvm/mini-pdb.db",
          "lib/modules/6.1.0-50-686/modules.dep",
          "lib/modules/6.1.0-50-686/modules.alias",
          "etc/udhcpc.script"]:
    print(f"  {'OK ' if k in names else '!! '} {k}" + (f"  ({len(names[k][2])} B)" if k in names else ""))


def elfinfo(d):
    if len(d) < 20 or d[:4] != b"\x7fELF":
        return "NO-ELF"
    cls = "32" if d[4] == 1 else "64"
    mach = {3: "i386", 62: "x86_64", 40: "arm", 183: "aarch64"}.get(
        int.from_bytes(d[18:20], "little"), "?")
    return f"ELF{cls} {mach}"


for k in ("bin/busybox", "opt/mvm/mvm-nas"):
    if k in names:
        print(f"  {k}: {elfinfo(names[k][2])}")
