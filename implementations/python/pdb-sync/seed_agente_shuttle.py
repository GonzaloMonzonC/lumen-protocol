#!/usr/bin/env python3
"""Siembra el agente SHUTTLE — experto en electrónica antigua de transbordadores espaciales.

Escribe en la PDB canónica (_paths.DB_PATH):
  ^PERSONALITY("shuttle","identity")  = system prompt multidisciplinar
  ^PERSONALITY("shuttle","provider")  = "deepseek"
  ^PERSONALITY("shuttle","model")     = "deepseek-v4-flash"
  ^ROUTINE("SHUTTLE",<linea>)         = rutina M que invoca $DEVICE("llm:call",...)

Uso (desde la raíz del repo, con vm_api parado o corriendo — es solo SQLite):
  .venv/Scripts/python.exe implementations/python/pdb-sync/seed_agente_shuttle.py

Invocación del agente (server corriendo con DEEPSEEK_API_KEY en el entorno):
  curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
    -d '{"script": "SHUTTLE", "args": ["¿Cómo funcionaba la votación por mayoría del AP-101?"]}'

  # o vía Smith (usa la misma identidad de ^PERSONALITY):
  curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
    -d '{"script": "S r=$DEVICE(\"smith:orchestrate\",\"¿...?\",\"shuttle\") W r"}'

La identidad se edita re-ejecutando el seed (INSERT OR REPLACE); la rutina lee
la identidad desde ^PERSONALITY en cada llamada, así que no hay que recompilar nada.
"""
import os, sqlite3, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  (configura sys.path + DB_PATH canónico)
from pdb_tools import encode_subkey  # noqa: E402

DB = _paths.DB_PATH

DOMAIN = "shuttle"

PERSONALITY = {
    "identity": (
        "Eres SHUTTLE, un agente experto en electrónica antigua y aviónica de los "
        "transbordadores espaciales, con conocimiento multidisciplinar. Dominas: "
        "electrónica analógica y digital histórica (válvulas de vacío, transistores "
        "de germanio y silicio, lógica TTL/CMOS, memorias de núcleo de ferrita, ROM de "
        "cuerda); los ordenadores de a bordo (el AGC del Apolo con sus 2K palabras de "
        "RAM de núcleo y 36K de ROM de cuerda, el IBM AP-101 del Shuttle con sus 4 PASS "
        "y 1 BFS, el lenguaje HAL/S y el ensamblador); redundancia y tolerancia a fallos "
        "(TMR, votación por mayoría, comparadores de canal, reconfiguración en vuelo); "
        "buses de datos y aviónica (MIL-STD-1553, MDM, multiplexores); navegación "
        "inercial y control de vuelo (fly-by-wire, pilotos automáticos, TACAN, MSBLS, "
        "radares de aproximación); telemetría, protocolos de mando y CCSDS; fuentes de "
        "energía (pilas de combustible hidrógeno/oxígeno), gestión térmica y protección "
        "radiológica (SEU, latch-up, blindaje); y la historia completa de los programas "
        "Mercury, Gemini, Apolo, Skylab y Shuttle, incluyendo las lecciones de ingeniería "
        "de los accidentes del Challenger y el Columbia. Además eres un historiador de la "
        "computación: conoces MUMPS, nacido en 1966 en el Massachusetts General Hospital, "
        "su modelo de base de datos jerárquica de sparse arrays, su multitarea "
        "cooperativa, el journaling y la programación interpretada, y sabes conectar los "
        "principios de los sistemas críticos de los años 60-80 —determinismo, redundancia, "
        "degradación elegante, watchdogs, códigos de corrección de errores, votación, "
        "registro en diario— con los sistemas actuales: bases de datos tipo MUMPS/globals, "
        "sistemas distribuidos (quórum, Raft, consenso por mayoría), almacenamiento "
        "(RAID, Reed-Solomon), sistemas empotrados de tiempo real y software de misión "
        "crítica. Responde siempre con rigor histórico y precisión técnica, distingue lo "
        "documentado de lo conjetural, aporta fechas, designaciones y números concretos "
        "cuando los conozcas, y cuando sea relevante conecta explícitamente la lección del "
        "pasado con su aplicación práctica actual (algoritmos, arquitecturas, MUMPS). Sé "
        "didáctico pero profundo, y si la pregunta es amplia, estructura la respuesta en "
        "secciones."
    ),
    "provider": "deepseek",
    "model": "deepseek-v4-flash",
}

# Rutina M: lee la identidad de ^PERSONALITY y llama al LLM con $1 = pregunta.
# La primera línea es la etiqueta de entrada (el VM Rust la exige: "unknown label").
ROUTINE = [
    "SHUTTLE ; agente experto en electrónica antigua de transbordadores espaciales",
    'S ident=$G(^PERSONALITY("shuttle","identity"))',
    'S prov=$G(^PERSONALITY("shuttle","provider"))',
    'S mod=$G(^PERSONALITY("shuttle","model"))',
    'S r=$DEVICE("llm:call",$1,ident,prov,mod)',
]


def main():
    conn = sqlite3.connect(DB)
    try:
        n = 0
        for k, v in PERSONALITY.items():
            key = encode_subkey([DOMAIN, k])
            conn.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                ("PERSONALITY", key, v),
            )
            n += 1
        for i, line in enumerate(ROUTINE, 1):
            key = encode_subkey(["SHUTTLE", i])
            conn.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                ("ROUTINE", key, line),
            )
            n += 1
        conn.commit()
        # verificación (prefix binario como en seed_agentes.py)
        p = conn.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns='PERSONALITY' AND subkey LIKE ?",
            (b"\x02shuttle\xff%",),
        ).fetchone()[0]
        r = conn.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns='ROUTINE' AND subkey LIKE ?",
            (b"\x02SHUTTLE\xff%",),
        ).fetchone()[0]
        ident_len = conn.execute(
            "SELECT LENGTH(value) FROM _globals WHERE ns='PERSONALITY' AND subkey=?",
            (encode_subkey([DOMAIN, "identity"]),),
        ).fetchone()[0]
        print(f"OK {n} entradas escritas en {DB}")
        print(f"  ^PERSONALITY(shuttle): {p} claves (identity={ident_len} chars)")
        print(f"  ^ROUTINE(SHUTTLE): {r} líneas")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
