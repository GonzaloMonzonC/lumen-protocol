#!/usr/bin/env python3
"""Del volcado de rutinas del MSM, sacar SOLO las de SISTEMA (las '%').
Formato MSM: cada rutina empieza con su nombre al principio de linea;
el codigo va en lineas siguientes. Buscamos cabeceras que empiecen por %."""
import re
from pathlib import Path

P = Path("C:/MsmMw/RUTSaNPERSAND.RUT")
if not P.exists():
    raise SystemExit(f"no existe {P}")

raw = P.read_bytes()
print(f"fichero: {len(raw)} bytes")
print("primeros bytes:", raw[:120])

# probar codificaciones tipicas de MSM (cp437 / latin-1)
txt = None
for enc in ("cp437", "latin-1", "utf-8", "utf-16"):
    try:
        t = raw.decode(enc)
        txt = t
        print(f"\ndecodificado con {enc}: {len(t)} chars, {t.count(chr(12))} form-feeds")
        break
    except Exception:
        continue

if not txt:
    raise SystemExit("no pude decodificar")

lineas = txt.split("\n")
print(f"lineas: {len(lineas)}")
print("\n--- muestra de las primeras 12 lineas ---")
for l in lineas[:12]:
    print("   ", repr(l[:100]))

# cabeceras de rutina: linea que es SOLO el nombre (letras/numeros/%/_)
pat = re.compile(r"^([%A-Za-z][%A-Za-z0-9_]{0,7})\s*$")
nombres = []
for l in lineas:
    m = pat.match(l.rstrip("\r").strip())
    if m:
        nombres.append(m.group(1))

sis = sorted({n for n in nombres if n.startswith("%")})
print(f"\n=== RUTINAS DE SISTEMA (empiezan por %): {len(sis)} ===")
print("  " + "  ".join(sis))
