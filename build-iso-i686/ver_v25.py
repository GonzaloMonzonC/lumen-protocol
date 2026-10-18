#!/usr/bin/env python3
"""Verifica la ISO v25: menu.c32 cargado en el config, entrada wifi, y arranque USB (isohybrid)."""
import io

import pycdlib

ISO = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/lumenos-i686-v25.iso"
iso = pycdlib.PyCdlib()
iso.open(ISO)

buf = io.BytesIO()
iso.get_file_from_iso_fp(buf, iso_path="/ISOLINUX/ISOLINUX.CFG;1")
cfg = buf.getvalue().decode("utf-8", "replace")

print("--- config de arranque DENTRO de la ISO ---")
print("  'UI menu.c32'      :", "SI ✓" if "UI menu.c32" in cfg else "NO ✗")
print("  entrada 'wifi'     :", "SI ✓" if "lumenwifi" in cfg else "NO ✗")
print("  nº de LABEL        :", cfg.count("LABEL "))
print()
print("--- arranque por USB (DD) ---")
b = open(ISO, "rb").read(512)
print("  firma MBR 55AA     :", b[510:512].hex().upper(), "✓" if b[510:512] == b"\x55\xaa" else "✗")
print("  particion 1 tipo   :", hex(b[446 + 4]), "(0x17 = FAT oculta, lo normal en isohybrid)")
print("  LBA arranque/sect. :", int.from_bytes(b[446 + 8:446 + 12], "little"),
      "/", int.from_bytes(b[446 + 12:446 + 16], "little"))
print("  ¿hay isohdpfx?     :",
      "SI" if b[0:2] in (b"\x33\xed", b"\xfa\x33", b"\x33\xc0") or b[0] != 0 else "?")
iso.close()
