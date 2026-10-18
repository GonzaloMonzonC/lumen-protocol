#!/usr/bin/env python3
"""test_merkle_epoch.py — anclaje verificable de la PDB (doc 10).

El doc 10 pide: Merkle root por epoch + prueba de inclusión + formato canónico.
Esto comprueba las tres cosas, y lo más importante: que **un tercero verifica
sin tener la PDB ni los datos completos**.

  1. El root es estable entre nodos con los mismos datos.
  2. El root NO depende del orden de inserción (mismo conjunto, distinto orden).
  3. Cambiar un valor cambia el root.
  4. Prueba de inclusión: verifica sin la PDB, sin el árbol, sin los demás datos.
  5. Una prueba manipulada se detecta.
  6. Un dato que no está, no tiene prueba.
  7. Un epoch vacío tiene root definido (se puede probar que estaba vacío).
  8. Usa la MISMA proyección canónica que el digest de estado (doc 15).

Uso: LUMEN_REPO=... python test_merkle_epoch.py
"""
import os
import random
import sys

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))

from digest_canonico import digest_de_globals, proyeccion  # noqa: E402
from merkle_epoch import (  # noqa: E402
    hash_hoja,
    prueba_de_inclusion,
    root_de_epoch,
    verificar_inclusion,
)

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


# ── dataset de prueba: los mismos globals que usa el digest ─────────────────
G = [
    {"ns": "LOTE", "subs": ["L1", "peso"], "value": 1200},
    {"ns": "LOTE", "subs": ["L1", "cafe"], "value": "arabica"},
    {"ns": "LOTE", "subs": ["L2", "peso"], "value": 1500},
    {"ns": "PARCELA", "subs": [1, "lat"], "value": 4.123456789},
    {"ns": "PARCELA", "subs": [1, "lon"], "value": -74.987654321},
]


print("=== 1. Root estable con los mismos datos ===")
e1 = root_de_epoch(G)
e2 = root_de_epoch(list(G))
print(f"   root: {e1['root'][:32]}…  n={e1['n']} alto={e1['alto']}")
chk(e1["root"] == e2["root"], "dos cálculos con los mismos datos dan el mismo root")

print("\n=== 2. NO depende del orden de inserción ===")
G2 = list(G)
random.seed(7)
random.shuffle(G2)
e3 = root_de_epoch(G2)
print(f"   orden invertido -> {e3['root'][:32]}…")
chk(e1["root"] == e3["root"], "el orden de inserción no cambia el root")

print("\n=== 3. Cambiar un valor cambia el root ===")
G3 = [dict(g) for g in G]
G3[0]["value"] = 1201
e4 = root_de_epoch(G3)
print(f"   un peso 1200->1201 -> {e4['root'][:32]}…")
chk(e1["root"] != e4["root"], "un cambio real de dato cambia el root")

print("\n=== 4. Prueba de inclusión verificable SIN la PDB ===")
linea = proyeccion([G[1]])[0]     # 'LOTE␟L1|cafe␟arabica'
prueba = prueba_de_inclusion(e1, linea)
print(f"   línea: {linea!r}")
print(f"   camino de {len(prueba['camino'])} paso(s)")
chk(prueba is not None, "existe prueba para un dato que está")
chk(verificar_inclusion(prueba, e1["root"]), "la prueba verifica contra el root publicado")
chk(verificar_inclusion(prueba), "verifica también sin pasar el root (lo lleva dentro)")

print("\n=== 5. Una prueba manipulada se detecta ===")
mala = dict(prueba)
mala["linea"] = "LOTE\x1fL1|cafe\x1farabica_falso"
mala["hoja"] = hash_hoja(mala["linea"]).hex()
chk(not verificar_inclusion(mala, e1["root"]),
    "cambiar el dato invalida la prueba contra el root")

print("\n=== 6. Un dato que no está, no tiene prueba ===")
chk(prueba_de_inclusion(e1, "NO\x1fEXISTE") is None, "None para un dato ausente")

print("\n=== 7. Epoch vacío tiene root definido ===")
ev = root_de_epoch([])
print(f"   root de vacío: {ev['root'][:32]}…")
chk(ev["root"] and ev["n"] == 0, "un epoch vacío tiene root (se puede probar que estaba vacío)")
chk(ev["root"] != e1["root"], "y es distinto del root con datos")

print("\n=== 8. Misma proyección canónica que el digest de estado ===")
# si la proyección diverge, el root y el digest serían incompatibles
lineas = proyeccion(G)
chk(len(lineas) == len(G), f"una línea canónica por global ({len(lineas)}/{len(G)})")
# el digest de estado se calcula sobre las mismas líneas: un dato añadido debe
# cambiar AMBOS
d_antes = digest_de_globals(G)
d_despues = digest_de_globals(G3)
chk(d_antes != d_despues, "el digest de estado también cambia con el mismo dato")
print(f"   digest estado antes : {d_antes[:16]}")
print(f"   digest estado después: {d_despues[:16]}")

print("\n=== 9. Los floats no rompen el root (misma normalización) ===")
A = [{"ns": "X", "subs": [1], "value": 0.1 + 0.2}]
B = [{"ns": "X", "subs": [1], "value": 0.3}]
chk(root_de_epoch(A)["root"] == root_de_epoch(B)["root"],
    "0.1+0.2 y 0.3 dan el mismo root (absorbe el ULP, igual que el digest)")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: Merkle root por epoch, independiente del orden, verificable sin la PDB")
