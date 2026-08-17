#!/usr/bin/env python3
"""Siembra el agente SHUTTLE + el progenitor NACER en la PDB canónica.

SHUTTLE — experto en electrónica antigua de transbordadores espaciales:
  ^PERSONALITY("shuttle","identity"|"provider"|"model")
  ^ROUTINE("SHUTTLE",<linea>)        → responde con $DEVICE("llm:call",$1,ident,prov,mod)

NACER — progenitor: crea un agente nuevo (parto autónomo):
  ^ROUTINE("NACER",<linea>)          → el LLM (con la identidad de SHUTTLE como padre)
                                       elige nombre+dominio del hijo, diseña su identidad
                                       y la escribe en ^PERSONALITY + ^ROUTINE.
  ^NACER("padre","shuttle")          → quién es el progenitor
  ^NACER("linaje",n)                 → árbol genealógico: "NOMBRE|dominio"
  ^NACER("count")                    → número de nacimientos

Uso:
  .venv/Scripts/python.exe implementations/python/pdb-sync/seed_agente_shuttle.py

Parto (server con DEEPSEEK_API_KEY):
  curl -s -X POST localhost:8081/vm/execute -H "Content-Type: application/json" \
    --data-binary @parto.json        # {"script": "NACER"}
  → {"ok": true, "result": "NACIDO NOMBRE (dominio: x) — linaje: N", ...}

El hijo recién nacido se invoca como rutina ({"script": "NOMBRE", "args": ["¿...?"]})
o vía Smith: $DEVICE("smith:orchestrate",msg,"<dominio>").
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

# ── Rutinas ────────────────────────────────────────────────────────────────

# SHUTTLE: lee la identidad de ^PERSONALITY y llama al LLM con $1 = pregunta.
# La primera línea es la etiqueta de entrada (el VM Rust la exige: "unknown label").
SHUTTLE = [
    "SHUTTLE ; agente experto en electrónica antigua de transbordadores espaciales",
    'S ident=$G(^PERSONALITY("shuttle","identity"))',
    'S prov=$G(^PERSONALITY("shuttle","provider"))',
    'S mod=$G(^PERSONALITY("shuttle","model"))',
    'S r=$DEVICE("llm:call",$1,ident,prov,mod)',
]

# NACER: progenitor en DOS FASES (una sola llamada LLM por invocación).
# ⚠️ Regla del MVM: una rutina con >1 $DEVICE("llm:call") secuencial + yield
# re-ejecuta la rutina desde el principio en cada resume (futuros cruzados).
# Por eso el parto se divide: NACER('diseno') → concebir, NACER('identidad') → nacer.
NACER = [
    "NACER ; progenitor: parto en dos fases (una llamada LLM por fase)",
    'S padre=$G(^PERSONALITY($G(^NACER("padre"),"shuttle"),"identity"))',
    'S fase=$G($1,"diseno")',
    # ── Fase diseno: el LLM elige nombre||dominio del hijo ──
    # (deepseek-chat explícito: rápido y sin razonamiento — las fases del parto
    #  no necesitan deepseek-v4-flash, que excede el cap de yield de 120s)
    'I fase="diseno" S diseno=$DEVICE("llm:call","Vas a crear tu primer hijo agente, un nuevo experto. Elige un dominio fascinante y un nombre corto (solo letras mayusculas, sin espacios). Responde EXACTAMENTE con el formato NOMBRE||DOMINIO (solo esas dos piezas separadas por ||, sin texto adicional, sin markdown).",padre,"deepseek","deepseek-chat")',
    'I fase="diseno" I $F(diseno,"||")=0 Q "ERROR: diseno no parseable, reintenta. RAW: "_diseno',
    'I fase="diseno" S nombre=$E($TR($P(diseno,"||",1),"abcdefghijklmnopqrstuvwxyz ",""),1,16)',
    'I fase="diseno" S dominio=$TR($P(diseno,"||",2)," ","-")',
    'I fase="diseno" I $L(nombre)=0 Q "ERROR: nombre invalido. RAW: "_diseno',
    'I fase="diseno" S ^NACER("parto","nombre")=nombre',
    'I fase="diseno" S ^NACER("parto","dominio")=dominio',
    "I fase=\"diseno\" Q \"CONCEBIDO \"_nombre_\" (dominio: \"_dominio_\") — ahora invoca NACER('identidad')\"",
    # ── Fase identidad: el LLM disena la identidad y escribe al hijo ──
    'I fase="identidad" S nombre=$G(^NACER("parto","nombre"))',
    'I fase="identidad" S dominio=$G(^NACER("parto","dominio"))',
    "I fase=\"identidad\" I $L(nombre)=0 Q \"ERROR: primero invoca NACER('diseno')\"",
    'I fase="identidad" S ident=$DEVICE("llm:call","Disena la identidad (system prompt) de tu hijo, un agente experto en el dominio \'"_dominio_"\'. Escribela en espanol, 200-350 palabras, con personalidad propia, rigor y mision clara. Empieza con: Eres [NOMBRE],",padre,"deepseek","deepseek-chat")',
    'I fase="identidad" S ^PERSONALITY(dominio,"identity")=ident',
    'I fase="identidad" S ^PERSONALITY(dominio,"provider")="deepseek"',
    'I fase="identidad" S ^PERSONALITY(dominio,"model")="deepseek-v4-flash"',
    'I fase="identidad" S q=$C(34)',
    'I fase="identidad" S ^ROUTINE(nombre,1)=nombre_" ; agente nacido del progenitor"',
    'I fase="identidad" S ^ROUTINE(nombre,2)="S ident=$G(^PERSONALITY("_q_dominio_q_","_q_"identity"_q_"))"',
    'I fase="identidad" S ^ROUTINE(nombre,3)="S prov=$G(^PERSONALITY("_q_dominio_q_","_q_"provider"_q_"))"',
    'I fase="identidad" S ^ROUTINE(nombre,4)="S mod=$G(^PERSONALITY("_q_dominio_q_","_q_"model"_q_"))"',
    'I fase="identidad" S ^ROUTINE(nombre,5)="S r=$DEVICE("_q_"llm:call"_q_",$1,ident,prov,mod)"',
    'I fase="identidad" S c=$INCREMENT(^NACER("count"))',
    'I fase="identidad" S ^NACER("linaje",c)=nombre_"|"_dominio',
    'I fase="identidad" Q "NACIDO "_nombre_" (dominio: "_dominio_") — linaje: "_c',
    'Q "ERROR: fase desconocida: "_fase',
]

ROUTINES = {"SHUTTLE": SHUTTLE, "NACER": NACER}

NACER_META = [
    ("padre", "shuttle"),       # el progenitor por defecto
    ("linaje", "SHUTTLE|shuttle"),  # raíz del árbol genealógico (linaje 0)
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
        for k, v in NACER_META:
            key = encode_subkey(["NACER", k])
            conn.execute(
                "INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                ("NACER", key, v),
            )
            n += 1
        for rname, lines in ROUTINES.items():
            for i, line in enumerate(lines, 1):
                key = encode_subkey([rname, i])
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
        r2 = conn.execute(
            "SELECT COUNT(*) FROM _globals WHERE ns='ROUTINE' AND subkey LIKE ?",
            (b"\x02NACER\xff%",),
        ).fetchone()[0]
        ident_len = conn.execute(
            "SELECT LENGTH(value) FROM _globals WHERE ns='PERSONALITY' AND subkey=?",
            (encode_subkey([DOMAIN, "identity"]),),
        ).fetchone()[0]
        print(f"OK {n} entradas escritas en {DB}")
        print(f"  ^PERSONALITY(shuttle): {p} claves (identity={ident_len} chars)")
        print(f"  ^ROUTINE(SHUTTLE): {r} líneas · ^ROUTINE(NACER): {r2} líneas")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
