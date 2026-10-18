#!/usr/bin/env python3
"""zigwrap.rs: filtrar tambien -melf* (rustc lo pasa para i686 y zig cc lo rechaza)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigwrap.rs"
s = open(P, encoding="utf-8").read()
old = '.filter(|a| !a.starts_with("--target=") && a != "-m32" && a != "-m64")'
new = ('.filter(|a| !a.starts_with("--target=") && !a.starts_with("-melf")\n'
       '                && a != "-m32" && a != "-m64")')
assert old in s, "no encontre el filtro"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("zigwrap.rs OK: -melf* filtrado")
