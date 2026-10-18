#!/usr/bin/env python3
"""test_certificado.py — el ciclo completo de la "caja negra de agentes" (doc 15).

Simula una decisión de negocio (conceder/denegar un crédito) y comprueba:

  1. Emitir certificado -> replay da el MISMO digest (decisión probada)
  2. Cambiar una regla  -> el replay DIVERGE, y sabemos que fue por la regla
  3. Cambiar el modelo  -> la clave de caché LLM cambia, la respuesta ya no
                           aparece: el certificado queda no reproducible
  4. Tocar el certificado -> firma inválida (detección de manipulación)
  5. Contrafactual      -> "con este umbral, esta decisión habría cambiado"

Usa una PDB temporal; no toca datos reales.

Uso: LUMEN_REPO=~/Documents/GitHub/lumen-protocol python test_certificado.py
"""
import os
import shutil
import sys
import tempfile

_here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _here)

_REPO = os.environ.get("LUMEN_REPO", os.path.expanduser("~/Documents/GitHub/lumen-protocol"))
_PDB_DIR = os.path.join(_REPO, "implementations", "mcp-servers", "pdb")
if not os.path.isdir(_PDB_DIR):
    sys.exit(f"No encuentro {_PDB_DIR} (define LUMEN_REPO)")

_tmp = tempfile.mkdtemp(prefix="cert_test_")
os.environ["PDB_PATH"] = os.path.join(_tmp, "test.db")
sys.path.insert(0, _PDB_DIR)

import lumen_mlight as L  # noqa: E402
import pdb_tools as pdb  # noqa: E402
from certificado import (  # noqa: E402
    clave_llm,
    diff_politicas,
    digest_de_reglas,
    emitir,
    grabar_llm,
    grabar_reglas,
    leer_llm,
    leer_reglas,
    verificar,
)
from digest_canonico import digest_de_globals  # noqa: E402

fails = []


def chk(cond, msg):
    print(f"   {'OK  ' if cond else 'FALLA'} {msg}")
    if not cond:
        fails.append(msg)


# ── La decisión de negocio ───────────────────────────────────────────────────
# Regla: si la deuda supera `max_deuda` se deniega; si el ratio deuda/ingreso
# supera `umbral` se deniega; si no, se concede.
PROGRAMA = """
S deuda=^SOLICITUD(1,"deuda")
S ingreso=^SOLICITUD(1,"ingreso")
S max=^REGLA("credito","max_deuda")
S umbral=^REGLA("credito","umbral")
S ratio=deuda/ingreso
S decision=1
I ratio>umbral D
. S decision=0
I deuda>max D
. S decision=0
S ^DECISION(1,"resultado")=decision
"""

TEXTO_LLM = "El solicitante tiene historial limpio; el ratio es alto pero justificado."


def ejecutar():
    """Ejecuta la decisión LEYENDO la PDB.

    OJO: L.execute() NO abre la base; hay que usar execute_sqlite(), que hace
    snapshot de los namespaces referenciados y persiste el diff. Con execute()
    a secas las globals llegan vacías y la decisión sale siempre igual: es un
    fallo silencioso que parece "las reglas no cambian nada".
    """
    return L.execute_sqlite(PROGRAMA, gas_limit=2_000_000_000)


def main():
    print("=== 0. Preparar reglas y caché LLM ===")
    d_reglas = grabar_reglas(pdb, "credito", {"max_deuda": 10000, "umbral": 0.4})
    reglas = leer_reglas(pdb, "credito")
    print(f"   reglas: { {k: v for k, v in reglas.items() if k not in ('updated_at',)} }")
    print(f"   digest de reglas: {d_reglas[:16]}")

    # solicitud de prueba: ratio 0.5 (> 0.4) -> denegar
    pdb.tool_set({"ns": "SOLICITUD", "subs": [1, "deuda"], "value": 5000})
    pdb.tool_set({"ns": "SOLICITUD", "subs": [1, "ingreso"], "value": 10000})

    clave = clave_llm("modelo-a", "evalua esta solicitud", {"temp": 0})
    grabar_llm(pdb, clave, {"texto": TEXTO_LLM})
    print(f"   clave LLM: {clave[:16]}")

    print("\n=== 1. Emitir certificado y replay ===")
    r1 = ejecutar()
    respuestas = [{"clave": clave, "modelo": "modelo-a", "texto": TEXTO_LLM}]
    cert = emitir("credito", PROGRAMA, r1, d_reglas, respuestas, modelo="modelo-a")
    print(f"   decision = {[g['value'] for g in r1['globals'] if g['ns'] == 'DECISION']}")
    print(f"   firma    = {cert['firma'][:16]}")
    print(f"   digest   = {cert['digest_estado'][:16]}")

    r2 = ejecutar()
    inf = verificar(cert, r2, leer_reglas(pdb, "credito") and digest_de_reglas(leer_reglas(pdb, "credito")))
    chk(inf["veredicto"] == "ok", f"replay da el mismo resultado (veredicto={inf['veredicto']})")
    chk(inf["firma_valida"], "firma del certificado valida")

    print("\n=== 2. Cambiar una regla -> el replay debe divergir ===")
    # deuda 5000, ingreso 10000 -> ratio 0.5.
    # Con umbral 0.4 -> deniega. Con umbral 0.9 -> CONCEDE. La decision cambia.
    pdb.tool_set({"ns": "SOLICITUD", "subs": [1, "deuda"], "value": 5000})
    pdb.tool_set({"ns": "SOLICITUD", "subs": [1, "ingreso"], "value": 10000})
    d_reglas2 = grabar_reglas(pdb, "credito", {"max_deuda": 10000, "umbral": 0.9})
    r3 = ejecutar()
    inf2 = verificar(cert, r3, d_reglas2)
    dec3 = [g["value"] for g in r3["globals"] if g["ns"] == "DECISION"]
    dec1 = [g["value"] for g in r1["globals"] if g["ns"] == "DECISION"]
    print(f"   decision con umbral 0.4 = {dec1}  (ratio 0.5 > 0.4 -> deniega)")
    print(f"   decision con umbral 0.9 = {dec3}  (ratio 0.5 < 0.9 -> concede)")
    chk(dec1 != dec3, "cambiar el umbral CAMBIA la decision (el caso discrimina)")
    chk(inf2["veredicto"] in ("estado_distinto", "reglas_cambiadas"),
        f"el replay detecta la divergencia (veredicto={inf2['veredicto']})")
    chk(inf2["reglas_iguales"] is False, "el informe detecta que las reglas cambiaron")

    print("\n=== 3. Cambiar el modelo -> la caché ya no sirve ===")
    clave_b = clave_llm("modelo-b", "evalua esta solicitud", {"temp": 0})
    print(f"   clave modelo-a: {clave[:16]}")
    print(f"   clave modelo-b: {clave_b[:16]}")
    chk(clave != clave_b, "cambiar el modelo cambia la clave de caché")
    chk(leer_llm(pdb, clave_b) is None,
        "no hay respuesta cacheada para el modelo nuevo -> el replay no puede reproducirla")

    print("\n=== 4. Manipular el certificado -> firma inválida ===")
    cert_tocado = dict(cert)
    cert_tocado["digest_estado"] = "0" * 64
    inf3 = verificar(cert_tocado, r1)
    chk(inf3["veredicto"] == "firma_invalida",
        f"tocar el certificado se detecta (veredicto={inf3['veredicto']})")

    print("\n=== 5. Contrafactual: qué habría cambiado con otra política ===")
    pdb.tool_set({"ns": "SOLICITUD", "subs": [1, "deuda"], "value": 5000})
    pdb.tool_set({"ns": "SOLICITUD", "subs": [1, "ingreso"], "value": 10000})
    d_pol = diff_politicas(cert, r3)
    print(f"   con umbral 0.9 la decisión {'CAMBIA' if d_pol['cambio'] else 'no cambia'}")
    chk(d_pol["cambio"], "el contrafactual detecta el cambio de decisión")

    shutil.rmtree(_tmp, ignore_errors=True)

    print()
    if fails:
        print(f"FALLO ({len(fails)})")
        for f in fails:
            print(f"   - {f}")
        sys.exit(1)
    print("PASS: el ciclo completo del certificado funciona")


if __name__ == "__main__":
    main()
