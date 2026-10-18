#!/usr/bin/env python3
"""Descarga kbd i386 (loadkeys + mapas de teclado) y muestra su estructura."""
import os, subprocess, sys

B = "C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686"
ASSETS = f"{B}/assets"
DEB = f"{ASSETS}/kbd.deb"
ROOT = f"{ASSETS}/kbd-root"

if not os.path.isfile(DEB):
    url = "https://deb.debian.org/debian/pool/main/k/kbd/kbd_2.5.1-1+b1_i386.deb"
    subprocess.run(["curl", "-sL", "-o", DEB, url], check=False)
print("kbd.deb:", os.path.getsize(DEB), "bytes")

sys.path.insert(0, B)
from extract_deb import main as ex
ex(DEB, ROOT)

print("\n== binarios ==")
for r, _, fs in os.walk(ROOT):
    for f in fs:
        if f in ("loadkeys", "setfont", "dumpkeys"):
            p = os.path.join(r, f)
            print("  ", p.replace(ROOT, ""), os.path.getsize(p), "B")

print("\n== mapas es/uk/de/fr ==")
n = 0
for r, _, fs in os.walk(ROOT):
    for f in fs:
        if f.endswith(".map.gz") and any(f.startswith(p) for p in ("es", "uk", "de", "fr", "it", "pt")):
            print("  ", os.path.join(r, f).replace(ROOT, ""))
            n += 1
            if n > 12:
                break
print(f"  (total {n})")
print("\n== fuentes de consola ==")
print("  consolefonts:", os.path.isdir(f"{ROOT}/usr/share/consolefonts") or os.path.isdir(f"{ROOT}/usr/share/kbd/consolefonts"))
