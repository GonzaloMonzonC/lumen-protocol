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
PKG_JS = os.path.join(_MVM, "pkg", "lumen_mlight.js")


def _pkg_construido() -> str | None:
    """Comprueba que el paquete wasm existe ANTES de comparar nada.

    Sin esto, cada caso acaba en ERR_MODULE_NOT_FOUND y el test lo cuenta como
    "digest distinto": reporta 11 divergencias de determinismo cuando el
    problema real es que no se construyó `pkg/`. Un falso rojo que asusta y
    desinforma (el mensaje llegaba a decir "WASM y nativo NO son
    intercambiables", que es falso).

    Devuelve None si está todo, o el motivo si falta algo.
    """
    if not os.path.exists(WASM_SCRIPT):
        return f"falta {os.path.basename(WASM_SCRIPT)}"
    if not os.path.exists(PKG_JS):
        return ("pkg/ no construido (falta pkg/lumen_mlight.js). "
                "Ejecuta: bash scripts/build_wasm.sh")
    return None


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

    # Antes de comparar: ¿está el paquete wasm? Sin esto se reportan 11
    # "divergencias de determinismo" que en realidad son un módulo ausente.
    falta = _pkg_construido()
    if falta:
        print(f"NO EJECUTABLE: {falta}")
        print("Esto NO es una divergencia de determinismo: falta el artefacto.")
        sys.exit(2)

    print(f"{'caso':<20} {'nativo':<18} {'wasm':<18} {'globals':<9} veredicto")
    print("-" * 78)

    fallos = []
    errores = []
    for nombre, prog in CASOS:
        dn, nn = nativo(prog)
        dw, nw, err = wasm(prog)
        if err:
            print(f"{nombre:<20} {dn[:16]:<18} {'ERROR':<18} {'-':<9} {err[:30]}")
            # ERROR de ejecución != digest distinto: se separan para que el
            # mensaje final diga la verdad (antes ambos contaban como divergir)
            errores.append(nombre)
            continue
        igual = dn == dw
        ng = f"{nn}/{nw}"
        print(f"{nombre:<20} {dn[:16]:<18} {dw[:16]:<18} {ng:<9} {'IGUAL' if igual else 'DIVERGE'}")
        if not igual:
            fallos.append(nombre)

    print()
    if errores:
        print(f"ERROR DE EJECUCIÓN en {len(errores)} caso(s): {', '.join(errores)}")
        print("       No es un problema de determinismo: el wasm no llegó a ejecutar.")
        print("       Revisa que pkg/ esté al día para el wasm compilado.")
    if fallos:
        print(f"FALLO: {len(fallos)} caso(s) con digest DISTINTO -> {', '.join(fallos)}")
        print("       WASM y nativo NO son intercambiables en esos casos.")
    if errores or fallos:
        sys.exit(1)
    print(f"PASS: {len(CASOS)} casos, WASM y nativo dan el MISMO digest")
    print("      -> 'un solo codigo cliente y servidor' se sostiene en estos casos")


if __name__ == "__main__":
    main()
