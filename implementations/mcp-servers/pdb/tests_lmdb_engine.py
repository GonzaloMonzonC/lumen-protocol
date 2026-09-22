#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tests_lmdb_engine.py — suite del motor LMDB de lumen_pdb (py-lmdb).

Requiere py-lmdb==2.3.0 (LMDB 0.9.35 — la MISMA que vendor/lmdb-master-sys
desde 22-sep-2026; versiones distintas de LMDB NO coexisten: MDB_VERSION_MISMATCH).

Cubre: contrato de 7 ops + set_raw/count/flush, ambas variantes de clave
(canónica del motor + legacy python), diferencial contra SqlitePDB con ops
aleatorias, multi-proceso real contra el binario mvm-nas (lectura cruzada +
invalidación de la caché de hijos por txn-id) y smoke sobre el store real.

Uso:  python tests_lmdb_engine.py
Env:  MVMNAS_BIN (default: ../mvm-nas/target/release/mvm-nas.exe) · opcional
"""
import json
import os
import random
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from lumen_pdb import LmdbPDB, SqlitePDB  # noqa: E402
from pdb_tools import encode_subkey  # noqa: E402

MVMNAS = os.environ.get(
    "MVMNAS_BIN",
    r"C:/Users/gonzalo/Documents/GitHub/mvm-nas/target/release/mvm-nas.exe")
REAL_STORE = os.environ.get(
    "REAL_STORE", r"C:/Users/gonzalo/pdb-data/lumen-pdb-test.lmdb")

FAILS = []


def check(name, cond, extra=""):
    tag = "✓" if cond else "✗"
    print("  %s %s%s" % (tag, name, "" if cond else "  → %r" % (extra,)))
    if not cond:
        FAILS.append(name)


def run_mvm(args, timeout=60):
    r = subprocess.run([MVMNAS] + args, capture_output=True, timeout=timeout)
    return (r.stdout + r.stderr).decode("utf-8", "replace")


def mvm_lines(out):
    skip = ("[", "·", "error")
    return [l.strip() for l in out.splitlines()
            if l.strip() and not l.strip().startswith(skip)]


def chain(e, ns, parent, limit=200):
    """Cadena completa de $O (forward) sobre el mismo contrato."""
    out, cur = [], ""
    while len(out) < limit:
        nxt = e.order(ns, list(parent) + [cur], 1)
        if nxt is None:
            break
        out.append(nxt)
        cur = nxt
    return out


def main():
    d = tempfile.mkdtemp(prefix="lmdb_engine_t_")

    # ── 1) contrato básico (store fresco) ──
    print("── 1) contrato básico ──")
    store = os.path.join(d, "base.lmdb")
    e = LmdbPDB(store)
    check("set/get str", e.set("T", ["a"], "hola") and e.get("T", ["a"]) == "hola")
    check("set/get num", e.set("T", ["n"], 7) and e.get("T", ["n"]) == 7)
    check("set/get dict", e.set("T", ["k", "x"], {"v": 1}) and e.get("T", ["k", "x"]) == {"v": 1})
    check("get default", e.get("T", ["nope"], default="D") == "D")
    check("data $D=1", e.data("T", ["a"]) == 1)
    check("data $D=0", e.data("T", ["zzz"]) == 0)
    e.set("T", ["a", "sub"], 1)
    check("data $D=11 (valor+hijo)", e.data("T", ["a"]) == 11)
    e.set("T", ["c", "d"], 1)
    check("data $D=10 (solo hijo)", e.data("T", ["c"]) == 10)
    check("incr 1ª vez", e.incr("T", ["cnt"], 2) == 2)
    check("incr 2ª vez", e.incr("T", ["cnt"], 3) == 5)
    e.set("T2", ["m"], "v")
    check("merge", e.merge("T3", ["z"], "T2", ["m"]) == 1 and e.get("T3", ["z"]) == "v")
    check("count", e.count("T2") == 1)
    nkill = e.kill("T", ["a"])
    check("kill nodo+subárbol (2 claves)", nkill == 2 and e.data("T", ["a"]) == 0, nkill)

    for s in ("b", "a", "c"):
        e.set("ORD", [s], 0)
    check("order fwd desde ''", chain(e, "ORD", []) == ["a", "b", "c"])
    check("order bwd desde ''", e.order("ORD", [""], -1) == "c")
    check("order bwd desde 'b'", e.order("ORD", ["b"], -1) == "a")
    check("order fwd desde 'b'", e.order("ORD", ["b"], 1) == "c")
    for v in (1, 2.5, "s"):
        e.set("ORD2", [v], 0)
    check("order mixto num/str", chain(e, "ORD2", []) == [1, 2.5, "s"],
          chain(e, "ORD2", []))
    # jerarquía con números no-finales (enc. distinta entre variantes)
    e.set("H", [1, "x"], "a")
    e.set("H", [1, "y"], "b")
    e.set("H", [2, "x"], "c")
    check("order hijos de [1]", chain(e, "H", [1]) == ["x", "y"])
    check("order hermanos nivel 0", chain(e, "H", []) == [1, 2])
    e.flush()
    e.close()
    e = LmdbPDB(store)
    check("persistencia (reabrir)", e.get("T", ["n"]) == 7)
    e.close()

    # ── 2) filas LEGACY (variante python/qpdb) ──
    print("── 2) variantes de clave (dominante qpdb + motor) ──")
    store2 = os.path.join(d, "legacy.lmdb")
    e = LmdbPDB(store2)
    num = -1.78832053943463e18
    sk_tools = encode_subkey([num, "SET", "X"])   # sortable + FF por sub (qpdb)
    sk_motor = (b"\x01" + struct.pack(">d", num) + b"\x02SET\xff"
                + b"\x02X\xff" + b"\xff")          # número crudo + FF final (rust)
    e.set_raw("CH", [(sk_tools, b"v-tools")])
    check("get fila dominante (qpdb)", e.get("CH", [num, "SET", "X"]) == "v-tools")
    check("data fila dominante", e.data("CH", [num, "SET", "X"]) == 1)
    check("data padre dominante", e.data("CH", [num]) == 10)
    check("order sobre dominante", e.order("CH", [num, ""], 1) == "SET")
    check("kill dominante", e.kill("CH", [num]) == 1 and e.data("CH", [num]) == 0)
    e.set_raw("CM", [(sk_motor, b"v-motor")])
    check("get fila del MOTOR (raw+FF)", e.get("CM", [num, "SET", "X"]) == "v-motor")
    check("kill fila del MOTOR", e.kill("CM", [num]) == 1)
    # set()/incr() sobre fila única: se sincroniza la gemela
    e.set_raw("SY", [(encode_subkey(["g"]), b'"5"')])
    check("incr sobre fila única", e.incr("SY", ["g"], 2) == 7)
    check("get tras sync", e.get("SY", ["g"]) == 7)
    e.close()

    # ── 3) diferencial LmdbPDB vs SqlitePDB ──
    print("── 3) diferencial vs SqlitePDB (300 ops aleatorias) ──")
    random.seed(42)
    eL = LmdbPDB(os.path.join(d, "d.lmdb"))
    eS = SqlitePDB(os.path.join(d, "d.db"))
    L1 = [1, 2.5, "a", "b", "meta"]
    L2 = [1, 2, "x", "y"]
    L3 = ["f", 3]

    def rnd_subs():
        k = random.randint(1, 3)
        parts = [random.choice(L1)]
        if k >= 2:
            parts.append(random.choice(L2))
        if k >= 3:
            parts.append(random.choice(L3))
        return parts

    numeric = set()
    for i in range(300):
        op = random.random()
        subs = rnd_subs()
        ksub = tuple(subs)
        if op < 0.60:
            v = random.choice(["hola", i, 3.14, {"x": i}, "meta-ok"])
            eL.set("D", subs, v)
            eS.set("D", subs, v)
            if isinstance(v, (int, float)):
                numeric.add(ksub)
            else:
                numeric.discard(ksub)
        elif op < 0.75 and ksub in numeric:
            inc = random.choice([1, 2.5])
            eL.incr("D", subs, inc)
            eS.incr("D", subs, inc)
        else:
            eL.kill("D", subs)
            eS.kill("D", subs)
            numeric.discard(ksub)
    mm = 0
    probes = []
    for a in L1:
        probes += [[a], []]
        for b in L2:
            probes += [[a, b]]
            for c in L3:
                probes += [[a, b, c]]
    for subs in probes:
        if eL.get("D", subs) != eS.get("D", subs):
            mm += 1
        if eL.data("D", subs) != eS.data("D", subs):
            mm += 1
    check("estado tras 300 ops idéntico (get/data)", mm == 0, "%d mismatches" % mm)
    chain_mm = 0
    for parent in ([], [1], [2.5], ["a"], ["b"], ["meta"], [1, "x"], [1, 2]):
        cL = chain(eL, "D", parent, 300)
        cS = chain(eS, "D", parent, 300)
        if cL != cS:
            chain_mm += 1
    check("cadenas $O idénticas", chain_mm == 0, chain_mm)
    eL.close()
    eS.close()

    # ── 4) multi-proceso real contra el motor (mvm-nas) ──
    print("── 4) cross-proceso con el MOTOR ──")
    if Path(MVMNAS).exists():
        store4 = os.path.join(d, "eng.lmdb")
        eE = LmdbPDB(store4)
        eE.set("XP", ["hola"], "desde-python")
        c1 = chain(eE, "XP", [])          # puebla la caché de hijos
        out = run_mvm(["-p", store4, "-e", 'W $G(^XP("hola")),!'])
        check("el MOTOR lee lo de Python", "desde-python" in out, out[:120])
        # el motor escribe un hijo NUEVO → la caché (txn-id) debe invalidarse
        run_mvm(["-p", store4, "-e", 'S ^XP("aaa")="x"'])
        c2 = chain(eE, "XP", [])
        check("caché de hijos invalidada cross-proceso", "aaa" in c2, c2)
        # el motor escribe un valor → Python lo ve al instante
        run_mvm(["-p", store4, "-e", 'S ^XP("engine")="desde-motor"'])
        check("Python lee al motor", eE.get("XP", ["engine"]) == "desde-motor")
        out2 = run_mvm(["-p", store4, "-e", 'W $O(^XP("")),!'])
        check("el MOTOR $O ve los hijos", ("aaa" in out2) or ("engine" in out2), out2[:120])
        eE.close()
    else:
        print("  (mvm-nas no encontrado — se omite; set MVMNAS_BIN)")

    # ── 5) smoke sobre el store REAL (si existe) ──
    print("── 5) store real (smoke) ──")
    if os.path.isdir(REAL_STORE):
        t0 = time.time()
        er = LmdbPDB(REAL_STORE)
        t_open = (time.time() - t0) * 1000
        n = er.count("CHANGES")
        check("CHANGES filas == 103631", n == 103631, n)
        first = er.order("CHANGES", [""], 1)
        t0 = time.time()
        ch = chain(er, "CHANGES", [], 500)
        t_chain = (time.time() - t0) * 1000
        check("cadena 500 pasos < 3 s", len(ch) == 500 and t_chain < 3000,
              "%d pasos en %.0f ms" % (len(ch), t_chain))
        if Path(MVMNAS).exists():
            # El motor lee estos números en su convención CRUDA y el adapter en la
            # SORTABLE (qpdb): el CONJUNTO de hijos coincide pero el ORDEN puede
            # quedar invertido (subkey-encodings §5). Verificamos que los dos
            # primeros hijos del motor PERTENECEN a nuestro conjunto completo.
            out1 = run_mvm(["-p", REAL_STORE, "-e", 'W $O(^CHANGES("")),!'])
            out2 = run_mvm(["-p", REAL_STORE, "-e", 'W $O(^CHANGES($O(^CHANGES("")))),!'])
            l1, l2 = mvm_lines(out1), mvm_lines(out2)
            kids = er._children("CHANGES", [])
            mags = {abs(float(k)) for k in kids if isinstance(k, (int, float))}
            ok = bool(l1) and all(
                abs(float(l)) in mags for l in (l1[:1] + l2[:1]) if l)
            check("mismo conjunto de hijos que el motor (set)", ok,
                  (l1[:1], l2[:1], len(mags)))
        print("  (open %.1f ms · chain %.0f ms)" % (t_open, t_chain))
        er.close()
    else:
        print("  (store real no encontrado — se omite)")

    print()
    if FAILS:
        print("❌ %d FALLOS: %s" % (len(FAILS), ", ".join(FAILS)))
        return 1
    print("✅ TODO OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
