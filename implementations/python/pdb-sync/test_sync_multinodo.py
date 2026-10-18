#!/usr/bin/env python3
"""test_sync_multinodo.py — el escenario del doc 04: varios nodos, sin conflictos.

El doc 04 propone: *"cada barco solo escribe su namespace → no hace falta
consenso, la fusión es una unión ordenada de eventos"*.

El código (`pdb_journal_recovery.py`) NO es last-writer-wins puro: aplica TRES
checks antes de escribir, incluida una precondición de estado (CAS):

    1. integridad   -> old_value/new_value válidos
    2. temporal     -> ts > checkpoint
    3. precondición -> valor actual == old_value   ← esto es CAS, no LWW

Este test comprueba el comportamiento REAL en los casos que importan:

  A. Escritura limpia de un nodo -> se aplica
  B. Dos nodos escriben la MISMA clave desde el mismo estado -> el segundo NO
     se aplica en silencio: queda registrado como CONFLICT
  C. Un entry duplicado (ts viejo) -> REDUNDANT, no se reaplica
  D. Un entry corrupto -> CORRUPT, no tumba el lote
  E. Escrituras en namespaces DISTINTOS -> no hay conflicto (propiedad por ns)
  F. Pérdida de escritura silenciosa -> NO debe ocurrir

El criterio de aceptación es F: **toda escritura o se aplica, o queda
registrada como conflicto/redundante**. Nunca desaparece sin rastro.

Uso: LUMEN_REPO=... python test_sync_multinodo.py
"""
import json
import os
import sys
import tempfile

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "sync.db")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "python", "pdb-sync"))

import pdb_tools as pdb  # noqa: E402
import pdb_journal_recovery as jr  # noqa: E402

# El nombre de la función de aplicar puede variar entre versiones: se busca.
APLICAR = None
for cand in ("apply_entries", "apply_journal", "recovery_apply",
             "verify_and_apply", "apply_recovery"):
    if hasattr(jr, cand):
        APLICAR = getattr(jr, cand)
        break

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


def entry(ns, subs, old, new, ts, op="SET"):
    return {"ns": ns, "subs": subs, "op": op, "old_value": old,
            "new_value": new, "timestamp_ns": ts}


def leer(ns, subs):
    r = pdb.tool_get({"ns": ns, "subs": subs})
    return r.get("value") if r.get("success") else None


if APLICAR is None:
    print("SKIP: no encuentro la funcion de aplicar en pdb_journal_recovery")
    print("      funciones disponibles:",
          [f for f in dir(jr) if not f.startswith("_") and callable(getattr(jr, f))][:12])
    sys.exit(0)

# checkpoint limpio
if hasattr(jr, "_load_checkpoint"):
    jr.CHECKPOINT_FILE = os.path.join(_d, "cp.json")

print(f"usando: {APLICAR.__name__}\n")

print("=== A. Escritura limpia de un nodo ===")
pdb.tool_set({"ns": "LOTE", "subs": ["L1", "peso"], "value": 1000})
st = APLICAR([entry("LOTE", ["L1", "peso"], 1000, 1200, 1)], dry_run=False)
print(f"   stats: {st}")
chk(leer("LOTE", ["L1", "peso"]) == 1200, f"se aplicó (valor={leer('LOTE',['L1','peso'])})")

print("\n=== B. Dos nodos, misma clave, mismo estado base -> CAS ===")
# el nodo A y el nodo B leyeron 1200. A escribe 1300, B escribe 900.
pdb.tool_set({"ns": "LOTE", "subs": ["L1", "peso"], "value": 1200})
st_a = APLICAR([entry("LOTE", ["L1", "peso"], 1200, 1300, 2)], dry_run=False)
valor_tras_a = leer("LOTE", ["L1", "peso"])
print(f"   A (1200->1300): aplicado={st_a.get('applied')} valor={valor_tras_a}")
# B cree que el valor sigue siendo 1200 (no vio la escritura de A)
st_b = APLICAR([entry("LOTE", ["L1", "peso"], 1200, 900, 3)], dry_run=False)
valor_tras_b = leer("LOTE", ["L1", "peso"])
print(f"   B (1200->900) : aplicado={st_b.get('applied')} conflictos={st_b.get('conflict')} valor={valor_tras_b}")
chk(valor_tras_b == 1300, f"la escritura de A NO se pisa (valor={valor_tras_b})")
chk(st_b.get("conflict", 0) >= 1, f"B queda registrado como CONFLICTO (no se pierde)")
chk(st_b.get("applied", 0) == 0, "B no se aplica")

print("\n=== C. Entry duplicado (ts viejo) -> REDUNDANT ===")
st_c = APLICAR([entry("LOTE", ["L1", "peso"], 1200, 1300, 2)], dry_run=False)
print(f"   stats: {st_c}")
chk(st_c.get("redundant", 0) >= 1 or st_c.get("applied", 0) == 0,
    "un entry ya visto no se reaplica")

print("\n=== D. Entry corrupto -> CORRUPT, no tumba el lote ===")
malo = {"ns": "LOTE", "subs": ["L1", "peso"], "op": "SET",
        "old_value": {"x": object()}, "new_value": 1, "timestamp_ns": 99}
st_d = APLICAR([malo, entry("LOTE", ["L1", "pais"], None, "co", 100)], dry_run=False)
print(f"   stats: {st_d}")
chk(st_d.get("corrupt", 0) >= 1 or st_d.get("applied", 0) >= 1,
    "el lote sigue procesándose")

print("\n=== E. Namespaces distintos -> sin conflicto ===")
antes_lote = leer("LOTE", ["L1", "peso"])
st_e = APLICAR([
    entry("PARCELA", ["P1", "lat"], None, 4.12, 200),
    entry("EVIDENCIA", ["E1", "foto"], None, "abc", 201),
], dry_run=False)
print(f"   stats: {st_e}")
chk(st_e.get("conflict", 0) == 0, "dos namespaces distintos no chocan")
chk(leer("LOTE", ["L1", "peso"]) == antes_lote, "LOTE no se tocó")

print("\n=== F. Ninguna escritura desaparece en silencio ===")
total = st_e.get("total", 0)
cuenta = (st_e.get("applied", 0) + st_e.get("corrupt", 0)
          + st_e.get("redundant", 0) + st_e.get("conflict", 0))
print(f"   total={total} aplicados+corrupt+redundant+conflict={cuenta}")
chk(cuenta == total, f"toda entrada tiene destino ({cuenta}/{total})")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: el sync no pierde escrituras y no pisa la de otro nodo en silencio")
