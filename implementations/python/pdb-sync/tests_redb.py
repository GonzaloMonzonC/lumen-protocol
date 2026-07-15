#!/usr/bin/env python3
"""Tests Fase 4: engine redb (crate lumen-pdb) vía FFI.

Compara semántica lado a lado con el motor SQLite sobre los mismos
datos, verifica el golden Python que consume Rust, y prueba el migrador
one-shot a través del FFI real.
"""
import json
import math
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: F401
from lumen_pdb import RedbPDB, SqlitePDB, connect, ensure_built, available
from pdb_tools import encode_subkey

p = f = 0
def t(n, o):
    global p, f
    if o: p += 1; print(f"  ✅ {n}")
    else: f += 1; print(f"  ❌ {n}")

print('🧪 TESTS REDB (Fase 4)\n')

if not ensure_built():
    print("  ❌ dylib no compilable (falta cargo) — engine redb no verificable")
    print("\n📊 0/1 tests passed")
    sys.exit(1)

tmp = tempfile.mkdtemp(prefix="lumen-redb-")
redb = RedbPDB(os.path.join(tmp, "t.redb"))

# ── 1. Golden binario Python (el mismo fichero compilado por tests Rust) ──
golden_path = os.path.join(
    _paths.REPO, "implementations", "rust", "lumen-pdb", "tests",
    "golden_subkey.json")
with open(golden_path, encoding="utf-8") as fh:
    golden = json.load(fh)
t("31 vectores encode_subkey Python", len(golden) == 31 and all(
    encode_subkey(case["subs"]).hex() == case["hex"] for case in golden))

# ── 2. Operaciones núcleo ──
redb.set("TEST", ["a"], "v1")
redb.set("TEST", ["a", "b"], {"k": 2})
redb.set("TEST", [3], "num")
redb.set("TEST", [-1.5], "neg")
t("set/get string", redb.get("TEST", ["a"]) == "v1")
t("set/get dict", redb.get("TEST", ["a", "b"]) == {"k": 2})
t("get default", redb.get("TEST", ["zz"], "dflt") == "dflt")
t("data 11", redb.data("TEST", ["a"]) == 11)
t("data 1", redb.data("TEST", [3]) == 1)
t("data 0", redb.data("TEST", ["zz"]) == 0)

# $ORDER: números primero (-1.5, 3), después strings (a)
t("order primero=-1.5", redb.order("TEST", [""]) == -1.5)
t("order tras -1.5 = 3", redb.order("TEST", [-1.5]) == 3.0)
t("order tras 3 = a", redb.order("TEST", [3]) == "a")
t("order tras a = None", redb.order("TEST", ["a"]) is None)
t("order reverso = a", redb.order("TEST", [""], direction=-1) == "a")
t("order subnivel", redb.order("TEST", ["a", ""]) == "b")

t("incr", redb.incr("CNT", ["n"], 5) == 5 and redb.incr("CNT", ["n"], 0.5) == 5.5)
t("merge subárbol", redb.merge("TEST", ["cp"], "TEST", ["a"]) == 2
  and redb.get("TEST", ["cp", "b"]) == {"k": 2})
killed = redb.kill("TEST", ["a"])
t("kill subárbol", killed == 2 and redb.data("TEST", ["a"]) == 0)
t("hermanos intactos tras kill", redb.get("TEST", [3]) == "num")

# ── 3. Paridad semántica redb vs SQLite sobre los mismos datos ──
sqlite_path = os.path.join(tmp, "parity.db")
sqlite_eng = SqlitePDB(sqlite_path)
DATA = [(["s1"], "x"), (["s1", "h1"], 1), (["s1", "h2"], 2), ([7], "siete"),
        (["ñ"], "eñe"), ([2.5, "mix"], [1, 2])]
for subs, val in DATA:
    redb.set("PAR", subs, val)
    sqlite_eng.set("PAR", subs, val)
ops_match = all(redb.get("PAR", s) == sqlite_eng.get("PAR", s) for s, _ in DATA)
t("paridad get", ops_match)
t("paridad data", all(redb.data("PAR", s) == sqlite_eng.data("PAR", s)
                      for s in [["s1"], [7], ["nada"]]))
# recorrido $ORDER completo idéntico
def walk(eng):
    out, cur = [], ""
    while True:
        cur = eng.order("PAR", [cur])
        if cur in (None, ""):
            return out
        out.append(cur)
walk_r, walk_s = walk(redb), walk(sqlite_eng)
# primer nivel: 2.5, 7, s1, ñ (h1/h2 son hijos de s1)
t("paridad recorrido $ORDER", walk_r == walk_s and len(walk_r) == 4)
for engine in (redb, sqlite_eng):
    engine.set("COLL", [-0.0], "negative zero")
    engine.set("COLL", [0.0], "positive zero")
    engine.set("COLL", ["ab"], "extension")
    engine.set("COLL", ["a"], "prefix")
    engine.set("COLL", [""], "empty")
next_zero_r = redb.order("COLL", [-0.0])
next_zero_s = sqlite_eng.order("COLL", [-0.0])
t("paridad $ORDER distingue -0.0 de +0.0",
  next_zero_r == next_zero_s == 0.0
  and math.copysign(1, next_zero_r) == math.copysign(1, next_zero_s) == 1)
t("paridad quirks prefijo y vacío",
  redb.order("COLL", ["ab"]) == sqlite_eng.order("COLL", ["ab"]) == "a"
  and redb.order("COLL", ["a"]) == sqlite_eng.order("COLL", ["a"]) == "")
t("paridad incr con delta", sqlite_eng.incr("CORE", ["n"], 5) == 5
  and sqlite_eng.incr("CORE", ["n"], 0.25) == 5.25)
sqlite_eng.set("CORE", ["src"], "root")
sqlite_eng.set("CORE", ["src", "child"], "leaf")
t("sqlite merge devuelve 2", sqlite_eng.merge(
    "CORE", ["dst"], "CORE", ["src"]) == 2
  and sqlite_eng.get("CORE", ["dst", "child"]) == "leaf")
t("sqlite kill devuelve borrados", sqlite_eng.kill("CORE", ["src"]) == 2
  and sqlite_eng.data("CORE", ["src"]) == 0)
sqlite_eng.set_raw("STRUCT", [
    (encode_subkey(["parent"]), None),
    (encode_subkey(["parent", "child"]), json.dumps("v").encode()),
])
t("sqlite NULL estructural conserva $DATA=10",
  sqlite_eng.get("STRUCT", ["parent"]) is None
  and sqlite_eng.data("STRUCT", ["parent"]) == 10)
t("SqlitePDB respeta path", os.path.samefile(sqlite_eng.path, sqlite_path))
sqlite_eng.close()

# ── 4. Infinitos (excluidos del golden JSON por no ser JSON válido) ──
redb.set("INF", [float("inf")], "pos")
redb.set("INF", [float("-inf")], "neg")
redb.set("INF", [0], "cero")
t("orden con ±inf", walk_inf := (redb.order("INF", [""]) == float("-inf")
  and redb.order("INF", [float("-inf")]) == 0.0
  and redb.order("INF", [0]) == float("inf")))

# ── 5. Migrador SQLite → redb ──
import sqlite3
mig_src = os.path.join(tmp, "src.db")
con = sqlite3.connect(mig_src)  # BD de fixture del test, exenta del contrato
con.execute("CREATE TABLE _globals (ns TEXT, subkey BLOB, value BLOB, PRIMARY KEY (ns, subkey))")
rows = [("M1", encode_subkey(["k", i]), json.dumps(f"v{i}").encode()) for i in range(500)]
rows += [("M2", encode_subkey([i]), json.dumps(i).encode()) for i in range(100)]
rows += [("M3", encode_subkey(["parent"]), None),
         ("M3", encode_subkey(["parent", "child"]), json.dumps("v").encode())]
con.executemany("INSERT INTO _globals VALUES (?,?,?)", rows)
con.commit(); con.close()

from pdb_migrate import migrate
os.environ["PDB_PATH"] = mig_src
mig_dst = os.path.join(tmp, "dst.redb")
rc = migrate(src=mig_src, dst=mig_dst, verify=True)
t("migración verificada rc=0", rc == 0)
t("migrador no mezcla destino existente",
  migrate(src=mig_src, dst=mig_dst, verify=False) == 1)
mig = RedbPDB(mig_dst)
t("counts migrados", mig.count("M1") == 500 and mig.count("M2") == 100)
t("valores migrados legibles", mig.get("M1", ["k", 7]) == "v7"
  and mig.get("M2", [42]) == 42)
t("NULL estructural conserva $DATA=10",
  mig.get("M3", ["parent"]) is None and mig.data("M3", ["parent"]) == 10)
t("$ORDER sobre datos migrados", mig.order("M2", [""]) == 0.0)
mig.close()

# ── 6. Flag PDB_ENGINE con fallback ──
os.environ["PDB_ENGINE"] = "redb"
e = connect(os.path.join(tmp, "flag.redb"))
t("PDB_ENGINE=redb", e.name == "redb")
e.close()
os.environ["PDB_ENGINE"] = "sqlite"
e2 = connect()
t("PDB_ENGINE=sqlite", e2.name == "sqlite")
e2.close()
try:
    connect(engine="typo")
    invalid_rejected = False
except ValueError:
    invalid_rejected = True
t("PDB_ENGINE inválido se rechaza", invalid_rejected)
os.environ.pop("PDB_ENGINE")

fallback_code = """
import os, sys
sys.path.insert(0, os.environ['PDB_MODULE_DIR'])
from lumen_pdb import connect
db = connect(os.environ['PDB_FALLBACK_DB'], engine='redb')
print(db.name)
db.close()
"""
fallback_env = os.environ.copy()
fallback_env["LUMEN_PDB_LIB"] = os.path.join(tmp, "missing-library.so")
fallback_env["PDB_MODULE_DIR"] = str(_paths.PDB_DIR)
fallback_env["PDB_FALLBACK_DB"] = os.path.join(tmp, "fallback.db")
fallback = subprocess.run([sys.executable, "-c", fallback_code],
                          env=fallback_env, capture_output=True, text=True)
t("redb no cargable hace fallback real a sqlite",
  fallback.returncode == 0 and fallback.stdout.strip() == "sqlite"
  and "fallback a sqlite" in fallback.stderr)

redb.close()
import shutil
shutil.rmtree(tmp, ignore_errors=True)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f == 0 else 1)
