#!/usr/bin/env bash
# Prueba de arranque REAL del LUMEN OS i686 en QEMU (sin pantalla, por serie).
# 1) initramfs directo (kernel + initrd) en modo sonda -> autodiagnostico + poweroff
# 2) la ISO como disco -> valida la capa isolinux/isohybrid
set -u
cd /c/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686 || exit 1
QEMU="/c/Users/gonzalo/tools/qemu/qemu-system-i386.exe"
[ -x "$QEMU" ] || QEMU="/c/Program Files/qemu/qemu-system-i386.exe"

echo "=== TEST 1: initramfs directo (sonda lumentest, consola serie) ==="
timeout 300 "$QEMU" -m 1024 -smp 1 \
  -kernel assets/kernel-root/boot/vmlinuz-6.1.0-50-686 \
  -initrd assets/initramfs-lumenos-i686.gz \
  -append "console=ttyS0 lumentest" \
  -nographic -no-reboot > boot-i686-initramfs.log 2>&1
echo "  qemu exit=$? (esperado 0; poweroff limpio)"

echo "=== evidencia (lineas clave) ==="
grep -aE 'LUMEN|\[hardware\]|\[red\]|\[pdb\]|rutina|sonda|Power down|Kernel panic|not found' \
  boot-i686-initramfs.log | head -25
echo "=== GPU/apagado ==="
grep -aE 'Power down|reboot: Power' boot-i686-initramfs.log | tail -2

echo
echo "=== TEST 2: la ISO (isolinux + isohybrid) ==="
timeout 300 "$QEMU" -m 1024 -smp 1 -cdrom lumenos-i686.iso -boot d \
  -netdev user,id=n0 -device e1000,netdev=n0 \
  -nographic -no-reboot > boot-i686-iso.log 2>&1
echo "  qemu exit=$?"
grep -aiE 'isolinux|LUMEN|kernel|initrd|Power down|panic' boot-i686-iso.log | head -12
