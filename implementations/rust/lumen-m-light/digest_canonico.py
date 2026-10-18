#!/usr/bin/env python3
"""digest_canonico.py — proyección canónica del estado para replay verificable.

PROBLEMA QUE RESUELVE
---------------------
El `state` que devuelve la MVM incluye `zh_start` (timestamp de arranque) y
`rng_state`. Por eso dos ejecuciones del MISMO programa dan digests distintos:

    run 1: 4813ed05e30419e6   zh_start=1792304652.0856464
    run 2: 5bbde3602b6452a1   zh_start=1792304652.0861535

El `program_hash` sí es estable, pero es el hash del CÓDIGO, no del estado.

Un certificado de replay necesita un digest del ESTADO que sea:
  1. estable entre ejecuciones y entre máquinas
  2. insensible a lo que no es resultado (reloj, RNG interno, PIDs, rutas)
  3. sensible a lo que sí es resultado (globals, valores, forma del árbol)
  4. insensible a floats frágiles (1/3 -> 0.3333333333333333)

LA PROYECCIÓN
-------------
Se hashea SOLO esto, en orden canónico:

    ns + subkeys + valor(canónico)

- ns y subkeys: tal cual, ordenados (la VM ya los devuelve ordenados).
- valor: normalizado a una forma estable:
    * números -> repr con 12 cifras significativas (evita el ULP)
    * strings -> tal cual
    * None    -> marcador explícito
- se EXCLUYE: zh_start, rng_state, fibers, ip, stack, pids, timestamps

Uso:
    from digest_canonico import digest_de_globals, digest_de_ejecucion
    digest_de_globals(r["globals"])       # solo estado
    digest_de_ejecucion(programa, r)      # estado + hash del programa
"""
from __future__ import annotations

import hashlib
import json

VERSION = "1"   # cambia si cambia la proyección: invalida certificados viejos

# Cuántas cifras significativas para números en el digest.
# 12 es de sobra para lógica de negocio y absorbe el ruido de coma flotante
# (1/3 -> 0.333333333333). Si algún día se necesita exactitud decimal real,
# esto tiene que ser Decimal, no float.
SIG_DIGITS = 12


def _num(v: float) -> str:
    """Representación canónica de un número.

    '%g' con 12 cifras: colapsa 0.1+0.2 y 0.30000000000000004 al mismo string,
    y deja 1/3 como '0.333333333333'. Es la pieza que evita que un ULP rompa
    un certificado.

    Casos especiales: inf/-inf/nan no deberían aparecer en estado de negocio,
    pero si aparecen tienen que ser distinguibles entre sí.
    """
    if v != v:                      # nan
        return "nan"
    if v == float("inf"):
        return "inf"
    if v == float("-inf"):
        return "-inf"
    # -0.0 y 0.0 deben ser el mismo valor en el digest
    if v == 0:
        return "0"
    if v == int(v) and abs(v) < 1e15:
        return str(int(v))          # 3.0 -> "3"
    return format(v, f".{SIG_DIGITS}g")


def _valor(v) -> str:
    """Normaliza un valor de global a string canónico."""
    if v is None:
        return "\x00none"           # marcador que no puede colisionar con un string
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return _num(float(v))
    if isinstance(v, str):
        return v
    # listas/dicts (no deberían salir de la MVM, pero por si acaso)
    return json.dumps(v, sort_keys=True, ensure_ascii=False, default=str)


def _subs(subs) -> str:
    """Subkeys a string canónico. '1' y '1.0' son la MISMA clave."""
    if subs is None:
        return ""
    return "|".join(_num(float(s)) if isinstance(s, (int, float)) else str(s) for s in subs)


def proyeccion(globals_: list[dict]) -> list[str]:
    """Líneas canónicas del estado. Esta es la verdad del replay."""
    lineas = []
    for g in globals_ or []:
        ns = g.get("ns", "")
        subs = _subs(g.get("subs"))
        val = _valor(g.get("value"))
        lineas.append(f"{ns}\x1f{subs}\x1f{val}")
    # orden estable: por ns y luego por subs (la VM ya ordena, pero no confiamos)
    lineas.sort()
    return lineas


def digest_de_globals(globals_: list[dict]) -> str:
    """Digest del ESTADO. Estable entre ejecuciones y máquinas."""
    h = hashlib.sha256()
    h.update(f"v{VERSION}\x1e".encode())
    for linea in proyeccion(globals_):
        h.update(linea.encode("utf-8"))
        h.update(b"\x1e")
    return h.hexdigest()


def digest_de_ejecucion(programa: str, resultado: dict) -> str:
    """Digest de (programa + estado resultante). Lo que va en un certificado.

    Incluye el hash del programa porque dos programas distintos pueden acabar
    en el mismo estado, y eso es información distinta.
    """
    st = resultado.get("state") or {}
    prog_hash = st.get("program_hash") or ""
    h = hashlib.sha256()
    h.update(f"v{VERSION}\x1e".encode())
    h.update(b"prog\x1f")
    h.update(prog_hash.encode())
    h.update(b"\x1eestado\x1f")
    h.update(digest_de_globals(resultado.get("globals")).encode())
    return h.hexdigest()


def diff_estados(a: list[dict], b: list[dict]) -> dict:
    """Qué cambió entre dos estados, línea a línea.

    Para el 'diff de políticas' del doc 15: cambiar una regla y ver QUÉ
    decisiones habrían cambiado, no solo que el digest difiere.
    """
    pa, pb = set(proyeccion(a)), set(proyeccion(b))
    solo_a = sorted(pa - pb)
    solo_b = sorted(pb - pa)
    return {
        "solo_en_a": solo_a,
        "solo_en_b": solo_b,
        "n_cambios": len(solo_a) + len(solo_b),
        "iguales": pa == pb,
    }
