#!/usr/bin/env python3
"""Fix: el ENLAZADOR dinamico (/lib/ld-linux.so.2) debe ser 0755.
Si el interprete de un ELF no es ejecutable, execve devuelve EACCES -> 'Permission
denied' (rc 126) aunque el binario SI tenga +x. Costo un rato encontrarlo."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '''                mode = 0o100755 if (r == "init" or r.endswith(".sh")
                                    or r.startswith("bin/") or r.startswith("sbin/")
                                    or r.startswith("opt/mvm/")
                                    or r == "etc/udhcpc.script") else 0o100644'''
new = '''                base = r.rsplit("/", 1)[-1]
                es_loader = base.startswith("ld-") or base.startswith("ld-linux")
                mode = 0o100755 if (r == "init" or r.endswith(".sh")
                                    or r.startswith("bin/") or r.startswith("sbin/")
                                    or r.startswith("opt/mvm/") or es_loader
                                    or r == "etc/udhcpc.script") else 0o100644'''
if old not in s:
    print("NO encontrado; candidatos:")
    for i, l in enumerate(s.splitlines(), 1):
        if "0o100755" in l or "es_loader" in l:
            print(f"  {i}: {l}")
    raise SystemExit(1)
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("OK: el loader dinamico (ld-*) tambien sera 0755")
