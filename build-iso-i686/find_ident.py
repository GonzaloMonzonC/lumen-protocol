#!/usr/bin/env python3
"""Localiza la identidad del nodo en el seed de la PDB (contexto del string)."""
p = "C:/Users/gonzalo/Documents/GitHub/mvm-nas/deploy/mini-pdb.db"
d = open(p, "rb").read()
for needle in (b"NAS02", b"DS216"):
    i = d.find(needle)
    print(f"--- {needle.decode()} @ offset {i} ---")
    if i >= 0:
        ini = max(0, i - 120)
        trozo = d[ini:i + 80]
        print(repr(trozo))
print("\n--- todas las claves ^... cercanas ---")
import re
claves = set(re.findall(rb"\^[A-Z][A-Z0-9_]{1,20}", d))
for c in sorted(claves):
    print("  ", c.decode())
