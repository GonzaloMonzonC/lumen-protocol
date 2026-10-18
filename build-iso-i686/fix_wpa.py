#!/usr/bin/env python3
"""Anade wpa_supplicant (i386, glibc) + sus librerias al initramfs."""
P = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py"
s = open(P, encoding="utf-8").read()

anchor = "def copy_firmware():"
new = '''WPA_ROOT = f"{B}/assets/wpa-root"
WPA_LIB = f"{WPA_ROOT}/lib/i386-linux-gnu"
# sonames que pide wpa_supplicant (leidos del ELF) + NSS
WPA_SO = ["libc.so.6", "libm.so.6", "libcrypto.so.3", "libssl.so.3",
          "libdbus-1.so.3", "libnl-3.so.200", "libnl-genl-3.so.200",
          "libnl-route-3.so.200", "libpcsclite.so.1",
          "libnss_dns.so.2", "libnss_files.so.2", "libresolv.so.2"]


def copy_wpa():
    """wpa_supplicant es glibc (dinamico): hay que llevar el binario + el
    enlazador (/lib/ld-linux.so.2, lo que dice PT_INTERP) + sus .so.
    Sin esto, el WiFi solo vale para redes abiertas."""
    src = f"{WPA_ROOT}/sbin/wpa_supplicant"
    if not os.path.isfile(src):
        print("  !! wpa_supplicant no encontrado (¿get_wpa.py?)")
        return
    os.makedirs(f"{OUT}/lib/i386-linux-gnu", exist_ok=True)
    shutil.copy2(src, f"{OUT}/bin/wpa_supplicant")
    ld = f"{WPA_LIB}/ld-linux.so.2"
    if os.path.exists(ld):
        real = os.path.realpath(ld)
        shutil.copy2(real, f"{OUT}/lib/ld-linux.so.2")
        shutil.copy2(real, f"{OUT}/lib/i386-linux-gnu/ld-linux.so.2")
    n = 0
    for so in WPA_SO:
        p = f"{WPA_LIB}/{so}"
        if os.path.exists(p):
            shutil.copy2(os.path.realpath(p), f"{OUT}/lib/i386-linux-gnu/{so}")
            n += 1
    # wpa_cli comparte las mismas libs
    cli = f"{WPA_ROOT}/sbin/wpa_cli"
    if os.path.isfile(cli):
        shutil.copy2(cli, f"{OUT}/bin/wpa_cli")
    print(f"  wpa_supplicant + {n} librerias glibc copiadas")


'''
assert anchor in s, "no encontre copy_firmware"
s = s.replace(anchor, new + anchor, 1)

old = "    copy_firmware()"
new2 = "    copy_firmware()\n    copy_wpa()"
assert old in s, "no encontre la llamada a copy_firmware"
s = s.replace(old, new2, 1)

open(P, "w", encoding="utf-8", newline="").write(s)
print("PATCH OK")
