#!/usr/bin/env python3
"""publicar_ots.py — anclar un root en OpenTimestamps (Bitcoin), sin `ots`.

POR QUE NO SE USA EL CLIENTE `ots`
----------------------------------
`opentimestamps-client` necesita `python-bitcoinlib` con su parte nativa, y en
Windows falla con `OSError: [WinError 193] %1 no es una aplicación Win32 válida`.
Así que se habla el protocolo directamente por HTTP.

EL PROTOCOLO, EN CORTO
----------------------
Un calendar server de OpenTimestamps (los públicos y gratuitos: alice, bob,
finney) acepta un POST con **32 bytes** (el digest sha256) y devuelve una
**prueba de compromiso** en formato binario (`vnd.opentimestamps.v1`).

Esa prueba dice: "tu digest está en el merkle tree de este calendar, en tal
posición". Horas después, el calendar agrega su árbol en una transacción de
Bitcoin. Entonces la prueba se puede completar (`upgrade`) y verificar contra el
bloque.

AQUÍ se implementa:
  - `sellar_en_ots(root_hex)`  -> envía el digest y guarda la prueba
  - `pedir_upgrade(prueba)`    -> pregunta si ya está confirmada en Bitcoin
  - `guardar_prueba` / `leer_prueba` -> persistencia en fichero

LO QUE NO HACE: no verifica la cadena hasta Bitcoin (eso exige un nodo o un
explorador). Deja la prueba y el estado; la verificación completa se hace con
`ots verify` en Linux/macOS, o con un explorador de bloques.

USO
---
    from publicar_ots import sellar_en_ots, pedir_upgrade

    s = sellar_en_ots("391ed863…")      # root hex de 64 chars
    s = pedir_upgrade(s)                # horas después: ¿ya en un bloque?
"""
from __future__ import annotations

import binascii
import hashlib
import json
import os
import urllib.error
import urllib.request

# Calendars públicos de OpenTimestamps (gratuitos). Se prueban en orden.
CALENDARS = [
    "https://alice.btc.calendar.opentimestamps.org",
    "https://bob.btc.calendar.opentimestamps.org",
    "https://finney.calendar.eternitywall.com",
]

TIMEOUT = 25
ENV_DIR = "LUMEN_OTS_DIR"


def _dir(pruebas_dir: str | None = None) -> str:
    d = pruebas_dir or os.environ.get(ENV_DIR) or os.path.join(os.getcwd(), "ots")
    os.makedirs(d, exist_ok=True)
    return d


def _post(url: str, datos: bytes) -> bytes:
    req = urllib.request.Request(
        url, data=datos, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/vnd.opentimestamps.v1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def _get(url: str) -> bytes:
    req = urllib.request.Request(
        url, headers={"Accept": "application/vnd.opentimestamps.v1"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.read()


def digest_de_root(root_hex: str) -> bytes:
    """El digest que se ancla. sha256 de los bytes del root (no del hex)."""
    if len(root_hex) != 64:
        raise ValueError(f"root debe ser hex de 64 chars, no {len(root_hex)}")
    return hashlib.sha256(bytes.fromhex(root_hex)).digest()


def sellar_en_ots(root_hex: str, pruebas_dir: str | None = None,
                  calendars: list[str] | None = None) -> dict:
    """Envía el root a un calendar y guarda la prueba de compromiso.

    Devuelve {"ok", "root", "digest", "prueba_hex", "calendar", "fichero"}.
    Si todos los calendars fallan, {"ok": False, "errores": [...]} — sin
    excepción, para que el anclaje no tumbe un sellado.
    """
    digest = digest_de_root(root_hex)
    errores = []
    for cal in (calendars or CALENDARS):
        try:
            resp = _post(f"{cal}/digest", digest)
            if not resp:
                errores.append(f"{cal}: respuesta vacía")
                continue
            fichero = os.path.join(_dir(pruebas_dir), f"{root_hex[:16]}.ots.bin")
            with open(fichero, "wb") as f:
                f.write(resp)
            return {
                "ok": True,
                "root": root_hex,
                "digest": digest.hex(),
                "prueba_hex": binascii.hexlify(resp).decode(),
                "bytes": len(resp),
                "calendar": cal,
                "fichero": fichero,
                "confirmado": False,
            }
        except urllib.error.HTTPError as e:
            errores.append(f"{cal}: HTTP {e.code}")
        except Exception as e:
            errores.append(f"{cal}: {type(e).__name__} {str(e)[:80]}")
    return {"ok": False, "root": root_hex, "errores": errores}


def pedir_upgrade(prueba_bin: bytes, calendars: list[str] | None = None) -> dict:
    """Pregunta al calendar si la prueba ya está confirmada en Bitcoin.

    El calendar responde con una prueba AMPLIADA (con el camino al bloque) o
    con un 404 si aún no está agregada (normal las primeras horas).
    """
    errores = []
    for cal in (calendars or CALENDARS):
        try:
            resp = _post(f"{cal}/timestamp/{binascii.hexlify(prueba_bin).decode()}",
                         b"")
            if resp:
                return {"ok": True, "confirmada": True, "prueba_hex":
                        binascii.hexlify(resp).decode(), "calendar": cal}
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return {"ok": True, "confirmada": False,
                        "motivo": "aún no agregada al arbol (normal < 6h)"}
            errores.append(f"{cal}: HTTP {e.code}")
        except Exception as e:
            errores.append(f"{cal}: {type(e).__name__}")
    return {"ok": False, "confirmada": False, "errores": errores}


def guardar_prueba(sello: dict, pruebas_dir: str | None = None) -> str:
    """Guarda el sello como JSON junto a la prueba binaria."""
    d = _dir(pruebas_dir)
    fichero = os.path.join(d, f"{sello['root'][:16]}.json")
    with open(fichero, "w", encoding="utf-8") as f:
        json.dump(sello, f, indent=1, ensure_ascii=False)
    return fichero


def leer_prueba(root_hex: str, pruebas_dir: str | None = None) -> dict | None:
    d = _dir(pruebas_dir)
    fichero = os.path.join(d, f"{root_hex[:16]}.json")
    if not os.path.exists(fichero):
        return None
    with open(fichero, encoding="utf-8") as f:
        return json.load(f)


def estado() -> dict:
    """Comprueba si hay red y algún calendar responde (sin anclar nada)."""
    for cal in CALENDARS:
        try:
            _get(f"{cal}/")
            return {"ok": True, "calendar": cal}
        except Exception as e:
            continue
    return {"ok": False, "motivo": "ningun calendar responde"}
