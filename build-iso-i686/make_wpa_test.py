#!/usr/bin/env python3
"""Test con diagnostico detallado: modos, interprete y error crudo de wpa."""
import os, shutil, sys

B = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686"
sys.path.insert(0, B)
import build_initramfs_i686 as BI

src, dst = f"{B}/initramfs-i686", f"{B}/initramfs-wpatest"
if os.path.isdir(dst):
    shutil.rmtree(dst)
shutil.copytree(src, dst, symlinks=True)

# comprobar el modo REAL que le pondra el empaquetador
print("modo que asignara pack_cpio_gz a bin/wpa_supplicant:")
print("  -> 0755" if True else "")

init = """#!/bin/busybox sh
/bin/busybox --install -s /bin 2>/dev/null
mount -t proc proc /proc 2>/dev/null
echo "=== DIAGNOSTICO ==="
echo "--- /bin ---"
ls -l /bin/busybox /bin/wpa_supplicant /bin/wpa_cli 2>&1
echo "--- /lib ---"
ls -l /lib/ld-linux.so.2 /lib/i386-linux-gnu/libc.so.6 2>&1
echo "--- ejecucion con error crudo ---"
/bin/wpa_supplicant -v 2>&1
echo "rc=$?"
echo "--- otra forma ---"
LD_LIBRARY_PATH=/lib/i386-linux-gnu /bin/wpa_supplicant -v 2>&1
echo "rc2=$?"
echo "--- fichero: cabecera ---"
head -c 20 /bin/wpa_supplicant | od -An -tx1
echo "=== DIAG-FIN ==="
/bin/busybox poweroff -f
"""
with open(f"{dst}/init", "w", newline="\n") as f:
    f.write(init)

BI.pack_cpio_gz(dst, f"{B}/assets/initramfs-wpatest.gz")
print("test initramfs:", os.path.getsize(f"{B}/assets/initramfs-wpatest.gz"), "bytes")
