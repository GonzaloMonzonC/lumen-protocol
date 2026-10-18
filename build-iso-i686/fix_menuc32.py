#!/usr/bin/env python3
"""FIX del MENÚ DE ARRANQUE: falta menu.c32 en la ISO.

Las directivas MENU LABEL del isolinux.cfg NO hacen nada sin menu.c32: isolinux
ignora el menu y arranca el DEFAULT a los 10s SIN MOSTRAR NADA. Es exactamente
lo que ve Gonzalo ("no sale nada de esto del menu ni nada").
"""
import os
from pathlib import Path

A = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/assets")
DIR = A / "syslinux-root/usr/lib/syslinux/modules/bios"
print("buscando en:", DIR)
if DIR.exists():
    c32 = sorted(p.name for p in DIR.iterdir() if p.suffix == ".c32")
    print("  .c32 disponibles:", c32)
else:
    print("  !! no existe; buscando syslinux en assets:")
    for p in A.glob("*/usr/lib/**/*.c32"):
        print("   ", p)

MENU = DIR / "menu.c32"
if not MENU.exists():
    print("\n  🔴 menu.c32 NO ESTA en el paquete syslinux extraido.")
    raise SystemExit(1)

P = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_iso_i686.py")
s = open(P, encoding="utf-8", newline="").read()
if "menu.c32" in s:
    print("\n(ya estaba parcheado)")
    raise SystemExit(0)

s = s.replace(
    'LDLINUX = f"{A}/syslinux-root/usr/lib/syslinux/modules/bios/ldlinux.c32"',
    'LDLINUX = f"{A}/syslinux-root/usr/lib/syslinux/modules/bios/ldlinux.c32"\n'
    '# ⚠️ 02-oct-2026: SIN menu.c32 las directivas MENU LABEL NO HACEN NADA:\n'
    '# isolinux ignora el menu y arranca el DEFAULT sin mostrar nada en pantalla.\n'
    'MENU_C32 = f"{A}/syslinux-root/usr/lib/syslinux/modules/bios/menu.c32"', 1)

s = s.replace(
    '    shutil.copy2(LDLINUX, f"{BUILD}/isolinux/ldlinux.c32")',
    '    shutil.copy2(LDLINUX, f"{BUILD}/isolinux/ldlinux.c32")\n'
    '    shutil.copy2(MENU_C32, f"{BUILD}/isolinux/menu.c32")', 1)

s = s.replace(
    '                 rr_name="ldlinux.c32")\n',
    '                 rr_name="ldlinux.c32")\n'
    '    iso.add_file(f"{BUILD}/isolinux/menu.c32", iso_path="/ISOLINUX/MENU.C32;1",\n'
    '                 joliet_path="/isolinux/menu.c32", rr_name="menu.c32")\n', 1)

open(P, "w", encoding="utf-8", newline="").write(s)
print("\nbuild_iso_i686.py OK: ahora mete menu.c32 en la ISO")
