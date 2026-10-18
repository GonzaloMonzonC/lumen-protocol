#!/usr/bin/env python3
"""Que hay DENTRO de las ISOs? (menú de arranque, isolinux, fechas)"""
import os
from pathlib import Path

import pycdlib

BUILD = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/build")
for iso in sorted(BUILD.glob("*.iso")):
    st = iso.stat()
    import datetime
    print("=" * 70)
    print(f"{iso.name}")
    print(f"   {st.st_size} bytes · {datetime.datetime.fromtimestamp(st.st_mtime):%d-%b %H:%M}")
    lib = pycdlib.PyCdlib()
    try:
        lib.open(str(iso))
    except Exception as e:
        print("   ERR", e)
        continue
    rutas = []
    lib.walk(rr_path="/", callback=lambda *a: rutas.append(a[0] if a else ""))
    # listado simple
    try:
        for child in lib.list_children(rr_path="/"):
            n = child.file_identifier().decode("utf-8", "replace")
            rutas.append(n)
    except Exception:
        pass
    print("   raiz:", sorted(set(rutas))[:14])
    # isolinux dir
    for d in ("/isolinux", "/boot/isolinux", "/syslinux"):
        try:
            hijos = [c.file_identifier().decode("utf-8", "replace")
                     for c in lib.list_children(rr_path=d)]
            print(f"   {d}: {sorted(hijos)}")
        except Exception:
            pass
    lib.close()
