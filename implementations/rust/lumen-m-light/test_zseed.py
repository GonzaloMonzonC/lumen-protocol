#!/usr/bin/env python3
"""test_zseed.py — $ZSEED hace el RNG reproducible.

EL PROBLEMA
-----------
`default_rng_state()` siembra el RNG desde el reloj, así que CADA EJECUCIÓN del
mismo programa da valores distintos. Medido con procesos separados antes de este
cambio: [21,65,79,98,32] vs [65,79,98,32,22].

Sin reproducibilidad no hay replay, y sin replay no hay digest por tick ni
certificado de decisión. Los 5 experimentos falsables de
`diseno-organizaciones.md` §7 dejan de ser falsables.

LA SOLUCIÓN
-----------
`$ZSEED(n)` fija la semilla y devuelve la anterior. Se añadió al motor (vm.rs).

Comprueba:
  1. Misma semilla -> misma secuencia, EN PROCESOS SEPARADOS
  2. Semillas distintas -> secuencias distintas
  3. $ZSEED devuelve la semilla anterior (se puede restaurar)
  4. La semilla sobrevive a la serialización del estado (resume)
  5. Dos ejecuciones del MISMO proceso con la misma semilla coinciden

Uso: LUMEN_REPO=... python test_zseed.py
"""
import os
import subprocess
import sys
import tempfile

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_PDB = os.path.join(_REPO, "implementations", "mcp-servers", "pdb")
sys.path.insert(0, _PDB)

import lumen_mlight as L  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


PROG = r"""
S x=$ZSEED({SEED})
S i=0
F  S i=i+1 Q:i>5  D
. S ^R(i)=$R(100)
"""


def secuencia(seed, verbose=False):
    """Ejecuta en un PROCESO NUEVO y devuelve los valores de ^R."""
    d = tempfile.mkdtemp()
    hijo = os.path.join(d, "h.py")
    with open(hijo, "w", encoding="utf-8") as f:
        f.write(f'''
import os, sys
os.environ["PDB_PATH"] = r"{os.path.join(d, "p.db")}"
sys.path.insert(0, r"{_PDB}")
import lumen_mlight as L
r = L.execute("""{PROG.format(SEED=seed)}""")
if r.get("error"):
    print("ERROR:", r["error"]); sys.exit(1)
print(",".join(str(int(g["value"])) for g in (r.get("globals") or []) if g["ns"]=="R"))
''')
    p = subprocess.run([sys.executable, hijo], capture_output=True, text=True, timeout=90)
    if verbose and p.stderr:
        print("   stderr:", p.stderr[:200])
    out = p.stdout.strip()
    return out


print("=== 1. Misma semilla -> misma secuencia (procesos separados) ===")
secs = [secuencia(42) for _ in range(3)]
print(f"   semilla 42: {secs}")
chk(len(set(secs)) == 1, "los 3 procesos dan la MISMA secuencia")
chk(secs[0] and secs[0] != "ERROR", "no hay error de ejecución")

print("\n=== 2. Semillas distintas -> secuencias distintas ===")
s_a = secuencia(42)
s_b = secuencia(99)
print(f"   42: {s_a}")
print(f"   99: {s_b}")
chk(s_a != s_b, "semillas distintas dan secuencias distintas")

print("\n=== 3. $ZSEED devuelve la semilla anterior ===")
r = L.execute("S ^X(1)=$ZSEED(42)\nS ^Y(1)=$ZSEED(7)")
vals = {g["ns"]: g["value"] for g in (r.get("globals") or []) if g["ns"] in ("X", "Y")}
print(f"   semilla tras $ZSEED(42)={vals.get('X')}, tras $ZSEED(7)={vals.get('Y')}")
chk(vals.get("Y") == 42, f"devuelve la anterior (dio {vals.get('Y')}, esperado 42)")

print("\n=== 4. La semilla va en el estado (se puede serializar) ===")
r = L.execute("S x=$ZSEED(123)\nS i=0\nS ^R(0)=$R(100)")
st = r.get("state") or {}
print(f"   rng_state en el estado: {st.get('rng_state')}")
chk(st.get("rng_state") is not None, "rng_state está en el state serializado")
chk(int(st.get("rng_state", 0)) != 0, "no es cero tras sembrar")

print("\n=== 5. Mismo proceso, misma semilla, dos veces ===")
a = L.execute(PROG.format(SEED=7))
b = L.execute(PROG.format(SEED=7))
va = [int(g["value"]) for g in (a.get("globals") or []) if g["ns"] == "R"]
vb = [int(g["value"]) for g in (b.get("globals") or []) if g["ns"] == "R"]
print(f"   run1: {va}")
print(f"   run2: {vb}")
chk(va == vb, "dos ejecuciones con la misma semilla coinciden")
c = L.execute(PROG.format(SEED=8))
vc = [int(g["value"]) for g in (c.get("globals") or []) if g["ns"] == "R"]
print(f"   run3 (semilla 8): {vc}")
chk(vc != va, "con otra semilla la secuencia cambia")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: $ZSEED hace el RNG reproducible entre procesos y ejecuciones")
