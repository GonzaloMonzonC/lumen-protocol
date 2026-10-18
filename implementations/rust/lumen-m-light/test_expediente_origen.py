#!/usr/bin/env python3
"""test_expediente_origen.py — el caso del doc 06, de punta a punta.

El doc 06 dice que el producto es "un expediente que un auditor acepta" y que la
prueba definitiva es: *"un auditor externo dice: esto me vale"*.

Esto simula el flujo completo con las dos mitades de la primitiva:

    PRODUCTOR (PDB local)          HUB (consolida)         AUDITOR (verifica)
    captura evidencia offline  →   Merkle root del lote →  verifica con la
    firmada, sin red               + manifiesto             prueba, SIN acceso
                                                            al sistema de nadie

El auditor solo recibe:
  - el manifiesto (root + lista de hashes de evidencia)
  - UNA prueba de inclusión por dato que quiera comprobar
  y no necesita la PDB, ni el sistema del productor, ni el del hub.

Uso: LUMEN_REPO=... python test_expediente_origen.py
"""
import json
import os
import sys
import tempfile

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "productor.db")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))

import pdb_tools as pdb  # noqa: E402
from digest_canonico import proyeccion  # noqa: E402
from merkle_epoch import prueba_de_inclusion, root_de_epoch, verificar_inclusion  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


# ── 1. El productor captura evidencia OFFLINE (PDB local) ───────────────────
print("=== 1. Productor: captura offline en su PDB ===")
EVIDENCIA = [
    ("LOTE", ["L1", "producto"], "cafe arabica"),
    ("LOTE", ["L1", "peso_kg"], 1200),
    ("PARCELA", ["P1", "lat"], 4.123456789),
    ("PARCELA", ["P1", "lon"], -74.987654321),
    ("PARCELA", ["P1", "area_ha"], 2.5),
    ("EVIDENCIA", ["L1", "foto1_hash"], "a3f5c9d1e2b4"),
    ("EVIDENCIA", ["L1", "foto2_hash"], "7b2e8f4a1c6d"),
    ("CADENA", ["L1", "paso1"], "cosecha:2026-10-12"),
    ("CADENA", ["L1", "paso2"], "secado:2026-10-14"),
]
for ns, subs, val in EVIDENCIA:
    pdb.tool_set({"ns": ns, "subs": subs, "value": val})
print(f"   {len(EVIDENCIA)} eventos capturados, sin red")

# globals tal como las devolvería la PDB
globs = [{"ns": ns, "subs": subs, "value": val} for ns, subs, val in EVIDENCIA]

# ── 2. El hub consolida: Merkle root del lote ───────────────────────────────
print("\n=== 2. Hub: consolida el lote y emite el manifiesto ===")
epoch = root_de_epoch(globs)
manifiesto = {
    "lote": "L1",
    "root": epoch["root"],
    "n_eventos": epoch["n"],
    "version": "1",
}
print(f"   root    : {epoch['root'][:32]}…")
print(f"   eventos : {epoch['n']}")
print(f"   manifiesto: {json.dumps(manifiesto, ensure_ascii=False)}")

# ── 3. El auditor verifica SIN acceso a nada ────────────────────────────────
print("\n=== 3. Auditor: verifica sin la PDB, sin el sistema del hub ===")

# lo que el auditor quiere comprobar: ¿el peso declarado es 1200?
dato = {"ns": "LOTE", "subs": ["L1", "peso_kg"], "value": 1200}
linea = proyeccion([dato])[0]
prueba = prueba_de_inclusion(epoch, linea)

# el auditor SOLO recibe (manifiesto, prueba) — nada más
ok_peso = verificar_inclusion(prueba, manifiesto["root"])
print(f"   ¿el peso 1200 está en el lote?  {ok_peso}")
chk(ok_peso, "el auditor confirma el peso con solo la prueba y el root")

# ¿y la parcela?
dato2 = {"ns": "PARCELA", "subs": ["P1", "lat"], "value": 4.123456789}
p2 = prueba_de_inclusion(epoch, proyeccion([dato2])[0])
ok_lat = verificar_inclusion(p2, manifiesto["root"])
print(f"   ¿la latitud está en el lote?    {ok_lat}")
chk(ok_lat, "el auditor confirma la geolocalización de la parcela")

# ── 4. El auditor detecta un fraude ────────────────────────────────────────
print("\n=== 4. Auditor: detecta un peso falsificado ===")
dato_falso = {"ns": "LOTE", "subs": ["L1", "peso_kg"], "value": 2000}
linea_falsa = proyeccion([dato_falso])[0]
p_falsa = prueba_de_inclusion(epoch, linea_falsa)
print(f"   prueba para peso=2000: {p_falsa is not None}")
chk(p_falsa is None, "no existe prueba para un valor que no está (peso 2000)")

# y si alguien fabrica una prueba a mano, el root no cuadra
from merkle_epoch import hash_hoja  # noqa: E402
p_manipulada = {
    "linea": linea_falsa,
    "hoja": hash_hoja(linea_falsa).hex(),
    "camino": prueba["camino"],
    "root": manifiesto["root"],
    "n": manifiesto["n_eventos"],
    "version": "1",
}
chk(not verificar_inclusion(p_manipulada, manifiesto["root"]),
    "una prueba fabricada a mano NO cuadra con el root publicado")

# ── 5. El auditor detecta datos cambiados después ──────────────────────────
print("\n=== 5. Auditor: detecta si el productor cambió un dato después ===")
globs_tocados = [dict(g) for g in globs]
globs_tocados[1]["value"] = 2000      # peso cambiado
epoch_nuevo = root_de_epoch(globs_tocados)
print(f"   root original : {epoch['root'][:32]}…")
print(f"   root con peso 2000: {epoch_nuevo['root'][:32]}…")
chk(epoch["root"] != epoch_nuevo["root"],
    "cambiar el peso produce otro root: el manifiesto viejo ya no cuadra")
chk(not verificar_inclusion(prueba, epoch_nuevo["root"]),
    "la prueba vieja NO valida contra el root nuevo")

# ── 6. El auditor lo re-verifica años después, sin nada ────────────────────
print("\n=== 6. Auditor, años después: solo manifiesto + prueba ===")
manifiesto_guardado = json.dumps(manifiesto)
prueba_guardada = json.dumps(prueba)
del pdb, globs, epoch        # el sistema del productor ya no existe

m = json.loads(manifiesto_guardado)
pr = json.loads(prueba_guardada)
chk(verificar_inclusion(pr, m["root"]),
    "con solo el JSON del manifiesto y la prueba, la verificación sigue valiendo")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: expediente de Origen verificable sin acceso al sistema de nadie")
