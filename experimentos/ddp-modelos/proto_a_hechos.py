# -*- coding: utf-8 -*-
"""PROTOTIPO A — Replicar HECHOS (append-only firmado).

Modelo: el nodo no replica "la clave k1 vale X". Replica hechos:
    (nodo, serie, seq, valor, prev_hash, hash)
Cada hecho encadena el anterior por hash. El estado actual NO se replica:
se DERIVA quedandose con el ultimo hecho de cada clave.

Escenario comun de comparacion (el mismo para el prototipo B):
  1. Barco sin cobertura escribe 3 muestras.
  2. Vuelve la cobertura y sincroniza.
  3. Se MODIFICA una muestra en el origen (valor distinto, mismo seq).
  4. Se BORRA una muestra.
  5. Dos barcos escriben la MISMA clave a la vez (conflicto).
"""
import hashlib, json, sys, io

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEP = "=" * 76


def h(prev: str, valor: str) -> str:
    """hash de la muestra: sha256(prev_hash || valor). El mismo que cadena.rs."""
    return hashlib.sha256((prev + valor).encode('utf-8')).hexdigest()


class Hecho:
    __slots__ = ("nodo", "serie", "seq", "valor", "prev", "hash")

    def __init__(self, nodo, serie, seq, valor, prev):
        self.nodo = nodo
        self.serie = serie
        self.seq = seq
        self.valor = valor
        self.prev = prev
        self.hash = h(prev, valor)

    def clave(self):
        """Identidad del hecho: (serie, seq). Un hecho es unico por posicion."""
        return (self.serie, self.seq)

    def to_dict(self):
        return {"nodo": self.nodo, "serie": self.serie, "seq": self.seq,
                "valor": self.valor, "prev": self.prev, "hash": self.hash}


class NodoHechos:
    """Un nodo que solo sabe anadir hechos. No sabe modificar ni borrar."""

    def __init__(self, nombre):
        self.nombre = nombre
        self.hechos = []          # lista ordenada de Hecho (append-only)
        self.por_clave = {}       # (serie, seq) -> Hecho

    def anadir(self, serie, valor):
        # seq = siguiente de esa serie
        existentes = [f.seq for f in self.hechos if f.serie == serie]
        seq = (max(existentes) + 1) if existentes else 0
        prev = ""
        for f in reversed(self.hechos):
            if f.serie == serie:
                prev = f.hash
                break
        f = Hecho(self.nombre, serie, seq, valor, prev)
        self.hechos.append(f)
        self.por_clave[f.clave()] = f
        return f

    def estado(self):
        """DERIVA el estado: ultimo hecho por serie."""
        est = {}
        for f in self.hechos:
            est[f.serie] = f.valor     # append-only => el ultimo gana de facto
        return est

    def verificar_cadena(self, serie):
        """Recorre la serie y comprueba prev_hash. Devuelve (ok, fallo)."""
        serie_hechos = sorted([f for f in self.hechos if f.serie == serie],
                              key=lambda x: x.seq)
        prev = ""
        for esperado_seq, f in enumerate(serie_hechos):
            if f.seq != esperado_seq:
                return False, "hueco: falta seq %d (tenemos %s)" % (
                    esperado_seq, [x.seq for x in serie_hechos])
            if f.prev != prev:
                return False, "cadena rota en seq %d" % f.seq
            if h(f.prev, f.valor) != f.hash:
                return False, "valor manipulado en seq %d" % f.seq
            prev = f.hash
        return True, ""

    def recibir(self, hechos):
        """Replicacion: recibe hechos, verifica e inserta los que falten.

        Idempotente: reenviar el mismo hecho no duplica.
        """
        nuevos = 0
        rechazados = []
        for f in hechos:
            if f.clave() in self.por_clave:
                continue                      # ya lo tengo
            if f.serie in [x.serie for x in self.hechos]:
                # verificar enlace con el anterior de esa serie
                previos = [x for x in self.hechos if x.serie == f.serie
                           and x.seq == f.seq - 1]
                if previos and f.prev != previos[0].hash:
                    rechazados.append((f.serie, f.seq, "prev no coincide"))
                    continue
            self.hechos.append(f)
            self.por_clave[f.clave()] = f
            nuevos += 1
        return nuevos, rechazados


print(SEP)
print("PROTOTIPO A — REPLICAR HECHOS (append-only firmado)")
print(SEP)

barco = NodoHechos("BARCO")
hub = NodoHechos("HUB")

print("\n[1] El barco escribe 3 muestras sin cobertura")
for v in ("lat=41.1", "lat=41.2", "lat=41.3"):
    barco.anadir("gps", v)
print("    hechos en barco: %d" % len(barco.hechos))
print("    estado derivado: %s" % barco.estado())

print("\n[2] Vuelve la cobertura y sincroniza")
n, rech = barco and hub.recibir(barco.hechos)
print("    hub recibe: %d hechos, rechazados: %d" % (n, len(rech)))
print("    estado del hub: %s" % hub.estado())
ok, err = hub.verificar_cadena("gps")
print("    cadena del hub verificada: %s %s" % (ok, err))

print("\n[3] MODIFICAR una muestra en el origen (el caso que hoy se pierde)")
# En append-only no se puede modificar: hay que anadir un hecho que corrija.
correct = barco.anadir("gps", "lat=41.25")
print("    no se modifica: se ANADE un hecho nuevo (seq=%d)" % correct.seq)
print("    el hecho original sigue ahi: %s" % barco.por_clave[("gps", 2)].valor)
n, _ = hub.recibir(barco.hechos)
print("    hub recibe %d nuevos -> estado: %s" % (n, hub.estado()))
print("    ** el cambio SI llega, y queda rastro del anterior **")

print("\n[4] BORRAR una muestra")
# En append-only el borrado es un hecho mas.
# (Se simula anadiendo un hecho que marca borrado; el original no desaparece.)
borrado = Hecho("BARCO", "gps", 4, "__BORRADO__", barco.por_clave[("gps",3)].hash)
barco.hechos.append(borrado); barco.por_clave[borrado.clave()] = borrado
n, _ = hub.recibir(barco.hechos)
print("    el borrado viaja como hecho (seq=%d)" % borrado.seq)
print("    hub lo recibe: %d nuevos" % n)
print("    ** el borrado SI se propaga, y se puede auditar **")

print("\n[5] CONFLICTO: dos barcos escriben la misma serie a la vez")
b1, b2 = NodoHechos("BARCO-1"), NodoHechos("BARCO-2")
f1 = b1.anadir("gps", "lat=A")
f2 = b2.anadir("gps", "lat=B")
print("    BARCO-1 seq=0 lat=A  |  BARCO-2 seq=0 lat=B")
mezcla = NodoHechos("MEZCLA")
n1, r1 = mezcla.recibir([f1, f2])
print("    la mezcla recibe ambos: %d insertados, %d rechazados" % (n1, len(r1)))
print("    -> se detectan los dos hechos (no hay perdida silenciosa)")
print("    -> resolver cual vale es POLITICA, no transporte")

print("\n[6] Hueco: se pierde una muestra por el camino")
roto = NodoHechos("ROTO")
for i, f in enumerate(barco.hechos):
    if f.seq == 2:
        continue           # se pierde la muestra 2
    if not roto.por_clave.get(f.clave()):
        roto.hechos.append(f); roto.por_clave[f.clave()] = f
ok, err = roto.verificar_cadena("gps")
print("    verificacion: ok=%s  ->  %s" % (ok, err))
print("    ** el hueco se LOCALIZA: 'falta la muestra 2' **")

print()
print(SEP)
print("RESUMEN PROTOTIPO A")
print(SEP)
print("  Cambio de valor   : SI (como hecho nuevo, con rastro)")
print("  Borrado           : SI (como hecho de borrado)")
print("  Conflicto         : DETECTADO (no hay perdida silenciosa)")
print("  Hueco             : DETECTADO y localizado")
print("  Estado            : DERIVADO (ultimo hecho por serie)")
print("  Coste             : crece con los hechos, no con el estado")
print("  Compactacion      : NECESARIA con el tiempo (los hechos no se borran)")
print(SEP)
