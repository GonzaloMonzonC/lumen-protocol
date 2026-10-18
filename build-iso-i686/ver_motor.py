#!/usr/bin/env python3
"""Arreglos en el MOTOR M-Light:
  1. '\\' division ENTERA  en apply_operator   (hoy 7\\2 -> 7 en silencio)
  2. '$I' alias de '$IO'                        (hoy 'undefined variable $I')
  3. '$ZJOB' y '$ZU'                            (hoy 'unsupported function')
"""
import re
from pathlib import Path

VM = Path("C:/Users/gonzalo/Documents/GitHub/lumen-protocol/implementations/rust/lumen-m-light/src/vm.rs")
s = VM.read_text(encoding="utf-8")

# ---------- 1. VER apply_operator ----------
i = s.find("fn apply_operator")
print("=== apply_operator ===")
if i < 0:
    print("  NO ENCONTRADA con 'fn apply_operator'")
    for m in re.finditer(r"fn \w*operator\w*", s):
        print("   ", m.group(0), "en", s[:m.start()].count("\n") + 1)
else:
    ln = s[:i].count("\n") + 1
    blk = s[i:i + 2200]
    print(f"  linea {ln}")
    for k, l in enumerate(blk.split("\n")[:45]):
        print(f"   {ln+k:5d} {l}")

# ---------- 2. VER la tabla de funciones $ (vm.rs:2744) ----------
print("\n=== contexto del 'unsupported function' (vm.rs:2744) ===")
j = s.find('"unsupported function {name}"')
if j > 0:
    ini = s.rfind("\n", 0, max(0, j - 3000))
    ln = s[:j].count("\n") + 1
    blk = s[max(0, j - 1600):j + 120]
    for k, l in enumerate(blk.split("\n")):
        print(f"   {ln-40+k:5d} {l}")
else:
    print("  no encontrado")
