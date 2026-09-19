#!/usr/bin/env python
# cc-arm.py — Wrapper de CC para cross-compilar C con zig (nodos LUMEN).
# Problemas que resuelve (medidos 19-sep-2026 con cc-rs 1.4.7 + zig 0.16 + lmdb-master-sys):
#   1) cc-rs pasa su propio --target=<triple-rust> ('armv7-unknown-linux-musleabi') 
#      y zig NO conoce 'armv7' (su nombre es 'arm-linux-musleabi') -> se filtra.
#   2) cc-rs añade -march=armv7-a / -mcpu / -mfloat-abi / -mfpu -> zig tampoco los
#      acepta así; el default del target es suficiente (el bench compiló sin ellos
#      y corre en la DS216se). Se filtran.
# Uso: CC_armv7_unknown_linux_musleabi="python C:/Users/gonzalo/lmdb-test/tools/cc-arm.py"
#      ZIGCC_TARGET opcional (default arm-linux-musleabi; p.ej. aarch64-linux-musl).
import os
import subprocess
import sys

ZIG = os.environ.get("ZIGCC_ZIG", r"C:/Users/gonzalo/tools/zig-x86_64-windows-0.16.0/zig.exe")
TARGET = os.environ.get("ZIGCC_TARGET", "arm-linux-musleabi")

out = []
skip_next = False
for a in sys.argv[1:]:
    if skip_next:
        skip_next = False
        continue
    if a == "-target":
        skip_next = True
        continue
    if a.startswith("--target="):
        continue
    if a.startswith(("-march=", "-mcpu=", "-mtune=", "-mfloat-abi=", "-mfpu=")):
        continue
    out.append(a)

rc = subprocess.run([ZIG, "cc", *out, "-target", TARGET]).returncode
sys.exit(rc)
