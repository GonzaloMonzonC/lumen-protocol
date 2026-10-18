#!/usr/bin/env python3
"""Fix: en el cpio, TODO fichero de /bin y /sbin debe ser 0755.
Antes solo se marcaban init/.sh/3 rutas -> wpa_supplicant salia 0644 y daba rc=126."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''                exec_paths = ("bin/busybox", "opt/mvm/mvm-nas", "etc/udhcpc.script")
                mode = 0o100755 if (r == "init" or r.endswith(".sh")
                                    or r in exec_paths) else 0o100644'''
new = '''                mode = 0o100755 if (r == "init" or r.endswith(".sh")
                                    or r.startswith("bin/") or r.startswith("sbin/")
                                    or r.startswith("opt/mvm/")
                                    or r == "etc/udhcpc.script") else 0o100644'''
if old not in s:
    print("NO encontrado; candidatos:")
    for i, l in enumerate(s.splitlines(), 1):
        if "0o100755" in l or "exec_paths" in l:
            print(f"  {i}: {l}")
    raise SystemExit(1)
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("OK: /bin/*, /sbin/*, /opt/mvm/* -> 0755")
