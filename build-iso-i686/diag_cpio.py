#!/usr/bin/env python3
"""Deduce la convencion de padding del cpio-newc comparando:
   - el initramfs del repo (que ARRANCA en x86_64)
   - el mio (falla con 'broken padding')"""
import gzip

def probe(path, label, limit=4):
    print(f"\n=== {label} ===")
    raw = gzip.decompress(open(path, "rb").read())
    print(f"descomprimido: {len(raw)} bytes")
    pos, n = 0, 0
    while pos + 110 <= len(raw) and raw[pos:pos+6] == b"070701" and n < limit:
        nsz = int(raw[pos+94:pos+102], 16)
        size = int(raw[pos+54:pos+62], 16)
        name = raw[pos+110:pos+110 + nsz - 1].decode("utf-8", "replace")
        # hipotesis A: se alinea SOLO el nombre
        a = pos + 110 + ((nsz + 3) // 4) * 4
        # hipotesis B: se alinea header+nombre juntos
        b = pos + ((110 + nsz + 3) // 4) * 4
        nxt_a = raw[a:a + 6]
        nxt_b = raw[b:b + 6]
        print(f"  #{n} name={name!r} nsz={nsz} size={size}")
        print(f"      A(name-align) data@{a-pos} -> sig.magic={nxt_a!r} {'OK' if nxt_a==b'070701' else ''}")
        print(f"      B(hdr+name)   data@{b-pos} -> sig.magic={nxt_b!r} {'OK' if nxt_b==b'070701' else ''}")
        pos = b + ((size + 3) // 4) * 4   # seguir con B
        n += 1
    print(f"  ultimos 24 bytes: {raw[-24:]!r}")

probe("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build/initramfs-lumenos.gz",
      "REPO (arranca en x86_64)")
probe("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets/initramfs-lumenos-i686.gz",
      "MIO i686 (falla)")
