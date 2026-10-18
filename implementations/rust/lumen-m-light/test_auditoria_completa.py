#!/usr/bin/env python3
"""test_auditoria_completa.py — el escenario real, de punta a punta.

Une las tres piezas en el flujo que de verdad se vendería:

    PRODUCTOR                HUB                    AUDITOR
    captura offline    →   sella epoch        →   recibe manifiesto
    (PDB local)            (^AUDIT + registro)     (root + prueba)
                                                   y verifica SIN la PDB

La prueba que importa: **el auditor verifica años después, sin acceso a nada**,
y detecta si alguien intenta colar un dato que no estaba.

Uso: LUMEN_REPO=... python test_auditoria_completa.py
"""
import json
import os
import sys
import tempfile

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "productor.db")
os.environ["LUMEN_ANCLAJE_JSONL"] = os.path.join(_d, "anclajes.jsonl")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))

import pdb_tools as pdb  # noqa: E402
from anclaje import sellar_epoch  # noqa: E402
from digest_canonico import proyeccion  # noqa: E402
from merkle_epoch import prueba_de_inclusion, verificar_inclusion  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


# ── PRODUCTOR: captura un lote completo ────────────────────────────────────
print("=== PRODUCTOR: captura offline ===")
LOTE = [
    ("LOTE", ["L1", "producto"], "cafe arabica"),
    ("LOTE", ["L1", "peso_kg"], 1200),
    ("LOTE", ["L1", "pais"], "co"),
    ("PARCELA", ["P1", "lat"], 4.123456789),
    ("PARCELA", ["P1", "lon"], -74.987654321),
    ("PARCELA", ["P1", "area_ha"], 2.5),
    ("EVIDENCIA", ["L1", "foto1"], "a3f5c9d1e2b4"),
    ("EVIDENCIA", ["L1", "foto2"], "7b2e8f4a1c6d"),
    ("CADENA", ["L1", "cosecha"], "2026-10-12"),
    ("CADENA", ["L1", "secado"], "2026-10-14"),
]
for ns, subs, v in LOTE:
    pdb.tool_set({"ns": ns, "subs": subs, "value": v})
print(f"   {len(LOTE)} eventos, sin red")

# ── HUB: sella cada namespace ──────────────────────────────────────────────
print("\n=== HUB: sella los epochs ===")
sellos = {}
for ns in ("LOTE", "PARCELA", "EVIDENCIA", "CADENA"):
    s = sellar_epoch(pdb, ns, publicar="fichero")
    sellos[ns] = s
    print(f"   {ns:10s} epoch {s['epoch']}  root {s['root'][:20]}…  n={s['n']}")

chk(all(s["n"] > 0 for s in sellos.values()), "todos los namespaces tienen hojas")

# ── AUDITOR: recibe manifiesto + pruebas, sin acceso ──────────────────────
print("\n=== AUDITOR: recibe solo manifiesto + pruebas ===")
manifiesto = {
    "lote": "L1",
    "epochs": {ns: {"root": s["root"], "n": s["n"], "epoch": s["epoch"]}
               for ns, s in sellos.items()},
}
print(f"   manifiesto: {len(json.dumps(manifiesto))} bytes")

# el productor envía una prueba por dato que el auditor quiere comprobar
DATOS = [
    ("LOTE", ["L1", "peso_kg"], 1200),
    ("PARCELA", ["P1", "lat"], 4.123456789),
    ("EVIDENCIA", ["L1", "foto1"], "a3f5c9d1e2b4"),
]
pruebas = []
for ns, subs, val in DATOS:
    linea = proyeccion([{"ns": ns, "subs": subs, "value": val}])[0]
    # el auditor reconstruye el epoch de ese ns a partir del manifiesto
    # (en producción lo recibe entero o pide prueba al hub)
    print(f"   dato: {ns}({subs}) = {val!r}")

# el auditor solo tiene el manifiesto; para verificar necesita la prueba,
# que lleva el camino. Aquí se generan como haría el hub al recibir la petición.
# Se reconstruye el epoch localmente SOLO para generar la prueba (el auditor
# NO tiene esto).
from merkle_epoch import root_de_epoch  # noqa: E402
epocas = {}
for ns in sellos:
    filas = [{"ns": n, "subs": s, "value": v} for n, s, v in LOTE if n == ns]
    epocas[ns] = root_de_epoch(filas)
    # comprobación: el epoch recalculado debe coincidir con el sellado
    chk(epocas[ns]["root"] == sellos[ns]["root"],
        f"{ns}: el epoch recalculado coincide con el sellado")

print("\n=== VERIFICACIÓN (sin la PDB) ===")
for ns, subs, val in DATOS:
    linea = proyeccion([{"ns": ns, "subs": subs, "value": val}])[0]
    p = prueba_de_inclusion(epocas[ns], linea)
    root_pub = manifiesto["epochs"][ns]["root"]
    ok = verificar_inclusion(p, root_pub)
    print(f"   {ns}({subs}) -> {ok}")
    chk(ok, f"el auditor confirma {ns}({subs}) contra el root publicado")

# ── AUDITOR: detecta un dato que NO estaba ────────────────────────────────
print("\n=== AUDITOR: detecta un dato falso ===")
linea_falsa = proyeccion([{"ns": "LOTE", "subs": ["L1", "peso_kg"], "value": 5000}])[0]
chk(prueba_de_inclusion(epocas["LOTE"], linea_falsa) is None,
    "no hay prueba para un peso de 5000: no estaba")

# ── AUDITOR: años después, sin nada ───────────────────────────────────────
print("\n=== AUDITOR, años después: solo JSON ===")
guardado = json.dumps({
    "manifiesto": manifiesto,
    "pruebas": [
        prueba_de_inclusion(epocas[ns], proyeccion([{"ns": ns, "subs": s, "value": v}])[0])
        for ns, s, v in DATOS
    ],
})
del pdb, epocas, sellos, LOTE     # el sistema ya no existe

recuperado = json.loads(guardado)
for i, (ns, subs, val) in enumerate(DATOS):
    ok = verificar_inclusion(recuperado["pruebas"][i],
                             recuperado["manifiesto"]["epochs"][ns]["root"])
    print(f"   {ns}({subs}) -> {ok}")
    chk(ok, f"verifica sin PDB ni sistema: {ns}({subs})")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: auditoría completa sin acceso al sistema de nadie")
