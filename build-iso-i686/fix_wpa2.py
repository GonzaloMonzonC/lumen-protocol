#!/usr/bin/env python3
"""copy_wpa: buscar las .so tambien en usr/lib/i386-linux-gnu (Debian las reparte)."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

old = """    n = 0
    for so in WPA_SO:
        p = f"{WPA_LIB}/{so}"
        if os.path.exists(p):
            shutil.copy2(os.path.realpath(p), f"{OUT}/lib/i386-linux-gnu/{so}")
            n += 1"""
new = """    n = 0
    busq = [WPA_LIB, f"{WPA_ROOT}/usr/lib/i386-linux-gnu"]
    for so in WPA_SO:
        p = None
        for d in busq:
            if os.path.exists(f"{d}/{so}"):
                p = f"{d}/{so}"
                break
        if p:
            shutil.copy2(os.path.realpath(p), f"{OUT}/lib/i386-linux-gnu/{so}")
            n += 1
        else:
            print(f"  !! sin {so}")"""
assert old in s, "no encontre el bucle de libs"
s = s.replace(old, new, 1)
open(P, "w", encoding="utf-8", newline="").write(s)
print("PATCH OK")
