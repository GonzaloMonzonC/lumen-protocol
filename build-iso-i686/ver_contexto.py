#!/usr/bin/env python3
"""Mete la ^GUIA en el contexto que se inyecta al LLM (node_context / build_system).
Sin tocar nada mas: si no encuentra el punto exacto, NO toca nada y lo dice."""
import re
from pathlib import Path

P = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/src/main.rs")
s = open(P, encoding="utf-8", newline="").read()

print("=== 1. VER node_context ===")
i = s.find("fn node_context")
if i < 0:
    raise SystemExit("NO encuentro fn node_context")
ln = s[:i].count("\n") + 1
# imprimir la funcion (hasta 3 lineas en blanco o siguiente fn)
blk = s[i:i + 4000]
corte = blk.find("\nfn ")
if corte > 0:
    blk = blk[:corte]
print(f"  linea {ln} · {blk.count(chr(10))} lineas")
for k, l in enumerate(blk.split("\n")[:60]):
    print(f"   {ln+k:5d} {l}")

# ¿ya tiene la guia?
if "%GUIA" in s or "GUIA" in s:
    print("\n  (ya hay algo de GUIA en el fichero)")
