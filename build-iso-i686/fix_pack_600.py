#!/usr/bin/env python3
"""El modo REAL del cpio lo decide pack_cpio_gz. hub.conf/wifi.conf -> 0600."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''                base = r.rsplit("/", 1)[-1]
                es_loader = base.startswith("ld-") or base.startswith("ld-linux")
                mode = 0o100755 if (r == "init" or r.endswith(".sh")'''
new = '''                base = r.rsplit("/", 1)[-1]
                es_loader = base.startswith("ld-") or base.startswith("ld-linux")
                if r in ("etc/hub.conf", "etc/wifi.conf"):
                    emit(buf, r, 0o100600, open(p, "rb").read(), ino)
                    continue
                mode = 0o100755 if (r == "init" or r.endswith(".sh")'''
assert old in s, "no encontre el bloque de modos"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: packer -> hub.conf / wifi.conf a 0600")
