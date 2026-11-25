# -*- coding: utf-8 -*-
"""PRUEBA: que pasa HOY si dos nodos escriben la misma serie durante una particion.

No es un diseno: es la demostracion de que el caso esta sin cubrir.
Dos barcos con el mismo nombre (por error de configuracion) o un nodo que
se re-instala y vuelve con la numeracion a cero.
"""
import hashlib, sys, io

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEP = "=" * 76

def h(prev, valor):
    return hashlib.sha256((prev + valor).encode()).hexdigest()


class Nodo:
    def __init__(self, nombre):
        self.nombre = nombre
        self.hechos = {}     # (nodo, serie, seq) -> dict


print(SEP)
print("SPLIT-BRAIN — estado actual del codigo")
print(SEP)

# Escenario: DOS barcos escriben "BARCO-A" (mismo nombre, o nodo re-instalado).
# Durante una particion no se ven. Al reconectar, el hub recibe de los dos.
a = Nodo("A")
b = Nodo("B")

for i in range(3):
    a.hechos[("BARCO-A", "gps", i)] = {
        "valor": "lat=41.%d" % i, "nodo": "BARCO-A", "seq": i}
    b.hechos[("BARCO-A", "gps", i)] = {
        "valor": "lat=99.%d" % i, "nodo": "BARCO-A", "seq": i}

print("\n[1] Durante la particion, los dos escriben la MISMA serie y los MISMOS seq")
print("    nodo A: %s" % [f['valor'] for f in a.hechos.values()])
print("    nodo B: %s" % [f['valor'] for f in b.hechos.values()])

print("\n[2] Al reconectar, el hub recibe ambos")
hub = Nodo("HUB")
recibidos = list(a.hechos.values()) + list(b.hechos.values())
vistos = {}
descartados = 0
for f in recibidos:
    k = (f["nodo"], "gps", f["seq"])
    if k in vistos:
        # El segundo con la misma identidad se DESCARTA en silencio.
        descartados += 1
        continue
    vistos[k] = f

print("    hechos enviados: %d" % len(recibidos))
print("    hechos guardados: %d" % len(vistos))
print("    DESCARTADOS EN SILENCIO: %d" % descartados)

print("\n[3] Que quedo en el hub")
for k in sorted(vistos):
    print("    %s = %s" % (k, vistos[k]["valor"]))

print()
print(SEP)
print("DIAGNOSTICO")
print(SEP)
print("""
La identidad del hecho es (nodo, serie, seq). Si dos nodos creen ser el MISMO
nodo, sus hechos colisionan y el segundo se pierde.

Hay DOS causas distintas y necesitan arreglos distintos:

  a) MISMO BARCO, dos instancias. Un nodo que se re-instala, o que arranca dos
     veces por error, vuelve con seq=0 y su historia choca con la anterior.
     Arreglo: identidad de INSTANCIA (no solo de barco) + epoch.

  b) PARTICION real con dos hubs. Dos hubs aceptan escrituras del mismo barco
     y ambos emiten seq. Al juntarse, la numeracion se solapa.
     Arreglo: epoch/term por par, y rechazo del que tenga epoch viejo.

Lo que hay hoy: el segundo se descarta sin aviso. Sin error, sin log, sin
conflicto detectado. Es el mismo patron de fallo que ya aparecio con el sync de
PDB (perdida silenciosa), pero en la capa de hechos.
""")
print(SEP)
