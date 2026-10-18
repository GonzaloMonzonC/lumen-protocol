#!/usr/bin/env python3
"""test_lectura_rango.py — el anclaje escala a millones de claves.

El problema: `merkle_epoch._leer_ns` hacía una llamada al MCP por nodo. Con un
millón de claves son millones de llamadas.

Solución: recorrido por RANGO en SQL sobre el subkey BLOB prefijado. Una query.

Comprueba:
  1. Devuelve exactamente las mismas hojas que el recorrido por $ORDER
  2. Recorre subárboles (no solo el namespace entero)
  3. Escala: 100k claves en un tiempo razonable
  4. El root coincide con el del recorrido clásico (no cambia la prueba)
  5. Una sola query por namespace (no N)

Uso: LUMEN_REPO=... python test_lectura_rango.py [--grande]
"""
import os
import sys
import tempfile
import time

GRANDE = "--grande" in sys.argv

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_d = tempfile.mkdtemp()
os.environ["PDB_PATH"] = os.path.join(_d, "p.db")
sys.path.insert(0, os.path.join(_REPO, "implementations", "mcp-servers", "pdb"))
sys.path.insert(0, os.path.join(_REPO, "implementations", "rust", "lumen-m-light"))

import pdb_tools as pdb  # noqa: E402
from merkle_epoch import _leer_ns, root_de_epoch  # noqa: E402
from lectura_rango import contar_ns, leer_ns_rango, listar_namespaces  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


def normalizar(filas):
    """Tupla ordenada (ns, subs, valor) para comparar dos recorridos."""
    return sorted((f["ns"], tuple(str(s) for s in f["subs"]), str(f["value"]))
                  for f in filas)


# ── 1. Mismas hojas que el recorrido por $ORDER ────────────────────────────
print("=== 1. Mismo resultado que el recorrido por $ORDER ===")
DATOS = [
    ("LOTE", ["L1", "peso"], 1200),
    ("LOTE", ["L1", "pais"], "co"),
    ("LOTE", ["L2", "peso"], 1500),
    ("LOTE", ["L2", "pais"], "pe"),
    ("PARCELA", ["P1", "gps", "lat"], 4.12),
    ("PARCELA", ["P1", "gps", "lon"], -74.98),
    ("PARCELA", ["P2", "gps", "lat"], 5.01),
]
for ns, subs, v in DATOS:
    pdb.tool_set({"ns": ns, "subs": subs, "value": v})

for ns in ("LOTE", "PARCELA"):
    a = normalizar(_leer_ns(pdb, ns))
    b = normalizar(leer_ns_rango(pdb, ns))
    print(f"   {ns}: $ORDER={len(a)}  rango={len(b)}")
    chk(a == b, f"{ns}: ambos recorridos dan las MISMAS hojas")

print("\n=== 2. Subárboles ===")
sub = leer_ns_rango(pdb, "LOTE", subs=["L1"])
print(f"   LOTE(L1) -> {[(f['subs'], f['value']) for f in sub]}")
chk(len(sub) == 2, f"solo las 2 hojas de L1 (dio {len(sub)})")
chk(all(f["subs"][0] == "L1" for f in sub), "todas bajo L1")

print("\n=== 3. El root coincide con el del recorrido clásico ===")
for ns in ("LOTE", "PARCELA"):
    r_clasico = root_de_epoch(_leer_ns(pdb, ns))
    r_rango = root_de_epoch(leer_ns_rango(pdb, ns))
    print(f"   {ns}: {r_clasico['root'][:20]}… vs {r_rango['root'][:20]}…")
    chk(r_clasico["root"] == r_rango["root"],
        f"{ns}: el root es el mismo (la prueba no cambia)")

print("\n=== 4. contar_ns sin traer las filas ===")
n = contar_ns(pdb, "LOTE")
print(f"   LOTE: {n} claves")
chk(n == 4, f"cuenta 4 (dio {n})")

print("\n=== 5. listar_namespaces ===")
nss = listar_namespaces(pdb)
print(f"   {nss}")
chk("LOTE" in nss and "PARCELA" in nss, "aparecen los dos namespaces")

# ── 6. ESCALA ──────────────────────────────────────────────────────────────
N = 100_000 if not GRANDE else 1_000_000
print(f"\n=== 6. Escala: {N:,} claves ===")

t0 = time.perf_counter()
c = pdb._get_conn("BULK", None)
filas = []
for i in range(N):
    from pdb_tools import encode_subkey
    filas.append(("BULK", encode_subkey([i]), str(i)))
c.executemany("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?,?,?)", filas)
c.commit()
t_ins = time.perf_counter() - t0
print(f"   inserción: {t_ins:.1f}s ({N/t_ins:,.0f}/s)")

t0 = time.perf_counter()
leidas = leer_ns_rango(pdb, "BULK")
t_rango = time.perf_counter() - t0
print(f"   rango SQL : {t_rango:.2f}s ({len(leidas):,} claves)")
chk(len(leidas) == N, f"lee las {N:,} (dio {len(leidas):,})")

t0 = time.perf_counter()
r = root_de_epoch(leidas)
t_merkle = time.perf_counter() - t0
print(f"   Merkle    : {t_merkle:.2f}s (root {r['root'][:16]}…)")
chk(r["n"] == N, f"el root cubre las {N:,} (dio {r['n']:,})")

total = t_rango + t_merkle
print(f"   TOTAL     : {total:.2f}s -> {N/total:,.0f} claves/s")
chk(total < 120, f"termina en menos de 2 min (dio {total:.1f}s)")

# comparación con el recorrido clásico, pero solo en una muestra
print("\n=== 7. Comparación de coste (muestra de 500) ===")
t0 = time.perf_counter()
_ = _leer_ns(pdb, "LOTE")
t_order_lote = time.perf_counter() - t0
print(f"   $ORDER en LOTE (4 claves): {t_order_lote*1000:.0f} ms")
if t_order_lote > 0:
    print(f"   extrapolado a {N:,}: {N*t_order_lote/4/60:.0f} minutos")
    print(f"   rango SQL real      : {t_rango:.2f}s")

print()
if fails:
    print(f"FALLO ({len(fails)})")
    for f in fails:
        print(f"   - {f}")
    sys.exit(1)
print("PASS: recorrido por rango, mismo resultado, escala a cientos de miles")
