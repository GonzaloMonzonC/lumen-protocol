#!/usr/bin/env python3
"""lectura_rango.py — recorrer un namespace entero en SQL, no por $ORDER.

PROBLEMA
--------
`merkle_epoch._leer_ns` recorre el árbol con `tool_order`/`tool_get`: **una
llamada al MCP por nodo**. Para un namespace de un millón de claves son millones
de llamadas. El anclaje no escala.

LA CLAVE: el subkey es un BLOB PREFIJADO
----------------------------------------
`encode_subkey()` produce claves donde cada subscript va con su tipo y un `\\xff`
final. Consecuencia: **las claves de un namespace (o de un subárbol) tienen un
prefijo común y ordenan por bytes**. Eso permite:

    SELECT subkey, value FROM _globals
     WHERE ns = ? AND subkey > ?  AND subkey < ?
     ORDER BY subkey

con el rango calculado a partir del prefijo — **una sola query** y el índice
hace el trabajo. Es la misma idea que un recorrido por rango en MUMPS.

CÁLCULO DEL RANGO
-----------------
    prefijo = encode_subkey(subs)          # p.ej. \\x02L1\\xff
    desde   = prefijo                      # lo primero >= prefijo
    hasta   = prefijo[:-1] + bytes([prefijo[-1]+1])   # justo despues del prefijo

Ojo: el `\\xff` final es lo que hace que el límite superior funcione. Si el
prefijo acabara en `\\xff`, se incrementa el byte anterior (con acarreo).

USO
---
    from lectura_rango import leer_ns_rango, contar_ns

    filas = leer_ns_rango(pdb, "LOTE")           # todas las hojas del ns
    filas = leer_ns_rango(pdb, "LOTE", subs=["L1"])   # solo el subárbol L1
    n = contar_ns(pdb, "LOTE")                   # cuántas sin traerlas
"""
from __future__ import annotations

import json
import sqlite3

from pdb_tools import encode_subkey


def _decode_db_value(value):
    """Deserializa el valor tal como lo guarda la PDB.

    La columna `value` guarda JSON sin decodificar (`"co"`, `"1200"`). tool_get
    lo deserializa; el SQL crudo no. Misma lógica que lumen_mlight._decode_db_value
    (se replica aquí para no depender del motor).
    """
    if value is None:
        return None
    if isinstance(value, bytes):
        value = value.decode("utf-8")
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return value


def _limite_superior(prefijo: bytes) -> bytes:
    """El primer valor estrictamente mayor que cualquier clave con ese prefijo.

    Se incrementa el último byte con acarreo. Si el prefijo acaba en 0xFF, se
    sube el anterior y se trunca (así `\\x02\\xff` -> `\\x03`).
    """
    b = bytearray(prefijo)
    while b and b[-1] == 0xFF:
        b.pop()
    if not b:
        # todo 0xFF: no hay límite superior; se devuelve un valor que ordena
        # después de cualquier clave razonable
        return b"\xff" * (len(prefijo) + 1)
    b[-1] += 1
    return bytes(b)


def _conexion(pdb, ns: str):
    """Conexión de SOLO LECTURA a la BD del namespace.

    Usa `_get_conn` de pdb_tools para respetar particiones y mapeos: en una PDB
    particionada, el namespace puede vivir en otro fichero.
    """
    c = pdb._get_conn(ns, None)
    return c


def leer_ns_rango(pdb, ns: str, subs: list | None = None,
                  campo: str = "value") -> list[dict]:
    """Lee todas las claves de un namespace (o subárbol) con UNA query.

    Devuelve [{"ns","subs","value"}] con las hojas que tienen valor.
    Los nodos estructurales (value NULL) se omiten: no aportan nada al root.
    """
    prefijo = encode_subkey(subs) if subs else b""
    hasta = _limite_superior(prefijo) if prefijo else None

    c = _conexion(pdb, ns)
    if prefijo and hasta:
        sql = ("SELECT subkey, value FROM _globals "
               "WHERE ns = ? AND subkey >= ? AND subkey < ? AND value IS NOT NULL "
               "ORDER BY subkey")
        params = (ns, prefijo, hasta)
    elif prefijo:
        sql = ("SELECT subkey, value FROM _globals "
               "WHERE ns = ? AND subkey >= ? AND value IS NOT NULL ORDER BY subkey")
        params = (ns, prefijo)
    else:
        sql = ("SELECT subkey, value FROM _globals "
               "WHERE ns = ? AND value IS NOT NULL ORDER BY subkey")
        params = (ns,)

    salida = []
    for subkey, valor in c.execute(sql, params):
        salida.append({
            "ns": ns,
            "subs": _decodificar(subkey),
            # OJO: la columna `value` guarda JSON SIN decodificar (`"co"`,
            # `"1200"`). tool_get lo deserializa; el SQL crudo no. Sin pasar por
            # _decode_db_value el digest cambia: `"co"` (con comillas) en vez de
            # `co`. Ese fue el bug que hizo divergir el root de LOTE.
            "value": _decode_db_value(valor),
        })
    return salida


def _decodificar(subkey) -> list:
    """Decodifica un subkey BLOB a lista de subscripts.

    Se apoya en decode_subkey de pdb_tools si existe (es la parte que tuvo el
    bug del formato numérico, ya arreglado); si no, deja el hex como marcador
    para no romper el root.
    """
    from pdb_tools import decode_subkey  # import local: evita ciclos
    try:
        return decode_subkey(bytes(subkey) if not isinstance(subkey, bytes) else subkey)
    except Exception:
        return [f"<hex:{(bytes(subkey) if not isinstance(subkey, bytes) else subkey).hex()}>"]


def contar_ns(pdb, ns: str, subs: list | None = None) -> int:
    """Cuenta claves con valor sin traerlas (para estimar antes de hashear)."""
    prefijo = encode_subkey(subs) if subs else b""
    hasta = _limite_superior(prefijo) if prefijo else None
    c = _conexion(pdb, ns)
    if prefijo and hasta:
        row = c.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns=? AND subkey>=? AND subkey<? "
            "AND value IS NOT NULL", (ns, prefijo, hasta)).fetchone()
    elif prefijo:
        row = c.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns=? AND subkey>=? AND value IS NOT NULL",
            (ns, prefijo)).fetchone()
    else:
        row = c.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns=? AND value IS NOT NULL", (ns,)).fetchone()
    return int(row[0]) if row else 0


def listar_namespaces(pdb) -> list[str]:
    """Namespaces con datos, en una query."""
    try:
        c = pdb._get_conn(None, None)
        return [r[0] for r in c.execute(
            "SELECT DISTINCT ns FROM _globals ORDER BY ns")]
    except Exception:
        return []
