#!/usr/bin/env python3
"""anclaje.py — epoch automático + publicación del root (el "notario" del doc 10).

Cierra el circuito:

    PDB  →  Merkle root por epoch  →  ^AUDIT(epoch, root)  →  publicación
            (merkle_epoch.py)          (esta pieza)            (Rekor/fichero)

El doc 10 pide tres niveles:
  A. anclaje + log de transparencia        <- ESTO (días de trabajo)
  B. consorcio con fraud proofs            <- no
  C. LUMEN como alternativa a EVM          <- nunca

Sin publicar el root, la prueba de inclusión solo vale si te fías de quien te la
da. Con el root publicado en un sitio que no controlas, vale por sí sola.

MODOS DE PUBLICACIÓN
--------------------
  fichero   append-only local (`^AUDIT` + un JSONL). Sirve para demos y para
            que el cliente tenga su propio registro.
  http      un POST a una URL (un log de transparencia, un bucket, un gist).
            Aquí solo se deja el gancho: no se implementa el cliente HTTP
            porque cada comprador pide el suyo.
  none      calcula y guarda, no publica (para CI o para probar).

GARANTÍA: el root y el `n` se guardan en `^AUDIT(epoch, ...)` de la propia PDB,
así que la PDB se convierte en su propio libro de epochs. Un auditor puede pedir
el epoch N y compararlo con lo que le dieron.

Uso:
    from anclaje import sellar_epoch, leer_epoch, verificar_epoch_publicado

    sello = sellar_epoch(pdb, "LOTE", publicar="fichero")
    # {"epoch": 3, "root": "...", "n": 42, "ts": ..., "ns": "LOTE"}
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from merkle_epoch import epoch_de_pdb

VERSION = "1"

# Ruta del registro append-only local. Configurable por entorno.
ENV_REGISTRO = "LUMEN_ANCLAJE_JSONL"
REGISTRO_DEFECTO = "anclajes.jsonl"


def _registro_path() -> Path:
    p = os.environ.get(ENV_REGISTRO)
    if p:
        return Path(p)
    return Path.cwd() / REGISTRO_DEFECTO


def _siguiente_epoch(pdb, ns: str) -> int:
    """Número del próximo epoch para un namespace (el último + 1)."""
    try:
        g = pdb.tool_get({"ns": "AUDIT", "subs": [ns, "ultimo"]})
        v = g.get("value")
        return int(v) + 1 if v is not None else 1
    except Exception:
        return 1


def sellar_epoch(pdb, ns: str, publicar: str = "fichero",
                 url: str | None = None) -> dict:
    """Calcula el Merkle root de un namespace y lo sella.

    Devuelve el sello. Deja en la PDB:
      ^AUDIT(ns, "ultimo")        -> número del último epoch
      ^AUDIT(ns, epoch, "root")   -> root hex
      ^AUDIT(ns, epoch, "n")      -> número de hojas
      ^AUDIT(ns, epoch, "ts")     -> timestamp
      ^AUDIT(ns, epoch, "version")-> versión del formato
    """
    epoch = _siguiente_epoch(pdb, ns)
    e = epoch_de_pdb(pdb, ns)
    ts = int(time.time())

    sello = {
        "version": VERSION,
        "ns": ns,
        "epoch": epoch,
        "root": e["root"],
        "n": e["n"],
        "ts": ts,
    }

    # 1. dejar constancia en la propia PDB (la PDB es su propio libro)
    for k, v in (("root", e["root"]), ("n", e["n"]), ("ts", ts), ("version", VERSION)):
        pdb.tool_set({"ns": "AUDIT", "subs": [ns, epoch, k], "value": v})
    pdb.tool_set({"ns": "AUDIT", "subs": [ns, "ultimo"], "value": epoch})

    # 2. publicar
    publicado = False
    if publicar == "fichero":
        ruta = _registro_path()
        with open(ruta, "a", encoding="utf-8") as f:
            f.write(json.dumps(sello, sort_keys=True, ensure_ascii=False) + "\n")
        publicado = True
        sello["publicado_en"] = str(ruta)
    elif publicar == "ots":
        # Anclaje REAL en Bitcoin via OpenTimestamps (sin el cliente `ots`,
        # que no funciona en Windows). Ver publicar_ots.py.
        try:
            from publicar_ots import sellar_en_ots
            ancla = sellar_en_ots(e["root"])
            sello["ots"] = ancla
            if ancla.get("ok"):
                publicado = True
                sello["publicado_en"] = ancla.get("calendar")
                # dejar tambien constancia en la PDB
                pdb.tool_set({"ns": "AUDIT", "subs": [ns, epoch, "ots_digest"],
                              "value": ancla["digest"]})
        except Exception as ex:
            sello["ots_error"] = f"{type(ex).__name__}: {str(ex)[:120]}"
    elif publicar == "http" and url:
        # gancho: cada comprador pide su log de transparencia
        sello["publicado_en"] = url
        sello["pendiente_http"] = True
        publicado = False
    else:
        sello["publicado_en"] = None

    sello["publicado"] = publicado
    return sello


def leer_epoch(pdb, ns: str, epoch: int) -> dict | None:
    """Recupera un sello de la propia PDB."""
    try:
        out = {}
        for k in ("root", "n", "ts", "version"):
            g = pdb.tool_get({"ns": "AUDIT", "subs": [ns, epoch, k]})
            if g.get("success") is False or g.get("value") is None:
                return None
            out[k] = g.get("value")
        out["ns"] = ns
        out["epoch"] = int(epoch)
        return out
    except Exception:
        return None


def verificar_epoch_publicado(pdb, sello: dict) -> dict:
    """Comprueba que el sello que te dan coincide con el que hay en la PDB.

    Detecta el caso de alguien que presenta un manifiesto con un root que no es
    el que se selló.
    """
    ns = sello.get("ns")
    ep = sello.get("epoch")
    if ns is None or ep is None:
        return {"ok": False, "motivo": "sello incompleto (falta ns o epoch)"}

    en_pdb = leer_epoch(pdb, ns, ep)
    if en_pdb is None:
        return {"ok": False, "motivo": f"no hay epoch {ep} para {ns} en la PDB"}

    igual = en_pdb["root"] == sello.get("root")
    return {
        "ok": igual,
        "motivo": "coincide" if igual else "el root NO coincide con el sellado",
        "root_en_pdb": en_pdb["root"],
        "root_recibido": sello.get("root"),
        "n_en_pdb": en_pdb["n"],
        "n_recibido": sello.get("n"),
    }


def leer_registro(ruta: str | None = None) -> list[dict]:
    """Lee el registro append-only local (JSONL)."""
    p = Path(ruta) if ruta else _registro_path()
    if not p.exists():
        return []
    out = []
    with open(p, encoding="utf-8") as f:
        for linea in f:
            linea = linea.strip()
            if linea:
                try:
                    out.append(json.loads(linea))
                except Exception:
                    continue
    return out


def verificar_cadena_registro(ruta: str | None = None) -> dict:
    """Comprueba que el registro no se ha reordenado ni truncado.

    Aunque no hay encadenamiento de hashes entre epochs (no hace falta: cada uno
    cubre un conjunto distinto), sí se puede comprobar que los números de epoch
    son consecutivos por namespace y que no hay huecos ni duplicados.
    """
    sellos = leer_registro(ruta)
    por_ns: dict[str, list[int]] = {}
    for s in sellos:
        por_ns.setdefault(s.get("ns", "?"), []).append(int(s.get("epoch", 0)))

    problemas = []
    for ns, eps in por_ns.items():
        eps_ord = sorted(eps)
        esperado = list(range(1, len(eps_ord) + 1))
        if eps_ord != esperado:
            problemas.append({"ns": ns, "epochs": eps_ord, "esperado": esperado})

    return {
        "ok": not problemas,
        "n_sellos": len(sellos),
        "namespaces": list(por_ns),
        "problemas": problemas,
    }
