#!/usr/bin/env python3
"""Verifica el initramfs con la convencion REAL del kernel:
   data_offset = ALIGN4(110 + namesize);  next = data_offset + ALIGN4(size)
   Imprime nombres y MODOS (octal) de las piezas clave."""
import gzip

P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/initramfs-lumenos-i686.gz"
raw = gzip.decompress(open(P, "rb").read())
print(f"descomprimido: {len(raw)} bytes\n")


def a4(x):
    return (x + 3) & ~3


pos, ents = 0, []
while pos + 110 <= len(raw) and raw[pos:pos+6] == b"070701":
    mode = int(raw[pos+14:pos+22], 16)
    size = int(raw[pos+54:pos+62], 16)
    nsz = int(raw[pos+94:pos+102], 16)
    name = raw[pos+110:pos+110 + nsz - 1].decode("utf-8", "replace")
    d0 = pos + a4(110 + nsz)
    ents.append((name, mode, size))
    pos = d0 + a4(size)
    if name == "TRAILER!!!":
        break

print(f"entradas: {len(ents)}")
print("primeras 12:")
for n, m, s in ents[:12]:
    kind = "DIR " if (m & 0o170000) == 0o040000 else ("LNK " if (m & 0o170000) == 0o120000 else "FILE")
    print(f"  {kind} {oct(m & 0o7777):>7}  {n}  ({s} B)")

names = {e[0]: e for e in ents}
print("\npiezas clave:")
for k in ("init", "bin/busybox", "opt/mvm/mvm-nas", "etc/udhcpc.script",
          "lib/modules/6.1.0-50-686/modules.dep"):
    if k in names:
        m = names[k][1]
        print(f"  OK  {k}  modo={oct(m & 0o7777)}  size={names[k][2]}")
    else:
        print(f"  !!  FALTA {k}")
print(f"\n.ko: {sum(1 for e in ents if e[0].endswith('.ko'))}")
