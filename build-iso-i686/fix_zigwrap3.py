#!/usr/bin/env python3
"""zig cc añade su crt1.o (musl) y choca con el self-contained de rustc
(duplicate symbol: _start). Se pasa -nostartfiles en modo cc."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/zigwrap.rs"
s = open(P, encoding="utf-8").read()
old = '''        cmd.args(["cc", "-target", if gnu { "x86-linux-gnu" } else { "x86-linux-musl" }, "-mcpu=i686"]);'''
new = '''        // -nostartfiles: el crt1.o lo pone rustc (self-contained). Si zig mete el
        // suyo -> "duplicate symbol: _start".
        cmd.args([
            "cc",
            "-target",
            if gnu { "x86-linux-gnu" } else { "x86-linux-musl" },
            "-mcpu=i686",
            "-nostartfiles",
        ]);'''
assert old in s, "no encontre la linea del cc"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("zigwrap.rs OK: -nostartfiles")
