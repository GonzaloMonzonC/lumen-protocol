#!/usr/bin/env python3
"""zigwrap: variante x86_64 (*x64* o *x86_64* en el nombre) -> -target x86_64-linux-*
y NO aplicar -mcpu=i686 en 64 bits."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigwrap.rs"
s = open(P, encoding="utf-8", newline="").read()

old_det = '''    let is_ranlib = name.contains("ranlib");'''
new_det = '''    let es64 = name.contains("x64") || name.contains("x86_64");
    let is_ranlib = name.contains("ranlib");'''
assert old_det in s
s = s.replace(old_det, new_det, 1)

old_cc = '''        cmd.args([
            "cc",
            "-target",
            if gnu { "x86-linux-gnu" } else { "x86-linux-musl" },
            "-mcpu=i686",
            "-nostartfiles",
        ]);'''
new_cc = '''        let target = if es64 {
            if gnu { "x86_64-linux-gnu" } else { "x86_64-linux-musl" }
        } else if gnu {
            "x86-linux-gnu"
        } else {
            "x86-linux-musl"
        };
        cmd.args(["cc", "-target", target, "-nostartfiles"]);
        if !es64 {
            cmd.arg("-mcpu=i686");
        }'''
assert old_cc in s, "no encontre el bloque cc"
s = s.replace(old_cc, new_cc, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
print("zigwrap.rs OK: variante x86_64")
