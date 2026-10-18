#!/usr/bin/env python3
"""test_ots.py — anclaje REAL en Bitcoin via OpenTimestamps.

El doc 10 dice: "necesitas raíces de Merkle **y un notario público**". Las raíces
ya están (merkle_epoch.py). Esto prueba el notario.

NO usa el cliente `ots` (falla en Windows con WinError 193); habla el protocolo
HTTP directo con los calendar servers públicos.

Comprueba:
  1. Los calendars responden
  2. El root se ancla y devuelve una prueba de compromiso
  3. La prueba se guarda y se puede releer
  4. Un root distinto produce un digest distinto (no hay colisiones de juguete)
  5. Integración con anclaje.sellar_epoch(publicar="ots")

Requiere red. Si no hay, sale con SKIP (no FALLO): el anclaje es opcional.

Uso: LUMEN_REPO=... python test_ots.py
"""
import os
import sys
import tempfile

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "p.db")
os.environ["LUMEN_ANCLAJE_JSONL"] = os.path.join(_d, "anclajes.jsonl")
os.environ["LUMEN_OTS_DIR"] = os.path.join(_d, "ots")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))

from publicar_ots import (  # noqa: E402
    digest_de_root,
    estado,
    guardar_prueba,
    leer_prueba,
    sellar_en_ots,
)

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


print("=== 1. Los calendars responden ===")
e = estado()
print(f"   {e}")
if not e.get("ok"):
    print("   SKIP: sin red, no se puede probar el anclaje externo")
    sys.exit(0)
chk(e["ok"], "al menos un calendar responde")

ROOT = "391ed86342da8c7abbd99e08ce27133cce34bab3c0dea6cb7b5ceaa61753bfe8"

print("\n=== 2. Anclar el root ===")
s = sellar_en_ots(ROOT)
print(f"   ok={s.get('ok')} calendar={s.get('calendar')} bytes={s.get('bytes')}")
if s.get("errores"):
    print(f"   errores: {s['errores']}")
chk(s.get("ok"), "el root se ancla")
chk(s.get("bytes", 0) > 50, f"devuelve una prueba ({s.get('bytes')} bytes)")
chk(s.get("digest") == digest_de_root(ROOT).hex(), "el digest es el esperado")

print("\n=== 3. La prueba se guarda y se relee ===")
f = guardar_prueba(s)
leido = leer_prueba(ROOT)
print(f"   fichero: {os.path.basename(f)}")
chk(os.path.exists(f), "el JSON de la prueba existe")
chk(leido is not None and leido.get("root") == ROOT, "se relee con el root correcto")
binary = os.path.join(os.environ["LUMEN_OTS_DIR"], f"{ROOT[:16]}.ots.bin")
chk(os.path.exists(binary), "la prueba binaria está en disco")

print("\n=== 4. Roots distintos -> digests distintos ===")
ROOT2 = "926cce3194b042945a6f7390675ef0f1" + "0" * 32
d1 = digest_de_root(ROOT)
d2 = digest_de_root(ROOT2)
print(f"   {d1.hex()[:16]}… vs {d2.hex()[:16]}…")
chk(d1 != d2, "digests distintos para roots distintos")

print("\n=== 5. Integración con sellar_epoch(publicar='ots') ===")
import pdb_tools as pdb  # noqa: E402
from anclaje import sellar_epoch  # noqa: E402

for k, v in (("peso", 1200), ("pais", "co")):
    pdb.tool_set({"ns": "LOTE", "subs": ["L1", k], "value": v})

sello = sellar_epoch(pdb, "LOTE", publicar="ots")
print(f"   root    : {sello['root'][:24]}…")
print(f"   publicado: {sello.get('publicado')} en {sello.get('publicado_en')}")
print(f"   ots     : ok={sello.get('ots', {}).get('ok')} bytes={sello.get('ots', {}).get('bytes')}")
chk(sello.get("publicado") is True, "el sello queda publicado en OTS")
chk(sello.get("ots", {}).get("ok") is True, "la prueba OTS está en el sello")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f_ in fails:
        print(f"   - {f_}")
    sys.exit(1)
print("PASS: root anclado en OpenTimestamps (Bitcoin), prueba guardada")
