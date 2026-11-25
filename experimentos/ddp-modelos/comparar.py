# -*- coding: utf-8 -*-
"""COMPARACION A vs B con las manos — escenario de flota real + coste.

Corrige el fallo visto en A: dos nodos con seq=0 colisionan. La solucion
correcta es que el seq sea POR (nodo, serie), no por serie. Asi dos barcos
pueden escribir el mismo instante sin pisarse.

Mide ademas el coste de cada modelo, que es lo que decide a escala.
"""
import hashlib, sys, io, time

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')

SEP = "=" * 78


def h(prev, valor):
    return hashlib.sha256((prev + valor).encode()).hexdigest()


# ══════════════════════════════════════════════════════════════════════════
# MODELO A corregido — hechos con seq por (nodo, serie)
# ══════════════════════════════════════════════════════════════════════════
class Hechos:
    def __init__(self, nombre):
        self.nombre = nombre
        self.hechos = {}
        self.ultimo_por_clave = {}     # (nodo,serie) -> seq
        self.prev_por_serie = {}       # clave -> ultimo hash por clave logica

    def anadir(self, serie, clave_logica, valor):
        k = (self.nombre, serie)
        seq = self.ultimo_por_clave.get(k, -1) + 1
        self.ultimo_por_clave[k] = seq
        prev = self.prev_por_serie.get(clave_logica, "")
        f = (self.nombre, serie, seq, clave_logica, valor, prev, h(prev, valor))
        self.hechos[(self.nombre, serie, seq)] = f
        self.prev_por_serie[clave_logica] = f[6]
        return f

    def estado(self):
        """Ultimo hecho por clave logica."""
        est = {}
        for f in self.hechos.values():
            _, _, seq, clave, valor, _, _ = f
            if clave not in est or seq >= est[clave][0]:
                est[clave] = (seq, valor)
        return {k: v for k, (_, v) in est.items()}

    def recibir(self, otros):
        nuevos = 0
        for f in otros:
            if f[:3] in self.hechos:
                continue
            self.hechos[f[:3]] = f
            self.ultimo_por_clave[(f[0], f[1])] = max(
                self.ultimo_por_clave.get((f[0], f[1]), -1), f[2])
            nuevos += 1
        return nuevos


# ══════════════════════════════════════════════════════════════════════════
# MODELO B — estado con LWW
# ══════════════════════════════════════════════════════════════════════════
class Estado:
    def __init__(self, nombre):
        self.nombre = nombre
        self.reloj = 0
        self.store = {}
        self.tomb = {}

    def escribir(self, clave, valor):
        self.reloj += 1
        self.store[clave] = (valor, (self.reloj, self.nombre))
        return self.store[clave][1]

    def borrar(self, clave):
        self.reloj += 1
        self.store.pop(clave, None)
        self.tomb[clave] = (self.reloj, self.nombre)

    def estado(self):
        return {k: v for k, (v, _) in self.store.items()}

    def fusionar(self, otro):
        self.reloj = max(self.reloj, otro.reloj)
        for k in set(self.store) | set(otro.store):
            mi, su = self.store.get(k), otro.store.get(k)
            if mi and su and su[1] > mi[1]:
                self.store[k] = su
            elif not mi and su:
                self.store[k] = su


print(SEP)
print("COMPARACION A (hechos) vs B (estado) — escenario de flota")
print(SEP)

# ── El caso que rompia A ────────────────────────────────────────────────
print("\n[CONFLICTO CORREGIDO] Dos barcos escriben la misma clave a la vez")
b1, b2 = Hechos("BARCO-1"), Hechos("BARCO-2")
f1 = b1.anadir("gps", "gps", "lat=A")
f2 = b2.anadir("gps", "gps", "lat=B")
hub_a = Hechos("HUB")
n = hub_a.recibir(list(b1.hechos.values()) + list(b2.hechos.values()))
print("  A: hub recibe %d hechos de 2 -> CONSERVA LOS DOS (clave (nodo,serie,seq))" % n)
print("     estado derivado: %s  <- ambiguo, hay que decidir politica" % hub_a.estado())

e1, e2 = Estado("B1"), Estado("B2")
e1.escribir("gps", "lat=A")
e2.escribir("gps", "lat=B")
print("  B: tras converger -> %s" % ({"gps": max([("lat=A",(1,"B1")),("lat=B",(1,"B2"))],
      key=lambda x: x[1])[0]}))
print("     ** UNO SE PIERDE. No queda constancia de que el otro existio. **")

# ── Coste ───────────────────────────────────────────────────────────────
print("\n[COSTE] Flota de 50 barcos, 1 muestra/s durante 1 hora = 180.000 muestras")

N_BARCOS, N_MUESTRAS = 50, 3600

t0 = time.perf_counter()
ha = Hechos("FLOTA")
for b in range(N_BARCOS):
    nodo = Hechos("B%02d" % b)
    for i in range(N_MUESTRAS):
        nodo.anadir("gps", "pos_%d" % b, "lat=%.4f" % (41.0 + i * 0.0001))
    ha.recibir(list(nodo.hechos.values()))
t_a = time.perf_counter() - t0

t0 = time.perf_counter()
eb = Estado("FLOTA")
for b in range(N_BARCOS):
    nodo = Estado("B%02d" % b)
    for i in range(N_MUESTRAS):
        nodo.escribir("pos_%d" % b, "lat=%.4f" % (41.0 + i * 0.0001))
    eb.fusionar(nodo)
t_b = time.perf_counter() - t0

print("  A (hechos): %6.1f ms  |  guarda %d hechos  |  %.1f MB aprox" % (
    t_a * 1000, len(ha.hechos), len(ha.hechos) * 120 / 1e6))
print("  B (estado): %6.1f ms  |  guarda %d claves   |  %.3f MB aprox" % (
    t_b * 1000, len(eb.store), len(eb.store) * 120 / 1e6))
print()
print("  A crece con el NUMERO DE MUESTRAS (lineal en el tiempo).")
print("  B crece con el NUMERO DE CLAVES (constante si el esquema no cambia).")
print()
print("  Despues de 24 h: A tendria %.1f M hechos; B seguiria con %d claves." % (
    N_BARCOS * 86400 / 1e6, N_BARCOS))

# ── Verificacion de integridad ──────────────────────────────────────────
print("\n[INTEGRIDAD] Se altera una muestra antigua en el modelo A")
hk = sorted(ha.hechos.keys())[100]
fk = list(ha.hechos[hk])
fk[4] = "lat=MANIPULADO"
ha.hechos[hk] = tuple(fk)
# recomprobar la cadena de ese barco
nodo0 = [f for f in ha.hechos.values() if f[0] == hk[0] and f[1] == hk[1]]
nodo0.sort(key=lambda f: f[2])
roto = None
prev = ""
for f in nodo0:
    if h(f[5], f[4]) != f[6]:
        roto = f[2]
        break
    prev = f[6]
print("  A: manipulacion detectada en seq=%s  -> %s" % (
    roto, "SI" if roto is not None else "NO"))
print("  B: no hay nada que verificar. El estado es el estado.")
print("     (por eso el modelo B necesita la cadena APARTE, como capa de auditoria)")

print()
print(SEP)
print("LECTURA")
print(SEP)
print("""
A (hechos)   es un REGISTRO: crece para siempre, prueba lo ocurrido, permite
             auditar y detectar manipulacion. Necesita compactacion.
B (estado)   es una BASE DE DATOS: converge, ocupa poco, es rapida. No prueba
             nada de lo que paso; solo dice como esta ahora.

Lo que decide no es cual es "mejor": es si en el escenario hace falta PROBAR.
  - Bitacora del barco, telemetria, criptomoneda -> hace falta probar -> A
  - Configuracion de agentes, preferencias, estado de UI -> no hace falta -> B
""")
print(SEP)
