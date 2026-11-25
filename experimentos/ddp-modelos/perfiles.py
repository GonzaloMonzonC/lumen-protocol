# -*- coding: utf-8 -*-
"""PERFIL DE REPLICACION — la configuracion como dato.

Requisito de Gonzalo: nada fijo. Todo configurable, porque "barco o no" depende
del setup. Y la prueba es que configuraciones DISTINTAS cumplan en escenarios
DISTINTOS.

Un perfil responde a estas preguntas, y cada una cambia el comportamiento:

  retencion    : cuanto se guarda antes de compactar (horas, dias, infinito)
  replicacion  : a quien se replica (todos, por interes, por flota, solo hub)
  firma        : por hecho, por bloque, o ninguna
  compactacion : que se hace con los hechos viejos (archivar, sellar, tirar)
  conflicto    : politica al derivar estado (ultimo gana, primero gana, manual)

Se definen perfiles nombrados para los escenarios de los papers, y todos usan
el MISMO codigo: lo unico que cambia es el diccionario.
"""
import json, sys, io, hashlib, time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEP = "=" * 78


# ══════════════════════════════════════════════════════════════════════════
# EL PERFIL — todo configurable, con valores por defecto sensatos
# ══════════════════════════════════════════════════════════════════════════
PERFIL_BASE = {
    # ── Retención ──
    "retencion_modo": "todo",          # "todo" | "ventana" | "sellado"
    "retencion_horas": None,           # solo si modo="ventana"

    # ── Replicación ──
    "replicacion": "todos",            # "todos" | "interes" | "flota" | "hub"
    "replicacion_interes": [],         # topics/series que este nodo sigue

    # ── Firma ──
    "firma": "por_hecho",              # "por_hecho" | "por_bloque" | "ninguna"
    "firma_bloque_n": 100,             # solo si "por_bloque"

    # ── Compactación ──
    "compactacion": "archivar",        # "archivar" | "sellos" | "descartar"

    # ── Conflicto al derivar estado ──
    "conflicto": "ultimo_gana",        # "ultimo_gana" | "primero_gana" | "manual"
}

PERFILES = {
    # Barco: 6 meses sin cobertura posible, hay que probar que no falta nada.
    "barco": {
        "retencion_modo": "ventana",
        "retencion_horas": 24 * 7,      # una semana a bordo; lo viejo se sella
        "replicacion": "flota",
        "firma": "por_bloque",          # 1 Hz x 6 meses: por hecho es carisimo
        "firma_bloque_n": 100,
        "compactacion": "sellos",       # conserva la prueba, tira el detalle
        "conflicto": "ultimo_gana",
    },
    # Enjambre aereo: nodos efimeros, muchos, alta rotacion.
    "enjambre": {
        "retencion_modo": "ventana",
        "retencion_horas": 6,           # un dron no guarda meses
        "replicacion": "interes",       # solo lo que le afecta
        "replicacion_interes": ["posicion", "amenaza"],
        "firma": "por_hecho",           # pocos hechos, firma barata
        "compactacion": "descartar",
        "conflicto": "ultimo_gana",
    },
    # Criptomoneda: registro inmutable, todo se prueba, nada se tira.
    "ledger": {
        "retencion_modo": "todo",       # nunca se borra
        "replicacion": "todos",         # todo el mundo tiene todo
        "firma": "por_hecho",
        "compactacion": "archivar",     # archiva pero conserva
        "conflicto": "manual",          # un doble gasto se detecta, no se resuelve solo
    },
    # Configuracion de agentes: estado, no historia.
    "config": {
        "retencion_modo": "ventana",
        "retencion_horas": 1,           # solo lo reciente
        "replicacion": "hub",
        "firma": "ninguna",
        "compactacion": "descartar",
        "conflicto": "ultimo_gana",
    },
}

ORDEN = ["retencion_modo", "retencion_horas", "replicacion", "replicacion_interes",
         "firma", "firma_bloque_n", "compactacion", "conflicto"]


def perfil(nombre):
    """Devuelve un perfil completo: base + los overrides del escenario."""
    if nombre not in PERFILES:
        raise KeyError("perfil desconocido: %s" % nombre)
    p = dict(PERFIL_BASE)
    p.update(PERFILES[nombre])
    p["nombre"] = nombre
    return p


def mostrar_perfiles():
    print(SEP)
    print("PERFILES DE REPLICACION — mismo codigo, distinta configuracion")
    print(SEP)
    print()
    anchos = max(len(k) for k in ORDEN) + 2
    print("%-*s %-12s %-11s %-16s %-10s %-10s" % (
        anchos, "CLAVE", "barco", "enjambre", "ledger", "config", ""))
    print("-" * 78)
    for k in ORDEN:
        vals = []
        for nom in ("barco", "enjambre", "ledger", "config"):
            v = perfil(nom).get(k)
            if isinstance(v, list):
                v = ",".join(v) if v else "-"
            vals.append(str(v) if v is not None else "-")
        print("%-*s %-12s %-11s %-16s %-10s" % (anchos, k, vals[0], vals[1], vals[2], vals[3]))
    print()
    print("Todos los perfiles usan la MISMA implementacion. Solo cambian los valores.")
    print(SEP)


if __name__ == "__main__":
    mostrar_perfiles()
