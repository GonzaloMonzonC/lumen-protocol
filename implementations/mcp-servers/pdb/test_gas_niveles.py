#!/usr/bin/env python3
"""test_gas_niveles.py — el gas es un FLUJO por turnos, no un acumulador.

El problema: con un tope fijo, cualquier operacion masiva (importar un millon de
registros) siempre se queda sin gas. El coste crece con los datos; un numero fijo
no puede cubrirlo.

La solucion: separar dos preguntas.
  - cuanto puede costar UN turno   -> gas_limit (el slice)
  - cuanto la operacion ENTERA     -> gas_budget (0 = sin tope)
Al agotar el turno, el motor devuelve `yielded` y se REANUDA.

Comprueba:
  1. normal complete 1M de registros (el caso que motivaba todo)
  2. sandbox corta y lo REPORTA como out_of_gas (no "completed")
  3. el nivel no puede subir por encima del techo del proceso
  4. gas_budget limita el total aunque haya turnos
  5. halted=False con completed es NORMAL (no confundirlo con un corte)

Uso: LUMEN_REPO=... python test_gas_niveles.py
"""
import os
import sys

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))

import lumen_mlight as L  # noqa: E402
from gas import NIVELES, nivel_proceso, resolver  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


def corre(n, **kw):
    p = f'S i=0\nF  S i=i+1 Q:i>{n}  D\n. S ^P(i)=i'
    return L.execute(p, **kw)


print("=== 0. Niveles: turno x turnos ===")
for k, v in NIVELES.items():
    print(f"   {k:10s} turno={v['turno']} turnos={v['turnos']} total={v['total']}")
chk(nivel_proceso() == "normal", f"nivel del proceso = normal ({nivel_proceso()})")

print("\n=== 1. normal completa 1.000.000 de registros ===")
r = corre(1_000_000)
n = len(r.get("globals") or [])
print(f"   1M -> {n:,} globals | exec={r.get('execution')} | completo={r.get('globals_complete')}")
chk(n == 1_000_000, f"vuelven el millon (dio {n:,})")
chk(r.get("execution") == "completed", f"termina (dio {r.get('execution')!r})")
chk(r.get("globals_complete") is True, "globals_complete=True")

print("\n=== 2. sandbox corta y lo REPORTA ===")
r = corre(50_000, gas_level="sandbox")
n = len(r.get("globals") or [])
print(f"   sandbox, 50k -> {n:,} globals | exec={r.get('execution')} | "
      f"turnos={r.get('gas_turnos_usados')}")
chk(n < 50_000, f"sandbox corta (dio {n:,} de 50.000)")
chk(r.get("execution") == "out_of_gas", f"dice out_of_gas (dio {r.get('execution')!r})")
chk(r.get("globals_complete") is False, "globals_complete=False")

print("\n=== 3. El nivel no puede subir por encima del techo ===")
os.environ["LUMEN_GAS_LEVEL"] = "sandbox"
g = resolver("unlimited")
os.environ.pop("LUMEN_GAS_LEVEL")
print(f"   proceso=sandbox pidio unlimited -> nivel={g['nivel']} turno={g['turno']} total={g['budget']}")
chk(g["nivel"] == "sandbox", f"se queda en sandbox (dio {g['nivel']})")
chk(g["turno"] == NIVELES["sandbox"]["turno"], "turno = el de sandbox")
chk(g["budget"] == NIVELES["sandbox"]["total"], "total = el de sandbox")

print("\n=== 4. gas_budget limita el total aunque haya turnos ===")
g = resolver("normal", gas_budget=5000)
print(f"   normal con budget=5000 -> turno={g['turno']} budget={g['budget']}")
chk(g["budget"] == 5000, f"el budget de la llamada manda (dio {g['budget']})")

print("\n=== 5. halted=False con completed es NORMAL ===")
r = corre(10)
st = r.get("state") or {}
print(f"   10 escrituras -> exec={r.get('execution')} halted={st.get('halted')}")
chk(r.get("execution") == "completed", "termina en completed")
chk(r.get("globals_complete") is True,
    "se considera completo aunque halted=False (Completed = ip al final, no HALT)")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: gas por turnos; las operaciones masivas caben y el corte se reporta")
