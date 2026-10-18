#!/usr/bin/env python3
"""certificado.py — certificado de decisión con replay verificable.

Cierra lo que el digest canónico dejaba a medias. Un certificado de replay
necesita CUATRO piezas, no una:

    1. estado resultante      -> digest canónico (digest_canonico.py)
    2. versión de reglas      -> qué ^REGLA regía en ese momento
    3. versión de modelo      -> qué LLM respondió
    4. respuestas cacheadas   -> el texto EXACTO que devolvió el LLM

Sin las cuatro, el replay no puede demostrar nada: si el LLM devuelve otro
texto, la decisión cambia y no hay forma de saber si fue el modelo o la lógica.

DISEÑO
------
- `^REGLA(ns, clave) = valor` con `^REGLA(ns, "version")` explícita.
  El digest de reglas cubre el namespace ENTERO, así que tocar una regla
  cambia el certificado de todas las decisiones de ese ns.
- `^LLMCACHE(clave) = respuesta`, donde la clave es
  sha256(modelo + prompt + params). Determinista y estable entre máquinas.
- El certificado es un dict serializable que se firma con sha256 y se puede
  guardar en `^CERT(id)`.

Uso:
    from certificado import emitir, verificar, grabar_reglas
    grabar_reglas(pdb, "credito", {"umbral": 0.05, "max": 10000})
    cert = emitir("credito", programa, resultado, reglas, respuestas_llm)
    verificar(cert, programa_reejecutado)
"""
from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from digest_canonico import VERSION as DIGEST_VERSION
from digest_canonico import digest_de_ejecucion, digest_de_globals

CERT_VERSION = "1"

# Claves que NO entran en el digest de reglas (metadatos, no reglas)
_META_REGLA = {"version", "updated_at", "updated_by", "note", "notes"}


# ── reglas ────────────────────────────────────────────────────────────────────

def digest_de_reglas(reglas: dict) -> str:
    """Digest del conjunto de reglas de un namespace.

    Ordena las claves y normaliza el valor igual que el digest de estado, para
    que dos máquinas con las mismas reglas den el mismo hash.
    """
    h = hashlib.sha256()
    h.update(f"reglas:v{CERT_VERSION}\x1e".encode())
    for k in sorted(reglas or {}):
        v = reglas[k]
        h.update(f"{k}\x1f".encode())
        h.update(json.dumps(v, sort_keys=True, ensure_ascii=False, default=str).encode())
        h.update(b"\x1e")
    return h.hexdigest()


def leer_reglas(pdb, ns: str) -> dict:
    """Lee ^REGLA(ns, *) de la PDB. Devuelve dict clave->valor.

    OJO: `tool_order` devuelve UNA sola clave en `value` (no una lista en `keys`),
    y hay que iterar pasando el último subkey como punto de partida. Es la
    trampa que hacía que esta funcion devolviera {} en silencio.
    """
    out = {}
    clave = ""
    for _ in range(500):                       # tope de seguridad
        r = pdb.tool_order({"ns": "REGLA", "subs": [ns, clave], "direction": 1})
        if not r.get("success") or r.get("value") in (None, ""):
            break
        k = str(r["value"])
        if k == clave:                         # no avanza: se acabo
            break
        g = pdb.tool_get({"ns": "REGLA", "subs": [ns, k]})
        if g.get("success") is not False:
            out[k] = g.get("value")
        clave = k
    return out


def grabar_reglas(pdb, ns: str, reglas: dict, autor: str = "operador") -> str:
    """Escribe ^REGLA(ns, clave)=valor y sube la versión. Devuelve el digest."""
    prev = leer_reglas(pdb, ns)
    try:
        version = int((prev or {}).get("version") or 0) + 1
    except (TypeError, ValueError):
        version = 1

    for k, v in (reglas or {}).items():
        pdb.tool_set({"ns": "REGLA", "subs": [ns, _slug(k)], "value": v})
    pdb.tool_set({"ns": "REGLA", "subs": [ns, "version"], "value": version})
    pdb.tool_set({"ns": "REGLA", "subs": [ns, "updated_at"], "value": int(time.time())})
    pdb.tool_set({"ns": "REGLA", "subs": [ns, "updated_by"], "value": autor})

    return digest_de_reglas(leer_reglas(pdb, ns))


def _slug(k: str) -> str:
    """Clave de regla a subkey: sin espacios raros, pero reversible a ojo."""
    return str(k).strip().replace(" ", "_")


# ── caché LLM ────────────────────────────────────────────────────────────────

def clave_llm(modelo: str, prompt: str, params: dict | None = None) -> str:
    """Clave estable de caché para una llamada LLM.

    Incluye TODO lo que puede cambiar la respuesta: modelo, prompt y parámetros
    (temperatura, max_tokens, system). Si algo de eso cambia, la clave cambia y
    el replay no encuentra la respuesta vieja: exactamente lo que un auditor
    quiere ver.
    """
    h = hashlib.sha256()
    h.update(f"llm:v{CERT_VERSION}\x1e".encode())
    h.update(f"modelo\x1f{modelo}\x1e".encode())
    h.update(f"prompt\x1f{prompt}\x1e".encode())
    h.update(f"params\x1f{json.dumps(params or {}, sort_keys=True, ensure_ascii=False)}\x1e".encode())
    return h.hexdigest()


def leer_llm(pdb, clave: str):
    """Devuelve la respuesta cacheada o None."""
    try:
        g = pdb.tool_get({"ns": "LLMCACHE", "subs": [clave]})
        if g.get("found") is False:
            return None
        v = g.get("value")
        if isinstance(v, str):
            try:
                return json.loads(v)
            except Exception:
                return {"texto": v}
        return v
    except Exception:
        return None


def grabar_llm(pdb, clave: str, respuesta: dict) -> None:
    """Cachea una respuesta. Se guarda como JSON string (la PDB no tiene dicts)."""
    pdb.tool_set({"ns": "LLMCACHE", "subs": [clave],
                  "value": json.dumps(respuesta, ensure_ascii=False, sort_keys=True)})


# ── certificado ──────────────────────────────────────────────────────────────

def emitir(ns_reglas: str, programa: str, resultado: dict,
           digest_reglas: str, respuestas_llm: list[dict],
           modelo: str = "", extra: dict | None = None) -> dict:
    """Construye el certificado de una decisión.

    `respuestas_llm` es la lista de {clave, modelo, texto} que se usaron.
    """
    cert = {
        "cert_version": CERT_VERSION,
        "digest_version": DIGEST_VERSION,
        "ts": int(time.time()),
        "ns_reglas": ns_reglas,
        "digest_reglas": digest_reglas,
        "modelo": modelo,
        "digest_estado": digest_de_globals(resultado.get("globals")),
        "digest_ejecucion": digest_de_ejecucion(programa, resultado),
        "program_hash": (resultado.get("state") or {}).get("program_hash", ""),
        "llm": [{"clave": r.get("clave"), "modelo": r.get("modelo"),
                 "texto": r.get("texto")} for r in (respuestas_llm or [])],
        "extra": extra or {},
    }
    cert["firma"] = firmar(cert)
    return cert


def firmar(cert: dict) -> str:
    """Firma = sha256 del certificado SIN el campo firma."""
    cuerpo = {k: v for k, v in cert.items() if k != "firma"}
    return hashlib.sha256(
        json.dumps(cuerpo, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def verificar_firma(cert: dict) -> bool:
    return cert.get("firma") == firmar(cert)


def verificar(cert: dict, resultado_nuevo: dict,
              digest_reglas_actual: str | None = None) -> dict:
    """Re-ejecuta y compara. Devuelve un informe, no un booleano.

    Distingue cuatro desenlaces, porque cada uno significa algo distinto:
      - ok:            todo coincide
      - reglas_cambiadas: el certificado es válido pero ya no aplica
      - estado_distinto: la decisión cambió (y sabemos por qué mirar)
      - firma_invalida: alguien tocó el certificado
    """
    informe = {
        "firma_valida": verificar_firma(cert),
        "estado_igual": False,
        "reglas_iguales": None,
        "veredicto": "",
    }

    if not informe["firma_valida"]:
        informe["veredicto"] = "firma_invalida"
        return informe

    d_ahora = digest_de_globals(resultado_nuevo.get("globals"))
    informe["estado_igual"] = (d_ahora == cert.get("digest_estado"))
    informe["digest_antes"] = cert.get("digest_estado")
    informe["digest_ahora"] = d_ahora

    if digest_reglas_actual is not None:
        informe["reglas_iguales"] = (digest_reglas_actual == cert.get("digest_reglas"))

    if not informe["estado_igual"]:
        informe["veredicto"] = "estado_distinto"
    elif informe["reglas_iguales"] is False:
        informe["veredicto"] = "reglas_cambiadas"
    else:
        informe["veredicto"] = "ok"
    return informe


def diff_politicas(cert: dict, resultado_con_reglas_nuevas: dict) -> dict:
    """Contrafactual: qué cambió al cambiar las reglas.

    La pieza que vende el doc 15: "con esta regla, N de M decisiones habrían
    cambiado". Aquí para UNA decisión; el agregado se calcula repitiendo esto
    sobre el histórico de certificados.
    """
    d_ahora = digest_de_globals(resultado_con_reglas_nuevas.get("globals"))
    return {
        "cambio": d_ahora != cert.get("digest_estado"),
        "digest_antes": cert.get("digest_estado"),
        "digest_ahora": d_ahora,
    }
