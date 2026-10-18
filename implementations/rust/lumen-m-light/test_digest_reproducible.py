#!/usr/bin/env python3
"""test_digest_reproducible.py — el digest canónico resuelve lo que el state no.

Comprueba, en este orden:
  1. El digest del `state` CRUDO NO es reproducible (el problema, demostrado).
  2. El digest CANÓNICO SÍ lo es (la solución).
  3. Discrimina: dos programas con estados distintos dan digests distintos.
  4. Insensible al ruido de float: 0.1+0.2 == 0.3.
  5. Sensible a lo que importa: cambia un valor -> cambia el digest.
  6. Estable entre órdenes de escritura distintos (mismo estado final).
  7. diff_estados dice QUÉ cambió, no solo que cambió.

Uso: LUMEN_REPO=~/Documents/GitHub/lumen-protocol python test_digest_reproducible.py
"""
import hashlib
import json
import os
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

_DEFAULT_REPO = os.path.expanduser("~/Documents/GitHub/lumen-protocol")
_REPO = os.environ.get("LUMEN_REPO", _DEFAULT_REPO)
_PDB = os.path.join(_REPO, "implementations", "mcp-servers", "pdb")
if not os.path.isdir(_PDB):
    sys.exit(f"No encuentro {_PDB} (define LUMEN_REPO)")
sys.path.insert(0, _PDB)
import lumen_mlight as L  # noqa: E402

from digest_canonico import (  # noqa: E402
    digest_de_ejecucion,
    digest_de_globals,
    diff_estados,
    proyeccion,
)

fails = []


def chk(cond, msg):
    if not cond:
        fails.append(msg)


def run(prog):
    return L.execute(prog, gas_limit=2_000_000_000)


def digest_state_crudo(r):
    """Lo que hace hoy quien intente usar `state` como digest."""
    return hashlib.sha256(
        json.dumps(r.get("state"), sort_keys=True, default=str).encode()
    ).hexdigest()[:16]


# ── 1. EL PROBLEMA: el state crudo no es reproducible ────────────────────────
PROG = "S ^A(1)=1\nS ^B(2)=\"x\"\n"
crudos = [digest_state_crudo(run(PROG)) for _ in range(4)]
print("1. state CRUDO, 4 ejecuciones:")
for i, d in enumerate(crudos, 1):
    print(f"     run {i}: {d}")
chk(len(set(crudos)) > 1,
    "el state crudo salio REPRODUCIBLE: entonces no habia problema y este test "
    "no demuestra nada (revisar si la VM dejo de meter zh_start)")
print(f"   -> {'reproducible' if len(set(crudos)) == 1 else 'NO reproducible (problema confirmado)'}\n")

# ── 2. LA SOLUCIÓN: el digest canónico sí lo es ──────────────────────────────
canonicos = [digest_de_globals(run(PROG).get("globals")) for _ in range(4)]
print("2. digest CANÓNICO, 4 ejecuciones:")
for i, d in enumerate(canonicos, 1):
    print(f"     run {i}: {d[:16]}")
chk(len(set(canonicos)) == 1,
    f"el digest canónico NO es reproducible: {canonicos}")
print(f"   -> {'reproducible' if len(set(canonicos)) == 1 else 'FALLA'}\n")

# ── 3. Discrimina: estados distintos -> digests distintos ────────────────────
d_a = digest_de_globals(run("S ^A(1)=1").get("globals"))
d_b = digest_de_globals(run("S ^A(1)=2").get("globals"))
chk(d_a != d_b, "dos estados distintos dan el MISMO digest: no discrimina")
print(f"3. ^A(1)=1 vs ^A(1)=2 -> {'distintos OK' if d_a != d_b else 'IGUALES: FALLA'}\n")

# ── 4. Ruido de float: 0.1+0.2 debe igualar a 0.3 ───────────────────────────
d_suma = digest_de_globals(run("S ^X=0.1+0.2").get("globals"))
d_directo = digest_de_globals(run("S ^X=0.3").get("globals"))
raw_suma = run("S ^X=0.1+0.2").get("globals")
print(f"4. 0.1+0.2 -> valor crudo {raw_suma[0]['value']!r}")
chk(d_suma == d_directo,
    f"0.1+0.2 y 0.3 dan digests distintos ({d_suma[:12]} vs {d_directo[:12]})")
print(f"   -> {'iguales OK (absorbe el ULP)' if d_suma == d_directo else 'DISTINTOS: FALLA'}\n")

# ── 5. Sensible a cambios reales de valor ───────────────────────────────────
chk(d_a != digest_de_globals(run("S ^A(1)=1.0000001").get("globals")),
    "un cambio de valor real NO cambia el digest")
print("5. cambio de valor real -> cambia el digest: OK\n")

# ── 6. Estable ante distinto ORDEN de escritura (mismo estado final) ────────
d_ord1 = digest_de_globals(run("S ^A(1)=1\nS ^A(2)=2\nS ^B(1)=9").get("globals"))
d_ord2 = digest_de_globals(run("S ^B(1)=9\nS ^A(2)=2\nS ^A(1)=1").get("globals"))
chk(d_ord1 == d_ord2, "el orden de escritura cambia el digest: no es canónico")
print(f"6. distinto orden de escritura -> {'mismo digest OK' if d_ord1 == d_ord2 else 'DISTINTO: FALLA'}\n")

# ── 7. diff_estados dice QUÉ cambió ────────────────────────────────────────
g1 = run("S ^D(1)=\"ok\"\nS ^D(2)=\"ok\"\nS ^D(3)=\"ok\"").get("globals")
g2 = run("S ^D(1)=\"ok\"\nS ^D(2)=\"NO\"\nS ^D(3)=\"ok\"").get("globals")
diff = diff_estados(g1, g2)
print(f"7. diff de estados: {diff['n_cambios']} cambio(s)")
for l in diff["solo_en_a"]:
    print(f"     antes : {l!r}")
for l in diff["solo_en_b"]:
    print(f"     ahora : {l!r}")
chk(diff["n_cambios"] == 2, f"esperaba 2 lineas cambiadas, hay {diff['n_cambios']}")
chk(not diff["iguales"], "diff dice iguales cuando deberian diferir")
print()

# ── 8. El digest de ejecución incluye el programa ──────────────────────────
e1 = digest_de_ejecucion("S ^A=1", run("S ^A=1"))
e2 = digest_de_ejecucion("S ^A=2", run("S ^A=2"))
e3 = digest_de_ejecucion("S ^A=1", run("S ^A=1"))
chk(e1 == e3, "digest de ejecución no reproducible")
chk(e1 != e2, "digest de ejecución no distingue programas")
print(f"8. digest de ejecución: reproducible={e1 == e3} discrimina={e1 != e2}\n")

# ── resumen ────────────────────────────────────────────────────────────────
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: el digest canónico es reproducible, discrimina y resiste floats")
print(f"      ejemplo de certificado: {canonicos[0]}")
