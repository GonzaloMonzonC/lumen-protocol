#!/usr/bin/env python3
"""test_wasm_vs_nativo.py — determinismo cruzado WASM <-> nativo.

El doc `01` §4 del estudio de juego afirma: "un solo código de simulación para
cliente y servidor. Nada de reimplementar reglas en C# o TS". Eso solo vale si
WASM y nativo dan EL MISMO resultado. Nadie lo había comprobado.

Este test ejecuta el mismo programa en los dos motores y compara el digest
canónico (digest_canonico.py v1, replicado en wasm_digest.mjs).

Uso: LUMEN_REPO=~/Documents/GitHub/lumen-protocol python test_wasm_vs_nativo.py
"""
import json
import os
import subprocess
import sys

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_PDB = os.path.join(_REPO, "implementations", "mcp-servers", "pdb")
_MVM = os.path.join(_REPO, "implementations", "rust", "lumen-m-light")
for p in (_PDB,):
    if not os.path.isdir(p):
        sys.exit(f"No encuentro {p} (define LUMEN_REPO)")
sys.path.insert(0, _PDB)

import lumen_mlight as L  # noqa: E402
from digest_canonico import digest_de_globals  # noqa: E402

WASM_SCRIPT = os.path.join(_MVM, "wasm_digest.mjs")


def nativo(prog):
    r = L.execute(prog, gas_limit=2_000_000_000)
    return digest_de_globals(r.get("globals")), len(r.get("globals") or [])


def wasm(prog):
    p = subprocess.run(
        ["node", WASM_SCRIPT, prog],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120,
    )
    out = (p.stdout or "").strip().splitlines()
    if not out:
        return None, 0, f"sin salida (stderr: {(p.stderr or '')[:150]})"
    try:
        d = json.loads(out[-1])
    except Exception as e:
        return None, 0, f"salida no JSON: {out[-1][:150]} ({e})"
    if not d.get("ok"):
        return None, d.get("n_globals", 0), d.get("error")
    return d.get("digest"), d.get("n_globals", 0), None


CASOS = [
    ("entero",            "S ^A(1)=1"),
    ("string",            "S ^N(1)=\"hola\""),
    ("decimal exacto",    "S ^F=0.5"),
    ("division 1/3",      "S ^F=1/3"),
    ("0.1+0.2 (ULP)",     "S ^F=0.1+0.2"),
    ("negativo",          "S ^F=-42"),
    ("bucle + ramas",     "S i=0\nF  S i=i+1 Q:i>5  D\n. S ^P(i)=i*2"),
    ("anidado",           "S ^T(1,2,3)=\"x\"\nS ^T(1,2,4)=\"y\""),
    ("varios ns",         "S ^A=1\nS ^B=2\nS ^C(9)=\"z\""),
    ("sobrescritura",     "S ^X=1\nS ^X=2\nS ^X=3"),
    ("string largo",      "S ^S=\"linea1\"_\"linea2\"_\"linea3\""),
]


def main():
    print(f"repo: {_REPO}\n")
    print(f"{'caso':<20} {'nativo':<18} {'wasm':<18} {'globals':<9} veredicto")
    print("-" * 78)

    fallos = []
    for nombre, prog in CASOS:
        dn, nn = nativo(prog)
        dw, nw, err = wasm(prog)
        if err:
            print(f"{nombre:<20} {dn[:16]:<18} {'ERROR':<18} {'-':<9} {err[:30]}")
            fallos.append(nombre)
            continue
        igual = dn == dw
        ng = f"{nn}/{nw}"
        print(f"{nombre:<20} {dn[:16]:<18} {dw[:16]:<18} {ng:<9} {'IGUAL' if igual else 'DIVERGE'}")
        if not igual:
            fallos.append(nombre)

    print()
    if fallos:
        print(f"FALLO: {len(fallos)} caso(s) divergen -> {', '.join(fallos)}")
        print("       WASM y nativo NO son intercambiables en esos casos.")
        sys.exit(1)
    print(f"PASS: {len(CASOS)} casos, WASM y nativo dan el MISMO digest")
    print("      -> 'un solo codigo cliente y servidor' se sostiene en estos casos")


if __name__ == "__main__":
    main()
