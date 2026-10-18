#!/usr/bin/env python3
"""gas.py — gas como FLUJO, no como acumulador de por vida.

EL PROBLEMA REAL
----------------
Tratar el gas como un contador único que se agota hace que cualquier operación
masiva sea imposible: importar un millón de registros NO cabe en ningún número,
porque el coste crece con los datos.

Y el corte no se reportaba: `execution` salía "completed" con el estado a medias
(medido: 5.000 escrituras -> 1 global devuelta).

LAS DOS PREGUNTAS QUE HAY QUE SEPARAR
-------------------------------------
1. ¿Cuánto puede costar UN turno de ejecución?   -> `gas_limit` (el slice)
2. ¿Cuánto puede costar la operación ENTERA?     -> `gas_budget` (0 = sin tope)

La máquina ya tiene las dos piezas (`gas_limit` y `gas_budget` en vm.rs), pero el
wrapper solo usaba la primera como tope duro. Para millones de registros:

  - `gas_limit` debe dimensionarse por turno (el slice), NO por la operación
  - `gas_budget` = 0 (sin tope de por vida) para trabajos de confianza
  - cuando el slice se agota, el motor devuelve `Yielded` y se REANUDA:
    el bucle de reanudación ya existe en lumen_mlight.execute (para `yielded`)

NIVELES: cuánto se permite por TURNO, no cuánto en total
--------------------------------------------------------

    sandbox    código de terceros: turno pequeño, sin reanudar más allá del tope
    normal     agente propio: turnos generosos, reanuda hasta terminar
    trusted    operador/CI: turnos grandes, reanuda hasta terminar
    unlimited  interno: sin tope de turno ni de total

REGLA: el nivel fija el TAMAÑO DEL TURNO y cuántas veces se puede reanudar. No
fija cuánto puede costar la operación completa (eso lo decide `gas_budget`).

Así, un import de un millón de registros corre en muchos turnos sin agotar nada,
y el gas sigue protegiendo de bucles infinitos (que es para lo que sirve: un
FRENO, no un precio — ver doc 11).
"""
from __future__ import annotations

import os

# ── Niveles: (gas por TURNO, máx. turnos; None = sin tope) ──────────────────
# El coste total permitido ≈ turno × turnos. `None` en turnos = reanuda siempre.
NIVELES = {
    "sandbox":   {"turno": 10_000,      "turnos": 10,       "total": 100_000},
    "normal":    {"turno": 10_000_000,  "turnos": None,     "total": None},
    "trusted":   {"turno": 1_000_000_000, "turnos": None,   "total": None},
    "unlimited": {"turno": None,        "turnos": None,     "total": None},
}

_ORDEN = ["sandbox", "normal", "trusted", "unlimited"]
NIVEL_DEFAULT = "normal"
ENV_NIVEL = "LUMEN_GAS_LEVEL"

# Presupuesto total opcional (variable de entorno). 0 o ausente = sin tope.
ENV_BUDGET = "LUMEN_GAS_BUDGET"


def nivel_proceso() -> str:
    """Nivel máximo permitido en este proceso (techo), por entorno."""
    n = (os.environ.get(ENV_NIVEL) or NIVEL_DEFAULT).strip().lower()
    return n if n in NIVELES else NIVEL_DEFAULT


def resolver(nivel_pedido: str | None = None, gas_limit: int | None = None,
             gas_budget: int | None = None) -> dict:
    """Devuelve la config efectiva de gas.

    Claves:
      turno   -> `gas_limit` que se pasa a la FFI (tamaño del slice)
      turnos  -> cuántas veces se puede reanudar (None = sin tope)
      budget  -> tope total acumulado (0 = sin tope)
      nivel   -> nivel aplicado (no puede superar el techo del proceso)
    """
    techo = nivel_proceso()
    pedido = (nivel_pedido or techo).strip().lower()
    if pedido not in NIVELES:
        pedido = NIVEL_DEFAULT

    idx = min(_ORDEN.index(pedido), _ORDEN.index(techo))
    efectivo = _ORDEN[idx]
    cfg = NIVELES[efectivo]

    turno = cfg["turno"] if cfg["turno"] is not None else 2_000_000_000
    if gas_limit is not None and cfg["turno"] is not None:
        turno = min(int(gas_limit), cfg["turno"])
    elif gas_limit is not None:
        turno = int(gas_limit)

    # budget: lo que diga la llamada, o el total del nivel, o la env
    if gas_budget is None:
        budget = cfg["total"] or int(os.environ.get(ENV_BUDGET) or 0)
    else:
        budget = int(gas_budget)
        if cfg["total"]:
            budget = min(budget, cfg["total"]) if budget else cfg["total"]

    return {
        "turno": turno,
        "turnos": cfg["turnos"],
        "budget": budget,
        "nivel": efectivo,
    }


def clasificar_resultado(respuesta: dict) -> dict:
    """Normaliza el resultado: nunca "completed" con el estado a medias.

    IMPORTANTE (lección aprendida a golpes): en el motor, `Execution::Completed`
    significa "el ip llego al final del programa" y NO implica `halted=True`
    (halted solo se pone con HALT/Q explicito). Asi que `halted=False` con
    `completed` es NORMAL, no un corte.

    La señal de corte real es `execution == "yielded"`: el motor la devuelve al
    agotar el turno de gas o al esperar un device. Si tras reanudar sigue
    "yielded", es out_of_gas; si termino, es un final valido.
    """
    out = dict(respuesta or {})
    ex = str(out.get("execution") or "")
    st = out.get("state") or {}

    if ex == "yielded":
        out["execution"] = "out_of_gas"
        out["out_of_gas"] = True
        out["globals_complete"] = False
        out.setdefault("warnings", []).append(
            "estado incompleto: se agoto el turno de gas y no se pudo reanudar. "
            "Sube el nivel de gas o reanuda con state."
        )
    else:
        out["out_of_gas"] = False
        # completed / halted / error son finales
        out["globals_complete"] = ex in ("completed", "halted")
        if ex == "error":
            out.setdefault("warnings", []).append(
                "la ejecucion termino con error; las globals son parciales."
            )
    return out
