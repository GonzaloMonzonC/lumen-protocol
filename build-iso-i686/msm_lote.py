#!/usr/bin/env python3
"""Extrae del volcado del MSM las rutinas de SISTEMA una a una y las guarda
como referencia para LUMEN OPS."""
import re
from pathlib import Path

FUENTE = Path("C:/MsmMw/RUTSaNPERSAND.RUT")
DEST = Path("C:/Users/gonzalo/Documents/GitHub/mvm-nas/lumenos/MSM-SISTEMA.md")

raw = FUENTE.read_bytes().decode("cp437")
L = [l.rstrip("\r") for l in raw.split("\n")]
pat = re.compile(r"^([%A-Za-z][%A-Za-z0-9_]{0,7})\s*$")

# indice: nombre -> linea
idx = {}
for i, l in enumerate(L):
    m = pat.match(l.strip())
    if m:
        n = m.group(1)
        if n not in idx:
            idx[n] = i


def saca(nombre, maxl=150):
    i = idx.get(nombre)
    if i is None:
        return None
    out = []
    for j in range(i, min(i + maxl, len(L))):
        if j > i and pat.match(L[j].strip()):
            break
        out.append(L[j])
    return out


# las de SISTEMA, por grupos
GRUPOS = [
    ("AYUDANTES COMPARTIDOS (la base de todo)", ["%UTL", "%UTLH", "%D", "%T", "%DEVICE", "%VIDEO"]),
    ("TOP / ESTADO", ["%SS", "%SSVN", "%MEM", "%ACTJOB"]),
    ("GLOBALS / DIRECTORIO", ["%GD", "%G", "%GL", "%GDE", "%GCOPY", "%GSIZE", "%RSIZE", "%GR"]),
    ("EDITOR", ["%GE", "%GEDIT", "%GEDIT1", "%GS", "%GSEL", "%NEWED"]),
    ("HELP", ["%HELP"]),
    ("DEPURACION", ["%DEBUG", "%DEBUGI", "%D", "%DO"]),
    ("UTILIDADES", ["%UT", "%SQRT", "%INDEX", "%INDSTR", "%SRCHPAT", "%TRANS", "%T"]),
    ("SISTEMA", ["%LOGON", "%RELOAD", "%DBSYNC", "%DOMAIN", "%ERRCODE"]),
]

lineas = ["# RUTINAS DE SISTEMA DEL MSM (referencia para LUMEN OPS)", ""]
lineas.append(f"Extraidas de: `{FUENTE}` ({FUENTE.stat().st_size} bytes, MSM original)")
lineas.append("")
lineas.append("Uso: referencia para escribir las nuestras «a la manera del MSM».")
lineas.append("")
resumen = []
for titulo, nombres in GRUPOS:
    lineas.append(f"## {titulo}")
    lineas.append("")
    for n in nombres:
        code = saca(n)
        if not code:
            continue
        resumen.append((n, len(code), titulo))
        lineas.append(f"### `{n}`  ({len(code)} líneas)")
        lineas.append("```mumps")
        lineas.extend(code[:60])
        if len(code) > 60:
            lineas.append(f"; ... ({len(code) - 60} líneas más)")
        lineas.append("```")
        lineas.append("")

DEST.write_text("\n".join(lineas), encoding="utf-8")
print(f"escrito: {DEST} ({DEST.stat().st_size} bytes)")
print(f"\n{'RUTINA':<10} {'LINEAS':>7}  GRUPO")
for n, l, g in resumen:
    print(f"  {n:<10} {l:>6}  {g}")
print(f"\ntotal rutinas extraidas: {len(resumen)}")
