#!/usr/bin/env python3
"""seed-local.m y serve.key tambien llevan SECRETOS -> 0600."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()
old = '''                if r in ("etc/hub.conf", "etc/wifi.conf"):'''
new = '''                if r in ("etc/hub.conf", "etc/wifi.conf",
                         "opt/mvm/seed-local.m", "opt/mvm/serve.key"):'''
assert old in s, "no encontre el bloque de credenciales"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: +seed-local.m/serve.key a 0600")
