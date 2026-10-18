#!/usr/bin/env python3
"""rustc pasa -Wl,-melf_i386: hay que filtrar por CONTIENE 'melf', no por empieza."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigwrap.rs"
s = open(P, encoding="utf-8").read()
old = '!a.starts_with("-melf")'
new = '!a.contains("melf")'
assert old in s, "no encontre el filtro"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("zigwrap.rs OK: filtro por 'contiene melf'")
