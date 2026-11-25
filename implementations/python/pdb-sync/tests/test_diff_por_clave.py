# -*- coding: utf-8 -*-
"""PRUEBA de la hipotesis H1: los cambios de VALOR no se sincronizan.

No toca el edge ni la PDB real. Reproduce el algoritmo de push_full_diff
sobre dos SQLite en memoria y comprueba que pasa con un valor modificado.

Algoritmo real (copiado de pdb_sync_engine.push_full_diff, pasos 1-3):
    edge_keys = conjunto de claves del edge
    local_map = {clave: (subs, valor)} del local
    missing = set(local_map) - edge_keys
    -> se empuja solo 'missing'
"""
import sqlite3, sys, io

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def crear():
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE _globals (ns TEXT, subkey TEXT, value TEXT)")
    return con


def insertar(con, ns, subkey, value):
    con.execute("INSERT INTO _globals VALUES (?,?,?)", (ns, subkey, value))


def claves(con, ns):
    return {r[0] for r in con.execute(
        "SELECT subkey FROM _globals WHERE ns=?", (ns,)).fetchall()}


def valores(con, ns):
    return {r[0]: r[1] for r in con.execute(
        "SELECT subkey, value FROM _globals WHERE ns=?", (ns,)).fetchall()}


def sync_actual(local, edge, ns):
    """Reproduce EXACTAMENTE el algoritmo de push_full_diff."""
    edge_keys = claves(edge, ns)
    local_map = valores(local, ns)
    missing = sorted(set(local_map) - edge_keys)
    empujadas = []
    for k in missing:
        insertar(edge, ns, k, local_map[k])
        empujadas.append(k)
    return empujadas


NS = "demo"

print("=" * 74)
print("H1 — ¿se sincronizan los cambios de valor?")
print("=" * 74)

# ── CASO 1: clave nueva (deberia funcionar) ──
local, edge = crear(), crear()
insertar(local, NS, "k1", "original")
print("\nCASO 1 · clave nueva")
print("  antes: local={k1:original}  edge={} ")
emp = sync_actual(local, edge, NS)
print("  empujadas: %s" % emp)
print("  edge ahora: %s" % valores(edge, NS))
print("  -> %s" % ("OK, se propaga" if valores(edge, NS).get("k1") == "original"
                  else "FALLO"))

# ── CASO 2: valor MODIFICADO en local (la hipotesis) ──
local, edge = crear(), crear()
insertar(edge, NS, "k1", "original")      # el edge ya la tiene
insertar(local, NS, "k1", "MODIFICADO")   # en local se cambio el valor
print("\nCASO 2 · valor modificado en local  <<< LA HIPOTESIS")
print("  antes: local={k1:MODIFICADO}  edge={k1:original}")
emp = sync_actual(local, edge, NS)
print("  empujadas: %s" % (emp if emp else "(NINGUNA)"))
print("  edge despues: %s" % valores(edge, NS))
if valores(edge, NS).get("k1") == "MODIFICADO":
    print("  -> OK, se propaga")
else:
    print("  -> ** FALLO CONFIRMADO **: el cambio NO se propaga")
    print("     local dice 'MODIFICADO', edge sigue con '%s'" % valores(edge, NS).get("k1"))

# ── CASO 3: valor MODIFICADO en el edge ──
local, edge = crear(), crear()
insertar(local, NS, "k1", "original")
insertar(edge, NS, "k1", "MODIFICADO_EDGE")
print("\nCASO 3 · valor modificado en el edge")
emp = sync_actual(local, edge, NS)
print("  empujadas: %s" % (emp if emp else "(NINGUNA)"))
print("  local sigue: %s" % valores(local, NS))
print("  -> %s" % ("divergencia: nadie reconcilia"
                  if valores(local, NS).get("k1") != valores(edge, NS).get("k1")
                  else "convergen"))

# ── CASO 4: borrado en local ──
local, edge = crear(), crear()
insertar(local, NS, "k1", "v")
insertar(edge, NS, "k1", "v")
insertar(local, NS, "k2", "solo_local")
local.execute("DELETE FROM _globals WHERE ns=? AND subkey='k1'", (NS,))
print("\nCASO 4 · clave borrada en local (existia en los dos)")
emp = sync_actual(local, edge, NS)
print("  empujadas: %s" % (emp if emp else "(NINGUNA)"))
print("  edge conserva k1: %s" % ("k1" in valores(edge, NS)))
print("  -> %s" % ("FALLO: el borrado no se propaga, k1 sigue en el edge"
                  if "k1" in valores(edge, NS) else "OK, se propago"))

print()
print("=" * 74)
print("CONCLUSION")
print("=" * 74)
print("El algoritmo actual usa set(local) - set(edge): diferencia de CLAVES.")
print("Todo lo que exista en los dos lados es invisible al sync, tenga el valor")
print("que tenga. Los casos 2, 3 y 4 son los que pierden datos hoy.")
print("=" * 74)
