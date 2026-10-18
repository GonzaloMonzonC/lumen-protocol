#!/usr/bin/env python3
"""FIX: quitar el CR de TODOS los ficheros de texto, no solo .conf/.script.
Un '\\r' al final del shebang (#!/bin/busybox sh\\r) hace que busybox busque el
applet 'sh\\r' -> 'sh: applet not found' y telnetd cierra la conexion.
Los binarios (.so, .ko, firmware, keymaps.gz) NO se tocan."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''        if f.endswith(".conf") or f.endswith(".script"):
            data = data.replace(b"\\r\\n", b"\\n")'''
new = '''        if (f == "init" or f.endswith(".sh") or f.endswith(".conf")
                or f.endswith(".script") or f.endswith(".m")
                or f.endswith(".cfg") or f.endswith(".EJEMPLO")):
            # CRLF -> LF: un \\r en el shebang rompe la 1a linea ("sh\\r: applet not found")
            data = data.replace(b"\\r\\n", b"\\n")'''
assert old in s, "no encontre el strip de CR"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: CR fuera de TODO el texto")
