#!/usr/bin/env python3
"""Verifica que iwconfig/iwlist son i386 validos, ve que libs piden,
y añade su copia al build del initramfs i686."""
import struct
from pathlib import Path

EXTRA = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/extra-bin")

for f in sorted(EXTRA.iterdir()):
    d = f.read_bytes()
    if d[:4] != b"\x7fELF":
        print(f"{f.name}: no es ELF")
        continue
    clase = "ELF32" if d[4] == 1 else "ELF64"
    mach = struct.unpack_from("<H", d, 18)[0]
    # DT_NEEDED: buscar en .dynamic (aprox: leer la seccion .dynstr por el header)
    libs = []
    for tok in (b"libc.so.6", b"libm.so.6", b"ld-linux.so.2", b"libiw.so",
                b"libnl-3.so", b"libnl-genl-3.so", b"libgcc_s.so.1"):
        if tok in d:
            libs.append(tok.decode())
    print(f"{f.name}: {len(d)} B · {clase} · machine={mach} · libs={libs}")

# ── añadir la copia al build i686 ──
P = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/build-iso-i686/build_initramfs_i686.py")
s = open(P, encoding="utf-8", newline="").read()
if "extra-bin" not in s:
    ancla = '''    _r = f"{MVN}/routines"'''
    nuevo = '''    # 02-oct-2026: iwconfig/iwlist (wireless-tools) para poder diagnosticar la
    # WiFi DENTRO del nodo (en la ISO vieja no estaban y hubo que ir por /sys).
    _eb = f"{os.path.dirname(os.path.abspath(__file__))}/extra-bin"
    if os.path.isdir(_eb):
        os.makedirs(f"{OUT}/bin", exist_ok=True)
        for f in os.listdir(_eb):
            shutil.copy2(os.path.join(_eb, f), f"{OUT}/bin/{f}")
            os.chmod(f"{OUT}/bin/{f}", 0o755)
        print(f"  herramientas extra: {sorted(os.listdir(_eb))}")
    _r = f"{MVN}/routines"'''
    assert ancla in s, "no encontre el ancla de routines"
    s = s.replace(ancla, nuevo, 1)
    open(P, "w", encoding="utf-8", newline="").write(s)
    print("\nbuild_initramfs_i686.py OK: copia extra-bin -> /bin")
else:
    print("\n(ya estaba)")
