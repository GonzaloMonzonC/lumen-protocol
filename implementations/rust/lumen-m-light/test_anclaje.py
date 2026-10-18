#!/usr/bin/env python3
"""test_anclaje.py — el circuito completo: PDB → root → sello → verificación.

Cierra lo que el doc 10 pide en su nivel A: "Merkle epoch + log de
transparencia, días de trabajo, sirve a todos los verticales".

  1. Sellar un namespace deja el epoch en ^AUDIT de la propia PDB.
  2. El sello publicado coincide con el que hay en la PDB.
  3. Un sello con root manipulado se detecta.
  4. El registro es append-only y los epochs son consecutivos.
  5. Varios namespaces llevan su propia numeración independiente.
  6. Cambiar un dato y volver a sellar produce un root distinto.
  7. Un sello vale aunque la PDB haya cambiado después (prueba de época).

Uso: LUMEN_REPO=... python test_anclaje.py
"""
import json
import os
import sys
import tempfile

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "p.db")
os.environ["LUMEN_ANCLAJE_JSONL"] = os.path.join(_d, "anclajes.jsonl")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))

import pdb_tools as pdb  # noqa: E402
from anclaje import (  # noqa: E402
    leer_epoch,
    leer_registro,
    sellar_epoch,
    verificar_cadena_registro,
    verificar_epoch_publicado,
)
from merkle_epoch import prueba_de_inclusion, root_de_epoch, verificar_inclusion  # noqa: E402
from digest_canonico import proyeccion  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


# ── datos de un productor ──────────────────────────────────────────────────
for k, v in (("peso", 1200), ("pais", "co"), ("cosecha", "2026-10-12")):
    pdb.tool_set({"ns": "LOTE", "subs": ["L1", k], "value": v})
pdb.tool_set({"ns": "LOTE", "subs": ["L2", "peso"], "value": 1500})
pdb.tool_set({"ns": "PARCELA", "subs": ["P1", "lat"], "value": 4.12})

print("=== 1. Sellar deja el epoch en ^AUDIT ===")
s1 = sellar_epoch(pdb, "LOTE", publicar="fichero")
print(f"   epoch={s1['epoch']} root={s1['root'][:24]}… n={s1['n']}")
chk(s1["epoch"] == 1, f"primer epoch es 1 (dio {s1['epoch']})")
chk(s1["n"] == 4, f"4 hojas en LOTE (dio {s1['n']})")
en_pdb = leer_epoch(pdb, "LOTE", 1)
chk(en_pdb is not None, "el epoch se puede recuperar de la PDB")
chk(en_pdb["root"] == s1["root"], "el root guardado coincide")

print("\n=== 2. El sello coincide con la PDB ===")
v = verificar_epoch_publicado(pdb, s1)
print(f"   {v['motivo']}")
chk(v["ok"], "un sello honesto verifica")

print("\n=== 3. Un sello manipulado se detecta ===")
falso = dict(s1)
falso["root"] = "0" * 64
v2 = verificar_epoch_publicado(pdb, falso)
print(f"   {v2['motivo']}")
chk(not v2["ok"], "un root inventado NO verifica contra la PDB")

print("\n=== 4. Registro append-only y epochs consecutivos ===")
s2 = sellar_epoch(pdb, "LOTE", publicar="fichero")
s3 = sellar_epoch(pdb, "LOTE", publicar="fichero")
reg = leer_registro()
print(f"   {len(reg)} sellos, epochs {[s['epoch'] for s in reg]}")
chk(len(reg) == 3, f"3 sellos en el registro (dio {len(reg)})")
cad = verificar_cadena_registro()
print(f"   cadena OK: {cad['ok']}")
chk(cad["ok"], "los epochs son consecutivos, sin huecos")

print("\n=== 5. Cada namespace numera por su cuenta ===")
sp = sellar_epoch(pdb, "PARCELA", publicar="fichero")
print(f"   PARCELA epoch={sp['epoch']} (debe ser 1, no 4)")
chk(sp["epoch"] == 1, f"PARCELA empieza en 1 (dio {sp['epoch']})")
chk(sp["root"] != s1["root"], "su root es distinto del de LOTE")

print("\n=== 6. Cambiar un dato cambia el root al resellar ===")
pdb.tool_set({"ns": "LOTE", "subs": ["L1", "peso"], "value": 2000})
s4 = sellar_epoch(pdb, "LOTE", publicar="fichero")
print(f"   root antes : {s3['root'][:24]}…")
print(f"   root ahora : {s4['root'][:24]}…")
chk(s4["root"] != s3["root"], "el nuevo epoch refleja el dato cambiado")

print("\n=== 7. Un sello viejo sigue valiendo para SU época ===")
# el sello s3 se emitió cuando el peso era 1200; el dato ya cambió, pero la
# prueba de esa época debe seguir verificando contra el root de entonces
epoch_viejo = leer_epoch(pdb, "LOTE", 3)
print(f"   epoch 3 (peso 1200) sigue en la PDB: {epoch_viejo is not None}")
chk(epoch_viejo is not None, "los epochs viejos no se borran al resellar")
chk(epoch_viejo["root"] == s3["root"],
    "el root del epoch 3 es el de su época, no el actual")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: circuito PDB -> root -> sello -> verificacion, con historico")
