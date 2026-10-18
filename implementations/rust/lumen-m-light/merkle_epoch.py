#!/usr/bin/env python3
"""merkle_epoch.py — anclaje de la PDB: Merkle root por epoch + prueba de inclusión.

LA OTRA MITAD DE LA PRIMITIVA
-----------------------------
`digest_canonico.py` prueba UNA ejecución ("esta decisión se tomó así").
Esto prueba UN CONJUNTO EN UN MOMENTO ("este dato existía el día 14").

Con las dos, un tercero verifica sin confiar en nadie:

    digest canónico → "esta decisión se tomó así"      (doc 15)
    Merkle root     → "este dato existía el día 14"    (doc 10)

Y sin la segunda, el expediente de Origen (doc 06) no se puede auditar.

POR QUÉ USA LA MISMA PROYECCIÓN CANÓNICA
----------------------------------------
El doc 10 avisa: *"hace falta un formato canónico — la misma lección de las
subkeys"*. Si dos nodos ordenan o normalizan distinto, calculan roots distintos
para los mismos datos y el anclaje no vale para nada.

Aquí se reutiliza `proyeccion()` de `digest_canonico.py`: misma normalización
de números (12 cifras), mismo orden, mismos marcadores. Un registro tiene
exactamente la misma representación en un digest de estado y en un Merkle root.

ESTRUCTURA
----------
    hoja_i  = sha256( linea_canonica_i )
    nodo    = sha256( min(a,b) + max(a,b) )      <- orden fijado, no posicional
    root    = raíz del árbol

El orden `min/max` hace el árbol **independiente del orden de las hojas**: dos
nodos que tienen los mismos datos en distinto orden dan el mismo root. Eso es
lo que permite verificar sin acordar el orden de inserción.

USO
---
    from merkle_epoch import root_de_epoch, prueba_de_inclusion, verificar_inclusion

    e = root_de_epoch(globals_)          # {"root": ..., "n": ..., "hojas": {...}}
    prueba = prueba_de_inclusion(e, "P\\x1f1\\x1f5000")
    verificar_inclusion(prueba, e["root"])   # True/False, sin la PDB
"""
from __future__ import annotations

import hashlib
from typing import Iterable

from digest_canonico import proyeccion

VERSION = "1"


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def hash_hoja(linea_canonica: str) -> bytes:
    """Hash de una hoja. Incluye versión para invalidar árboles viejos a propósito."""
    return _h(f"v{VERSION}\x1ehoja\x1f{linea_canonica}".encode("utf-8"))


def _hash_par(a: bytes, b: bytes) -> bytes:
    """Hash de dos nodos, con orden fijado (min/max) para no depender del orden."""
    if a > b:
        a, b = b, a
    return _h(f"v{VERSION}\x1enodo\x1f".encode() + a + b)


def root_de_epoch(globals_: Iterable[dict]) -> dict:
    """Calcula el Merkle root de un conjunto de globals.

    Devuelve:
      root  -> hex del root
      n     -> número de hojas
      hojas -> dict linea_canonica -> hex de la hoja (para pruebas de inclusión)
      alto  -> altura del árbol

    Un conjunto vacío tiene root definido (sha256 del marcador vacío), no None:
    un epoch sin datos también necesita prueba de que estaba vacío.
    """
    lineas = sorted(proyeccion(globals_))     # orden canónico
    if not lineas:
        return {
            "root": _h(f"v{VERSION}\x1eepoch_vacio".encode()).hex(),
            "n": 0,
            "hojas": {},
            "alto": 0,
        }

    hojas = {linea: hash_hoja(linea) for linea in lineas}
    nivel = [hojas[l] for l in lineas]
    alto = 0

    while len(nivel) > 1:
        siguiente = []
        for i in range(0, len(nivel), 2):
            if i + 1 < len(nivel):
                siguiente.append(_hash_par(nivel[i], nivel[i + 1]))
            else:
                # hoja impar: se sube tal cual (no se duplica, que sería
                # vulnerable a la segunda preimagen)
                siguiente.append(nivel[i])
        nivel = siguiente
        alto += 1

    return {"root": nivel[0].hex(), "n": len(lineas), "hojas":
            {l: h.hex() for l, h in hojas.items()}, "alto": alto}


def prueba_de_inclusion(epoch: dict, linea_canonica: str) -> dict | None:
    """Prueba de que una línea concreta está en el árbol.

    Devuelve {"linea", "hoja", "hermanas": [hex...], "root"} o None si la línea
    no está. Las "hermanas" son el camino de abajo arriba, en el orden en que se
    combinan; con el flag `izquierda` de cada paso se puede recalcular el root
    sin el árbol completo.
    """
    hojas = epoch.get("hojas") or {}
    if linea_canonica not in hojas:
        return None

    # OJO: `hojas` viene en HEX (para serializar). Aquí se trabaja en bytes.
    lineas = sorted(hojas.keys())
    nivel = [bytes.fromhex(hojas[l]) for l in lineas]
    idx = lineas.index(linea_canonica)
    camino = []

    while len(nivel) > 1:
        es_izquierda = (idx % 2 == 0)
        if es_izquierda:
            hermana = nivel[idx + 1] if idx + 1 < len(nivel) else None
        else:
            hermana = nivel[idx - 1]
        camino.append({
            "hermana": hermana.hex() if hermana else None,
            "es_izquierda": es_izquierda,
        })
        # siguiente nivel
        siguiente = []
        for i in range(0, len(nivel), 2):
            if i + 1 < len(nivel):
                siguiente.append(_hash_par(nivel[i], nivel[i + 1]))
            else:
                siguiente.append(nivel[i])
        nivel = siguiente
        idx //= 2

    return {
        "linea": linea_canonica,
        "hoja": hojas[linea_canonica],
        "camino": camino,
        "root": epoch["root"],
        "n": epoch["n"],
        "version": VERSION,
    }


def verificar_inclusion(prueba: dict, root_esperado: str | None = None) -> bool:
    """Verifica una prueba de inclusión SIN tener la PDB ni el árbol.

    Solo necesita la prueba y (opcionalmente) el root que se publicó.
    """
    if not prueba:
        return False
    root = root_esperado or prueba.get("root")
    if not root:
        return False
    if (prueba.get("version") or VERSION) != VERSION:
        return False

    actual = bytes.fromhex(prueba["hoja"])
    for paso in prueba["camino"]:
        hermana = paso.get("hermana")
        if hermana is None:
            # era la hoja impar sola: sube sin combinar
            continue
        h = bytes.fromhex(hermana)
        actual = _hash_par(actual, h)

    return actual.hex() == root


def epoch_de_pdb(pdb, ns: str | None = None) -> dict:
    """Calcula el epoch de una PDB real (o de un namespace concreto).

    Usa el recorrido por RANGO en SQL (una query por namespace) en vez del
    recorrido por `$ORDER` (una llamada al MCP por nodo). El de $ORDER sigue en
    `_leer_ns` como referencia y para PDBs raras (particionadas sin SQL directo).
    """
    try:
        from lectura_rango import leer_ns_rango, listar_namespaces
        nombres = [ns] if ns else listar_namespaces(pdb)
        globs = []
        for n in nombres or []:
            globs.extend(leer_ns_rango(pdb, n))
        return root_de_epoch(globs)
    except Exception:
        # fallback: recorrido clásico
        pass

    globs = []
    ns_list = [ns] if ns else None
    if ns_list is None:
        try:
            r = pdb.tool_ns_list({}) if hasattr(pdb, "tool_ns_list") else {}
            ns_list = r.get("namespaces") or r.get("value") or []
        except Exception:
            ns_list = []
    for n in ns_list or []:
        filas = _leer_ns(pdb, n)
        globs.extend(filas)
    return root_de_epoch(globs)


def _leer_ns(pdb, ns: str) -> list[dict]:
    """Lee un namespace ENTERO: baja hasta las hojas, no solo el primer nivel.

    `tool_order` opera por NIVEL: con subs=[''] da la primera clave de la raiz;
    con subs=['L1',''] da la primera hija de L1. Hay que recorrer el arbol en
    profundidad para llegar a los valores.

    Dos trampas encontradas:
      - subs=[] da 'Need at least one subscript for $ORDER' -> usar ['']
      - iterar solo la raiz devuelve los nodos intermedios (value=None), no las
        hojas. Un Merkle root sobre eso no cubre los datos reales.
    """
    salida = []
    # pila de prefijos a explorar; se empieza por la raiz
    pila = [[]]
    visitados = 0
    LIMITE = 500_000

    while pila and visitados < LIMITE:
        prefijo = pila.pop()
        # valor del propio nodo (si lo tiene)
        if prefijo:
            try:
                g = pdb.tool_get({"ns": ns, "subs": prefijo})
                if g.get("success") is not False and g.get("value") is not None:
                    salida.append({"ns": ns, "subs": list(prefijo), "value": g["value"]})
                    visitados += 1
            except Exception:
                pass

        # recorrer los hijos de este nivel
        hijos = []
        clave = ""
        for _ in range(100_000):
            try:
                r = pdb.tool_order({"ns": ns, "subs": list(prefijo) + [clave],
                                    "direction": 1})
            except Exception:
                break
            if not r.get("success") or r.get("value") in (None, ""):
                break
            k = str(r["value"])
            if k == clave:
                break
            hijos.append(k)
            clave = k

        # apilar en orden inverso para que el recorrido sea ascendente
        for k in reversed(hijos):
            pila.append(prefijo + [k])

    return salida
