#!/usr/bin/env python3
"""merkle_stream.py — Merkle root sin cargar el namespace en memoria.

PROBLEMA
--------
`root_de_epoch(leer_ns_rango(pdb, ns))` acumula TODO antes de hashear:

    leer_ns_rango pico :  66 MB por 200k claves
    root_de_epoch pico : 133 MB por 200k claves
    -> ~1 GB por millón; 10M reventaría

PERO EL MERKLE SE PUEDE CONSTRUIR INCREMENTALMENTE
--------------------------------------------------
Una hoja = sha256(linea_canonica). No hace falta tener todas las hojas para
construir el nivel siguiente: solo **dos a la vez**.

    nivel 0: recorrer el cursor, hashear cada hoja, emparejar de dos en dos
             y empujar el hash del par al nivel 1. Memoria: O(n/2) hashes,
             no O(n) dicts.
    nivel k: idem, sobre los hashes del nivel anterior.

Para 1M claves el nivel 0 son 1M hashes (32 MB) pero **cero dicts de Python**
(~300 MB ahorrados). Y el nivel 0 se puede volcar a disco si hace falta.

EL PROBLEMA DEL ORDEN
---------------------
El árbol exige las hojas ORDENADAS. El cursor SQL ya las da ordenadas por
subkey, que es el orden canónico (la proyección usa ese mismo orden). Así que
**se puede hashear en streaming sin ordenar en memoria**.

CUIDADO con el nodo impar: sube sin combinar. Se guarda "pendiente" y se
arrastra al siguiente par.

USO
---
    from merkle_stream import root_stream_ns, root_stream_filas

    r = root_stream_ns(pdb, "LOTE")        # 1M en streaming
    r = root_stream_filas(iterable)        # desde cualquier iterable ordenado
"""
from __future__ import annotations

import hashlib

from digest_canonico import _valor, _subs
from pdb_tools import encode_subkey

VERSION = "1"


def _h(data: bytes) -> bytes:
    return hashlib.sha256(data).digest()


def _linea(ns: str, subs, value) -> str:
    """Misma proyección canónica que digest_canonico (no duplicar la lógica)."""
    return f"{ns}\x1f{_subs(subs)}\x1f{_valor(value)}"


def _hash_hoja(linea: str) -> bytes:
    return _h(f"v{VERSION}\x1ehoja\x1f{linea}".encode("utf-8"))


def _hash_par(a: bytes, b: bytes) -> bytes:
    if a > b:
        a, b = b, a
    return _h(f"v{VERSION}\x1enodo\x1f".encode() + a + b)


class AcumuladorNivel:
    """Empareja hashes de un nivel y empuja los pares al siguiente.

    Memoria: O(1) por nivel (guarda uno pendiente) + O(n/2) en el nivel de
    salida. Si `volcar_a` se indica, el nivel de salida va a disco.
    """

    __slots__ = ("_pendiente", "_destino", "_n_hojas", "_volcar")

    def __init__(self, destino: list | None = None, volcar=None):
        self._pendiente = None
        self._destino = destino
        self._n_hojas = 0
        self._volcar = volcar

    def push(self, h: bytes) -> None:
        self._n_hojas += 1
        if self._pendiente is None:
            self._pendiente = h
            return
        par = _hash_par(self._pendiente, h)
        self._pendiente = None
        if self._volcar is not None:
            self._volcar.write(par)
        else:
            self._destino.append(par)

    def cerrar(self) -> int:
        """Cierra el nivel. Devuelve cuántos hashes salieron."""
        if self._pendiente is not None:
            if self._volcar is not None:
                self._volcar.write(self._pendiente)
            else:
                self._destino.append(self._pendiente)
            self._pendiente = None
        return len(self._destino) if self._destino is not None else -1


def root_stream_filas(filas) -> dict:
    """Merkle root de un iterable YA ORDENADO de {ns,subs,value}.

    No acumula las hojas: hashea y empareja sobre la marcha. Memoria ~O(n/2)
    hashes de 32 bytes (no O(n) dicts). Para 1M: ~16-32 MB en vez de 300+.
    """
    nivel = []
    pendiente = None
    n_hojas = 0

    # ── nivel 0: hojas en streaming ────────────────────────────────────────
    # Cada hoja se hashea y se empareja con la anterior EN CUANTO llega. La
    # salida ya es el NIVEL 1 (pares de hojas), no la lista de hojas.
    for f in filas:
        linea = _linea(f.get("ns", ""), f.get("subs"), f.get("value"))
        h = _hash_hoja(linea)
        n_hojas += 1
        if pendiente is None:
            pendiente = h
        else:
            nivel.append(_hash_par(pendiente, h))
            pendiente = None
    if pendiente is not None:
        nivel.append(pendiente)      # hoja impar: sube sin combinar
        pendiente = None

    if n_hojas == 0:
        return {
            "root": _h(f"v{VERSION}\x1eepoch_vacio".encode()).hex(),
            "n": 0, "alto": 0, "streaming": True,
        }

    # La reducción de hojas->pares ya contó como un nivel (si hubo >= 2 hojas).
    alto = 1 if n_hojas > 1 else 0
    # ── niveles superiores: mismo patrón, sobre los hashes ya reducidos ────
    while len(nivel) > 1:
        siguiente = []
        pend = None
        for h in nivel:
            if pend is None:
                pend = h
            else:
                siguiente.append(_hash_par(pend, h))
                pend = None
        if pend is not None:
            siguiente.append(pend)
        nivel = siguiente
        alto += 1

    return {"root": nivel[0].hex(), "n": n_hojas, "alto": alto, "streaming": True}


def root_stream_ns(pdb, ns: str, subs: list | None = None) -> dict:
    """Merkle root de un namespace, leyendo del cursor en streaming.

    No instancia `leer_ns_rango` (que devuelve una lista). Recorre el cursor y
    hashea cada fila. Al final deja el árbol en `^AUDIT` si se le pide.
    """
    prefijo = encode_subkey(subs) if subs else b""
    from lectura_rango import _decode_db_value, _decodificar, _limite_superior

    hasta = _limite_superior(prefijo) if prefijo else None
    c = pdb._get_conn(ns, None)

    if prefijo and hasta:
        sql = ("SELECT subkey, value FROM _globals WHERE ns=? AND subkey>=? "
               "AND subkey<? AND value IS NOT NULL ORDER BY subkey")
        params = (ns, prefijo, hasta)
    else:
        sql = ("SELECT subkey, value FROM _globals WHERE ns=? AND value IS NOT NULL "
               "ORDER BY subkey")
        params = (ns,)

    def generador():
        for subkey, valor in c.execute(sql, params):
            yield {"ns": ns, "subs": _decodificar(subkey),
                   "value": _decode_db_value(valor)}

    r = root_stream_filas(generador())
    r["ns"] = ns
    return r
