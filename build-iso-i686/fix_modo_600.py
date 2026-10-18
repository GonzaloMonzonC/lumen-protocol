#!/usr/bin/env python3
"""hub.conf y wifi.conf llevan CREDENCIALES -> deben ir a 0600, no 0644."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''        open(d, "wb").write(data)
        os.chmod(d, 0o755 if (f == "init" or f.endswith(".sh") or f == "udhcpc.script") else 0o644)'''
new = '''        open(d, "wb").write(data)
        # credenciales -> 0600 (hub.conf = clave HMAC del hub, wifi.conf = clave WiFi)
        if f in ("hub.conf", "wifi.conf"):
            modo = 0o600
        else:
            modo = 0o755 if (f == "init" or f.endswith(".sh") or f == "udhcpc.script") else 0o644
        os.chmod(d, modo)'''
assert old in s, "no encontre el chmod del rootfs"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
import py_compile
py_compile.compile(P, doraise=True)
print("PATCH OK: hub.conf / wifi.conf -> 0600")
