#!/usr/bin/env python3
"""
Construye lumenos-i686.iso:
  - ISO9660 + Joliet + RockRidge
  - Arranque BIOS via El Torito (isolinux.bin, no-emulacion, boot info table)
  - Parche isohybrid (MBR isohdpfx.bin) para arrancar tambien desde USB (Rufus DD)
Piezas: initramfs i686 + kernel Debian i686 + isolinux Debian + isohdpfx.bin
"""
import os, sys, struct, random, shutil

HOME = "C:/Users/gonzalo"
B = f"{HOME}/Documents/GitHub/lumen-protocol/build-iso-i686"
A = f"{B}/assets"
BUILD = f"{B}/iso-root"
import os as _os
_SER = _os.environ.get("ISO_SERIAL", "") == "1"
# 04-oct-2026: ISO_OUT permite elegir el nombre de salida. Util cuando el
# lumenos-i686.iso esta bloqueado por Windows (Device or resource busy) y hay
# que escribir directo a -FINAL.iso sin tocar el codigo.
_OUT_ENV = _os.environ.get("ISO_OUT", "").strip()
OUT_ISO = _OUT_ENV if _OUT_ENV else (f"{B}/lumenos-i686-serial.iso" if _SER else f"{B}/lumenos-i686.iso")
VER = "0.1.25"

ISOLINUX_BIN = f"{A}/isolinux-root/usr/lib/ISOLINUX/isolinux.bin"
ISOHDPFX = f"{A}/isolinux-root/usr/lib/ISOLINUX/isohdpfx.bin"
LDLINUX = f"{A}/syslinux-root/usr/lib/syslinux/modules/bios/ldlinux.c32"
# ⚠️ 02-oct-2026: SIN menu.c32 las directivas MENU LABEL NO HACEN NADA:
# isolinux ignora el menu y arranca el DEFAULT sin mostrar nada en pantalla.
MENU_C32 = f"{A}/syslinux-root/usr/lib/syslinux/modules/bios/menu.c32"
KERNEL = f"{A}/kernel-root/boot/vmlinuz-6.1.0-50-686"
INITRD = f"{A}/initramfs-lumenos-i686.gz"

ISOLINUX_CFG = f"""DEFAULT {"serie" if _SER else "lumenos"}
PROMPT 0
TIMEOUT 100
# ⚠️⚠️ 02-oct-2026: FALTA ESTA LINEA = NO HAY MENU ⚠️⚠️
#   Tener menu.c32 en la ISO NO basta: si no se pone `UI menu.c32`, isolinux
#   NO lo carga, IGNORA todas las directivas MENU LABEL y arranca el DEFAULT a
#   los 10s SIN PINTAR NADA. Sintoma exacto: "modo ISO ningun menu".
UI menu.c32

# LUMEN OS i686 (32 bits) — kernel Debian 6.1.0-50-686 + nodo mvm-nas-i686
LABEL lumenos
  MENU LABEL LUMEN OS v{VER}  ·  consola del nodo (i686)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k

LABEL wifi
  MENU LABEL LUMEN OS  ·  consola del nodo + WiFi FORZADA
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k lumenwifi

LABEL sonda
  MENU LABEL LUMEN OS  ·  sonda de diagnostico (automatica)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k lumentest

LABEL serie
  MENU LABEL LUMEN OS  ·  consola por SERIE (depuracion)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 console=ttyS0,115200 fbcon=scrollback:512k

LABEL hw
  MENU LABEL LUMEN OS  ·  SONDA DE HARDWARE (drivers/modprobe/firmware)
  KERNEL /vmlinuz-i686
  INITRD /initramfs-lumenos-i686.gz
  APPEND console=tty0 fbcon=scrollback:512k lumenhw
"""


def stage():
    if os.path.isdir(BUILD):
        shutil.rmtree(BUILD)
    os.makedirs(f"{BUILD}/isolinux", exist_ok=True)
    shutil.copy2(KERNEL, f"{BUILD}/vmlinuz-i686")
    shutil.copy2(INITRD, f"{BUILD}/initramfs-lumenos-i686.gz")
    shutil.copy2(ISOLINUX_BIN, f"{BUILD}/isolinux/isolinux.bin")
    shutil.copy2(LDLINUX, f"{BUILD}/isolinux/ldlinux.c32")
    shutil.copy2(MENU_C32, f"{BUILD}/isolinux/menu.c32")
    # menu.c32 NO carga solo: necesita libutil.c32 y libcom32.c32
    for _l in ("libutil.c32", "libcom32.c32"):
        shutil.copy2(f"{A}/syslinux-root/usr/lib/syslinux/modules/bios/{_l}", f"{BUILD}/isolinux/{_l}")
    with open(f"{BUILD}/isolinux/isolinux.cfg", "w", newline="\n") as f:
        f.write(ISOLINUX_CFG)
    print("  staged:", os.listdir(BUILD))


def build_iso():
    import pycdlib
    print("  add_eltorito signature:", end=" ")
    try:
        import inspect
        print(inspect.signature(pycdlib.PyCdlib.add_eltorito))
    except Exception as e:
        print("(no introspeccionable:", e, ")")

    iso = pycdlib.PyCdlib()
    iso.new(joliet=3, rock_ridge="1.09", vol_ident="LUMENOS_I686")
    iso.add_directory("/ISOLINUX", joliet_path="/isolinux", rr_name="isolinux")
    iso.add_file(f"{BUILD}/vmlinuz-i686", iso_path="/VMLINUZ.I68;1",
                 joliet_path="/vmlinuz-i686", rr_name="vmlinuz-i686")
    iso.add_file(f"{BUILD}/initramfs-lumenos-i686.gz", iso_path="/INITRAM.GZ;1",
                 joliet_path="/initramfs-lumenos-i686.gz",
                 rr_name="initramfs-lumenos-i686.gz")
    iso.add_file(f"{BUILD}/isolinux/isolinux.cfg", iso_path="/ISOLINUX/ISOLINUX.CFG;1",
                 joliet_path="/isolinux/isolinux.cfg", rr_name="isolinux.cfg")
    iso.add_file(f"{BUILD}/isolinux/ldlinux.c32", iso_path="/ISOLINUX/LDLINUX.C32;1",
                 joliet_path="/isolinux/ldlinux.c32", rr_name="ldlinux.c32")
    # ⚠️ 02-oct-2026: SIN menu.c32 las directivas MENU LABEL no hacen NADA:
    # isolinux ignora el menu y arranca el DEFAULT a los 10s SIN MOSTRAR NADA.
    # menu.c32 necesita ademas libutil.c32 y libcom32.c32.
    iso.add_file(f"{BUILD}/isolinux/menu.c32", iso_path="/ISOLINUX/MENU.C32;1",
                 joliet_path="/isolinux/menu.c32", rr_name="menu.c32")
    iso.add_file(f"{BUILD}/isolinux/libutil.c32", iso_path="/ISOLINUX/LIBUTIL.C32;1",
                 joliet_path="/isolinux/libutil.c32", rr_name="libutil.c32")
    iso.add_file(f"{BUILD}/isolinux/libcom32.c32", iso_path="/ISOLINUX/LIBCOM32.C32;1",
                 joliet_path="/isolinux/libcom32.c32", rr_name="libcom32.c32")
    iso.add_file(f"{BUILD}/isolinux/isolinux.bin", iso_path="/ISOLINUX/ISOLINUX.BIN;1",
                 joliet_path="/isolinux/isolinux.bin", rr_name="isolinux.bin")
    iso.add_eltorito("/ISOLINUX/ISOLINUX.BIN;1", "/BOOT.CAT;1",
                     boot_info_table=True, media_name="noemul")
    iso.write(OUT_ISO)
    iso.close()
    print("  iso escrita:", OUT_ISO, os.path.getsize(OUT_ISO), "bytes")


def isohybrid_patch():
    """Escribe el MBR isohdpfx + tabla de particion 1 (todo el ISO) para USB."""
    with open(OUT_ISO, "rb") as f:
        img = bytearray(f.read())
    total_sectors = len(img) // 512
    with open(ISOHDPFX, "rb") as f:
        mbr = bytearray(f.read(432))
    # MBR = 432 bytes de isohdpfx + 8 bytes zona BIOS + firma disco + tabla
    out = bytearray(512)
    out[0:432] = mbr
    out[440:444] = random.randbytes(4)      # disk signature
    part = bytearray(16)
    part[0] = 0x80                          # arrancable
    part[1:4] = bytes([0x00, 0x02, 0x00])   # CHS inicio
    part[4] = 0x17                          # tipo (oculta para Windows)
    part[5:8] = bytes([0xFE, 0xFF, 0xFF])   # CHS fin (saturado)
    part[8:12] = struct.pack("<I", 0)       # LBA inicio
    part[12:16] = struct.pack("<I", total_sectors)
    out[446:462] = part
    out[510:512] = b"\x55\xaa"
    img[0:512] = out
    with open(OUT_ISO, "wb") as f:
        f.write(img)
    print(f"  isohybrid aplicado (total_sectors={total_sectors})")


if __name__ == "__main__":
    print("== staging ==")
    stage()
    print("== construyendo ISO ==")
    build_iso()
    print("== isohybrid (USB) ==")
    isohybrid_patch()
    print("== LISTO:", OUT_ISO, "=")
