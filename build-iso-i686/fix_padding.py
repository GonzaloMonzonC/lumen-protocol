#!/usr/bin/env python3
"""Corrige el padding del cpio-newc en build_initramfs_i686.py:
   el kernel alinea (110 + namesize), NO el nombre solo."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '        raw.write(b"\\x00" * ((4 - (len(nm) % 4)) % 4))'
new = ('        _t = 110 + len(nm)\n'
       '        raw.write(b"\\x00" * (((_t + 3) // 4) * 4 - _t))')

if old not in s:
    print("NO encontrado (revisar). Lineas con 'raw.write(b\"\\\\x00\"':")
    for i, l in enumerate(s.splitlines(), 1):
        if "raw.write" in l and "x00" in l:
            print(f"  {i}: {l}")
    raise SystemExit(1)

s = s.replace(old, new)
open(P, "w", encoding="utf-8", newline="").write(s)
print("OK: padding corregido a align4(110 + namesize)")

# verificar
s2 = open(P, encoding="utf-8").read()
for i, l in enumerate(s2.splitlines(), 1):
    if "_t = 110" in l or ("raw.write" in l and "x00" in l):
        print(f"  {i}: {l}")
