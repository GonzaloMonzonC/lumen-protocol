#!/usr/bin/env python3
"""test_merkle_stream.py — Mismo root, memoria acotada.

`root_de_epoch(leer_ns_rango(pdb, ns))` acumula todo: ~1 GB por millón de claves.

`root_stream_ns(pdb, ns)` hashea en streaming: no guarda dicts, solo hashes.

Comprueba:
  1. MISMO root que el camino clásico (lo único que no puede fallar)
  2. Mismo `n` y mismo `alto`
  3. Memoria muy inferior (medida con tracemalloc)
  4. Funciona con subárboles
  5. Hoja impar: mismo resultado
  6. Epoch vacío
  7. Escala a 1M sin agotar memoria

Uso: LUMEN_REPO=... python test_merkle_stream.py [--grande]
"""
import os
import sys
import tempfile
import tracemalloc

GRANDE = "--grande" in sys.argv

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "p.db")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))

import pdb_tools as pdb  # noqa: E402
from pdb_tools import encode_subkey  # noqa: E402
from lectura_rango import leer_ns_rango  # noqa: E402
from merkle_epoch import root_de_epoch  # noqa: E402
from merkle_stream import root_stream_filas, root_stream_ns  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


def llenar(ns, n, base=0):
    c = pdb._get_conn(ns, None)
    c.executemany(
        "INSERT OR REPLACE INTO _globals (ns,subkey,value) VALUES (?,?,?)",
        [(ns, encode_subkey([i]), str(i)) for i in range(base, base + n)])
    c.commit()


print("=== 1. Mismo root que el camino clásico ===")
llenar("A", 1000)
clasico = root_de_epoch(leer_ns_rango(pdb, "A"))
stream = root_stream_ns(pdb, "A")
print(f"   clasico: {clasico['root'][:24]}… n={clasico['n']} alto={clasico['alto']}")
print(f"   stream : {stream['root'][:24]}… n={stream['n']} alto={stream['alto']}")
chk(clasico["root"] == stream["root"], "MISMO root")
chk(clasico["n"] == stream["n"], "mismo numero de hojas")
chk(clasico["alto"] == stream["alto"], "misma altura de arbol")

print("\n=== 2. Hoja impar (999 y 1001) ===")
for n in (999, 1001):
    c = pdb._get_conn("I", None)
    c.execute("DELETE FROM _globals WHERE ns='I'")
    c.commit()
    llenar("I", n)
    a = root_de_epoch(leer_ns_rango(pdb, "I"))
    b = root_stream_ns(pdb, "I")
    print(f"   {n} hojas: {a['root'][:16]}… vs {b['root'][:16]}…")
    chk(a["root"] == b["root"], f"{n} hojas -> mismo root (impar manejado igual)")

print("\n=== 3. Subárbol ===")
c = pdb._get_conn("S", None)
c.executemany("INSERT OR REPLACE INTO _globals (ns,subkey,value) VALUES (?,?,?)",
              [("S", encode_subkey(["X", i]), str(i)) for i in range(50)]
              + [("S", encode_subkey(["Y", i]), str(i)) for i in range(50)])
c.commit()
a = root_de_epoch(leer_ns_rango(pdb, "S", subs=["X"]))
b = root_stream_ns(pdb, "S", subs=["X"])
print(f"   50 hojas, n={a['n']}")
chk(a["root"] == b["root"], "subárbol: mismo root")
chk(a["n"] == 50, f"cuenta solo el subárbol (dio {a['n']})")

print("\n=== 4. Epoch vacío ===")
ev = root_stream_ns(pdb, "NSINNADIE")
print(f"   root: {ev['root'][:24]}… n={ev['n']}")
chk(ev["n"] == 0, "0 hojas")
chk(ev["root"] == root_de_epoch([])["root"], "mismo root que el epoch vacío clásico")

print("\n=== 5. MEMORIA: clásico vs streaming ===")
N = 200_000
if GRANDE:
    N = 1_000_000
print(f"   dataset: {N:,} claves")
c = pdb._get_conn("M", None)
c.execute("DELETE FROM _globals WHERE ns='M'")
c.commit()
llenar("M", N)

tracemalloc.start()
_r1 = root_de_epoch(leer_ns_rango(pdb, "M"))
pico_clasico = tracemalloc.get_traced_memory()[1]
tracemalloc.stop()

tracemalloc.start()
_r2 = root_stream_ns(pdb, "M")
pico_stream = tracemalloc.get_traced_memory()[1]
tracemalloc.stop()

print(f"   clásico   : {pico_clasico/1e6:7.1f} MB")
print(f"   streaming : {pico_stream/1e6:7.1f} MB")
ahorro = 100 * (1 - pico_stream / pico_clasico) if pico_clasico else 0
print(f"   ahorro    : {ahorro:.0f}%")
chk(_r1["root"] == _r2["root"], f"mismo root con {N:,} claves")
chk(pico_stream < pico_clasico * 0.5,
    f"streaming usa menos de la mitad de memoria ({pico_stream/1e6:.0f} vs {pico_clasico/1e6:.0f} MB)")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print(f"PASS: mismo root, memoria {ahorro:.0f}% menor")
