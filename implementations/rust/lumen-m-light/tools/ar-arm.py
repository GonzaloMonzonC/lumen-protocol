#!/usr/bin/env python
# ar-arm.py — Wrapper de AR para cross-compilar C con zig (nodos LUMEN).
# Motivo (20-sep-2026): cc-rs de lumen-m-light pasa el valor de AR_<target> como
# programa único; un valor con argumentos ("zig.exe ar") pierde el "ar" y llamba
# a `zig.exe cq lib.a obj.o` → error del archiver. Este wrapper evita el parsing:
#   AR_armv7_unknown_linux_musleabi="python C:/.../tools/ar-arm.py"
# Uso: recibe los args de ar (cq lib.a obj.o...) y los reenvía a `zig ar`.
import os
import subprocess
import sys

ZIG = os.environ.get("ZIGCC_ZIG", r"C:/Users/gonzalo/tools/zig-x86_64-windows-0.16.0/zig.exe")

sys.exit(subprocess.call([ZIG, "ar"] + sys.argv[1:]))
