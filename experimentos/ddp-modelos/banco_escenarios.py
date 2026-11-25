# -*- coding: utf-8 -*-
"""BANCO DE PRUEBAS — cada configuracion cumple en su escenario.

Requisito de Gonzalo (4): "que diferentes configuraciones vayan bien, y cumplan
para los diferentes escenarios".

No basta con que no peten: cada escenario tiene CRITERIOS DE CUMPLIMIENTO y se
comprueba uno por uno. Si un perfil no cumple su criterio, la prueba falla.
"""
import sys, io
from perfiles import perfil
from motor import Motor

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEP = "=" * 78
fallos = []


def check(nombre, cond, detalle=""):
    marca = "OK  " if cond else "FALLO"
    print("    [%s] %s%s" % (marca, nombre, ("  -> " + detalle) if detalle else ""))
    if not cond:
        fallos.append(nombre)
    return cond


# ══════════════════════════════════════════════════════════════════════════
# ESCENARIO 1 · BARCO — 6 h sin cobertura, luego sube todo
# ══════════════════════════════════════════════════════════════════════════
def escenario_barco():
    print(SEP)
    print("ESCENARIO 1 · BARCO — 6 h sin cobertura (21.600 muestras a 1 Hz)")
    print("Perfil: retencion ventana 168h, firma por bloque 100, sellos, flota")
    print(SEP)
    p = perfil("barco")
    barco = Motor("BARCO-A", p)
    hub = Motor("HUB-FLOTA", p)

    # 6 horas a 1 Hz, con un ts por segundo real
    N = 21600
    for i in range(N):
        barco.escribir("gps", "lat=%.6f" % (41.0 + i * 1e-6), ts=i, serie="gps")
    print("    barco: %d muestras escritas (ts 0..%d s = 6 h)" % (N, N - 1))

    check("firma por bloque, no por hecho",
          barco.estadisticas()["firmados"] == N // 100,
          "%d firmas para %d muestras" % (barco.estadisticas()["firmados"], N))

    # sincroniza al recuperar cobertura
    n, _ = hub.recibir(barco)
    check("el hub recibe todas las muestras", n == N, "%d de %d" % (n, N))

    # verificar la cadena: no falta ninguna
    lista = barco.series[("BARCO-A", "gps")]
    ok_cadena = all(lista[i].prev == (lista[i-1].hash if i else "") for i in range(len(lista)))
    check("cadena intacta sin huecos", ok_cadena)

    # 30 dias despues (en segundos): la ventana es 168 h = 7 dias, asi que lo
    # anterior a los ultimos 7 dias ya se puede archivar.
    barco.compactar(ahora=30 * 24 * 3600)
    st = barco.estadisticas()
    check("compacta y conserva el sello de lo archivado",
          st["descartados"] > 0 and st["bloques"] > 0,
          "%d descartados, %d bloques" % (st["descartados"], st["bloques"]))
    check("el estado sigue siendo correcto tras compactar",
          barco.estado().get("gps", "").startswith("lat=41.0"),
          str(barco.estado().get("gps"))[:30])
    return len(fallos) == 0


# ══════════════════════════════════════════════════════════════════════════
# ESCENARIO 2 · ENJAMBRE — nodos efimeros, solo lo que les interesa
# ══════════════════════════════════════════════════════════════════════════
def escenario_enjambre():
    print()
    print(SEP)
    print("ESCENARIO 2 · ENJAMBRE AEREO — nodos efimeros, replicacion por interes")
    print("Perfil: retencion 6h, interes(posicion,amenaza), firma por hecho, descartar")
    print(SEP)
    p = perfil("enjambre")
    dron1 = Motor("DRON-1", p)
    dron2 = Motor("DRON-2", p)

    dron1.escribir("pos", "41.1,1.2", ts=0, serie="posicion")
    dron1.escribir("bat", "87%", ts=1, serie="bateria")        # NO interesa
    dron1.escribir("threat", "ninguna", ts=2, serie="amenaza")

    n, motivo = dron2.recibir(dron1)
    check("replica (hay series de interes)", n > 0 or "rechazado" not in motivo,
          "%d recibidos" % n)

    # un dron que solo sigue 'bateria' debe rechazar
    p2 = perfil("enjambre")
    p2["replicacion_interes"] = ["bateria"]
    dron3 = Motor("DRON-3", p2)
    dron_otro = Motor("DRON-4", perfil("enjambre"))
    dron_otro.escribir("pos", "1,1", serie="posicion")
    n3, motivo3 = dron3.recibir(dron_otro)
    check("rechaza lo que no le interesa", n3 == 0, motivo3 or "%d recibidos" % n3)

    check("firma por hecho (pocos hechos, barato)",
          dron1.estadisticas()["firmados"] == dron1.estadisticas()["hechos"],
          "%d firmas para %d hechos" % (
              dron1.estadisticas()["firmados"], dron1.estadisticas()["hechos"]))
    return len(fallos) == 0


# ══════════════════════════════════════════════════════════════════════════
# ESCENARIO 3 · LEDGER — nada se borra, un doble gasto se DETECTA
# ══════════════════════════════════════════════════════════════════════════
def escenario_ledger():
    print()
    print(SEP)
    print("ESCENARIO 3 · CRIPTOMONEDA — registro inmutable, conflicto detectado")
    print("Perfil: retencion total, firma por hecho, conflicto MANUAL")
    print(SEP)
    p = perfil("ledger")
    nodo1 = Motor("NODO-1", p)
    nodo2 = Motor("NODO-2", p)

    nodo1.escribir("saldo:A", "100", ts=1)
    nodo1.escribir("pago:A->B", "60", ts=2)
    n, _ = nodo2.recibir(nodo1)
    check("replica todo", n == 2, "%d hechos" % n)

    # doble gasto: dos nodos gastan lo mismo
    nodo3 = Motor("NODO-3", p)
    nodo3.escribir("pago:A->C", "60", ts=3)
    nodo2.recibir(nodo3)
    est = nodo2.estado()
    check("el conflicto se DETECTA, no se resuelve solo",
          any("CONFLICTO" in str(v) for v in est.values()),
          str(est.get("pago:A->B", "sin conflicto"))[:40])

    antes = nodo2.estadisticas()["hechos"]
    nodo2.compactar(ahora=10 ** 9)
    check("nada se borra nunca",
          nodo2.estadisticas()["hechos"] == antes,
          "%d hechos siguen" % antes)
    return len(fallos) == 0


# ══════════════════════════════════════════════════════════════════════════
# ESCENARIO 4 · CONFIG — estado puro, sin historia, solo con el hub
# ══════════════════════════════════════════════════════════════════════════
def escenario_config():
    print()
    print(SEP)
    print("ESCENARIO 4 · CONFIGURACION DE AGENTES — estado, no historia")
    print("Perfil: retencion 1h, solo hub, sin firma, descartar")
    print(SEP)
    p = perfil("config")
    agente = Motor("AGENTE", p)
    hub = Motor("HUB", p)

    agente.escribir("temperatura", "0.7", ts=0)
    agente.escribir("temperatura", "0.9", ts=1)
    check("el estado es el ultimo valor", agente.estado().get("temperatura") == "0.9",
          str(agente.estado()))

    check("sin firma (no hace falta probar autoría)",
          agente.estadisticas()["firmados"] == 0)

    n, _ = hub.recibir(agente)
    check("replica al hub", n > 0, "%d recibidos" % n)

    agente.compactar(ahora=3 * 3600)   # 3 h despues; la ventana es de 1 h
    check("descarta lo viejo sin sellar",
          agente.estadisticas()["descartados"] > 0 and
          agente.estadisticas()["bloques"] == 0,
          "%d descartados, %d bloques" % (
              agente.estadisticas()["descartados"], agente.estadisticas()["bloques"]))
    return len(fallos) == 0


# ══════════════════════════════════════════════════════════════════════════
print(SEP)
print("BANCO DE PRUEBAS DE CONFIGURACIONES")
print(SEP)
print()

escenario_barco()
escenario_enjambre()
escenario_ledger()
escenario_config()

print()
print(SEP)
if fallos:
    print("RESULTADO: %d FALLOS" % len(fallos))
    for f in fallos:
        print("  - %s" % f)
else:
    print("RESULTADO: las 4 configuraciones cumplen en su escenario")
    print()
    print("  barco     -> prueba completitud con firmas por bloque y sellos")
    print("  enjambre  -> filtra por interes y firma cada hecho")
    print("  ledger    -> conserva todo y DETECTA el conflicto en vez de resolverlo")
    print("  config    -> solo estado, sin firma ni historia")
    print()
    print("  Cuatro politicas opuestas, la MISMA implementacion.")
print(SEP)
sys.exit(1 if fallos else 0)
