#!/usr/bin/env python3
"""Fix: en Windows los modos POSIX no existen (st_mode=0o666), asi que el
initramfs salia SIN bit de ejecucion y el kernel no podia correr /init.
Se fija el modo explicitamente por ruta."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = '                mode = 0o100000 | (st.st_mode & 0o777)'
new = ('                exec_paths = ("bin/busybox", "opt/mvm/mvm-nas", "etc/udhcpc.script")\n'
       '                mode = 0o100755 if (r == "init" or r.endswith(".sh")\n'
       '                                    or r in exec_paths) else 0o100644')

if old not in s:
    print("NO encontrado; lineas candidatas:")
    for i, l in enumerate(s.splitlines(), 1):
        if "st_mode" in l or "0o100000" in l:
            print(f"  {i}: {l}")
    raise SystemExit(1)

s = s.replace(old, new)
open(P, "w", encoding="utf-8", newline="").write(s)
print("OK: modo explicito (0755 para init/.sh/busybox/nodo/udhcpc, 0644 resto)")
for i, l in enumerate(open(P, encoding="utf-8").read().splitlines(), 1):
    if "exec_paths" in l or "mode = 0o100755" in l:
        print(f"  {i}: {l}")
