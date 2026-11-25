# -*- coding: utf-8 -*-
"""PROTOTIPO B — Replicar ESTADO convergente (LWW + vectores de version).

Modelo: se replica "la clave k1 vale X, con version (ts, contador, nodo)".
No hay historia: el nodo converge al mismo estado aplicando LWW
(Last-Writer-Wins) por timestamp logico mas contador y desempate por nodo.

Mismo escenario que el prototipo A, para comparar con las manos.
"""
import sys, io

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEP = "=" * 76


class Version:
    """Version logica: (reloj de Lamport, nodo). Orden total sin relojes fisicos."""
    __slots__ = ("lamport", "nodo")

    def __init__(self, lamport, nodo):
        self.lamport = lamport
        self.nodo = nodo

    def mayor_que(self, otra):
        if otra is None:
            return True
        if self.lamport != otra.lamport:
            return self.lamport > otra.lamport
        return self.nodo > otra.nodo     # desempate determinista

    def __repr__(self):
        return "v%d@%s" % (self.lamport, self.nodo)


class EstadoNodo:
    """Estado KV con LWW. Convergente por construccion."""

    def __init__(self, nombre):
        self.nombre = nombre
        self.reloj = 0                        # reloj de Lamport
        self.store = {}                       # clave -> (valor, Version)
        self.tombstones = {}                  # clave -> Version del borrado

    def _tic(self):
        self.reloj += 1
        return self.reloj

    def escribir(self, clave, valor):
        v = Version(self._tic(), self.nombre)
        actual = self.store.get(clave)
        if actual and not v.mayor_que(actual[1]):
            return actual[1], False
        self.store[clave] = (valor, v)
        return v, True

    def borrar(self, clave):
        v = Version(self._tic(), self.nombre)
        self.store.pop(clave, None)
        self.tombstones[clave] = v    # el tombstone evita que resucite
        return v

    def estado(self):
        return {k: val for k, (val, _) in self.store.items()}

    def fusionar(self, otro):
        """Merge: aplica LWW por clave, respetando tombstones. Convergente.

        Invariante del store: clave -> (valor, Version). SIEMPRE una tupla.
        """
        cambios = 0
        claves = set(self.store) | set(otro.store) | set(self.tombstones) | set(otro.tombstones)
        for k in claves:
            mi = self.store.get(k)          # (valor, Version) | None
            su = otro.store.get(k)          # (valor, Version) | None
            mi_borrado = self.tombstones.get(k)   # Version | None
            su_borrado = otro.tombstones.get(k)

            # 1) candidato de VALOR: el de Version mayor
            if mi and su:
                ganador_val = mi if mi[1].mayor_que(su[1]) else su
            else:
                ganador_val = mi or su

            # 2) candidato de BORRADO: el de Version mayor
            if mi_borrado and su_borrado:
                ver_bor = mi_borrado if mi_borrado.mayor_que(su_borrado) else su_borrado
            else:
                ver_bor = mi_borrado or su_borrado

            # 3) gana el mas nuevo entre valor y borrado
            if ver_bor and (ganador_val is None or ver_bor.mayor_que(ganador_val[1])):
                if k in self.store:
                    del self.store[k]
                    cambios += 1
                self.tombstones[k] = ver_bor
            elif ganador_val is not None:
                if self.store.get(k) != ganador_val:
                    self.store[k] = ganador_val
                    cambios += 1
                self.tombstones.pop(k, None)

            self.reloj = max(self.reloj, otro.reloj)
        return cambios


print(SEP)
print("PROTOTIPO B — REPLICAR ESTADO (LWW + Lamport)")
print(SEP)

barco = EstadoNodo("BARCO")
hub = EstadoNodo("HUB")

print("\n[1] El barco escribe 3 muestras sin cobertura")
barco.escribir("gps", "lat=41.1")
barco.escribir("gps", "lat=41.2")
barco.escribir("gps", "lat=41.3")
print("    estado del barco: %s" % barco.estado())
print("    ** NO hay historia: solo el ultimo valor **")

print("\n[2] Vuelve la cobertura y sincroniza")
c = hub.fusionar(barco)
print("    hub fusiona: %d cambios -> estado: %s" % (c, hub.estado()))

print("\n[3] MODIFICAR una muestra en el origen")
v, ok = barco.escribir("gps", "lat=41.25")
print("    barco escribe %s (version %r)" % ("lat=41.25", v))
c = hub.fusionar(barco)
print("    hub fusiona: %d cambios -> estado: %s" % (c, hub.estado()))
print("    ** el cambio SI llega **")
print("    pero el valor anterior se PERDIO: no queda rastro")

print("\n[4] BORRAR una muestra")
vb = barco.borrar("gps")
print("    barco borra gps (tombstone %r)" % vb)
c = hub.fusionar(barco)
print("    hub fusiona: %d cambios -> estado: %s" % (c, hub.estado()))
print("    tombstones del hub: %s" % hub.tombstones)
print("    ** el borrado SI se propaga, gracias al tombstone **")

print("\n[5] CONFLICTO: dos barcos escriben la misma clave a la vez")
b1, b2 = EstadoNodo("BARCO-1"), EstadoNodo("BARCO-2")
b1.escribir("gps", "lat=A")
b2.escribir("gps", "lat=B")
print("    BARCO-1: %s   BARCO-2: %s" % (b1.estado(), b2.estado()))
# converger en ambos sentidos
b1c, b2c = EstadoNodo("B1"), EstadoNodo("B2")
for k, vv in b1.store.items(): b1c.store[k] = vv
for k, vv in b2.store.items(): b2c.store[k] = vv
b1c.reloj, b2c.reloj = b1.reloj, b2.reloj
b1c.fusionar(b2); b2c.fusionar(b1)
print("    B1 tras merge: %s" % b1c.estado())
print("    B2 tras merge: %s" % b2c.estado())
print("    convergen: %s (mismo valor en los dos)" % (b1c.estado() == b2c.estado()))
print("    ** UNO GANA EN SILENCIO: se pierde el otro sin avisar **")

print("\n[6] Hueco / muestra perdida")
print("    el modelo de estado NO TIENE el concepto de secuencia.")
print("    Si se pierde una escritura intermedia, el estado final es el mismo.")
print("    ** no se puede detectar que hubo un hueco **")

print()
print(SEP)
print("RESUMEN PROTOTIPO B")
print(SEP)
print("  Cambio de valor   : SI (pero sin rastro del anterior)")
print("  Borrado           : SI (con tombstone, obligatorio)")
print("  Conflicto         : CONVERGE, pero uno se pierde en silencio")
print("  Hueco             : NO DETECTABLE (no hay concepto de secuencia)")
print("  Estado            : DIRECTO (es lo que se replica)")
print("  Coste             : crece con el ESTADO, no con los hechos")
print("  Compactacion      : barata (tombstones con TTL)")
print(SEP)
