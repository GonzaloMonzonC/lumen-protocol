# -*- coding: utf-8 -*-
"""MOTOR UNICO que respeta el perfil de replicacion.

Un solo codigo. El perfil decide retencion, replicacion, firma, compactacion y
politica de conflicto. El objetivo no es "que funcione": es que CONFIGURACIONES
OPUESTAS cumplan cada una en su escenario.
"""
import hashlib, sys, io

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')


def h(prev, valor):
    return hashlib.sha256((prev + valor).encode()).hexdigest()


class Hecho:
    __slots__ = ("nodo", "serie", "seq", "clave", "valor", "prev", "hash", "ts",
                 "firma", "recurso")

    def __init__(self, nodo, serie, seq, clave, valor, prev, ts, recurso=None):
        self.nodo, self.serie, self.seq = nodo, serie, seq
        self.clave, self.valor, self.prev, self.ts = clave, valor, prev, ts
        self.recurso = recurso
        self.hash = h(prev, valor)
        self.firma = None

    def identidad(self):
        """(nodo, serie, seq) — lleva el NODO dentro, regla que salio de A."""
        return (self.nodo, self.serie, self.seq)

    def recurso_de_clave(self):
        """Deduce el recurso de la clave: 'pago:A->B' -> 'saldo:A'.

        Sirve para detectar doble gasto sin que el usuario tenga que declararlo.
        Si no se puede deducir, devuelve None y no se comprueba.
        """
        if ":" in self.clave:
            cabeza, resto = self.clave.split(":", 1)
            if "->" in resto:
                origen = resto.split("->")[0]
                return "saldo:%s" % origen
            return "%s:%s" % (cabeza, resto)
        return None


class Motor:
    """Nodo de replicacion. Todo lo variable viene del perfil."""

    def __init__(self, nombre, cfg):
        self.nombre = nombre
        self.cfg = cfg                      # el perfil
        self.hechos = {}                    # identidad -> Hecho
        self.series = {}                    # (nodo, serie) -> [Hecho en orden]
        self.bloques = []                   # sellos de bloque
        self.borrados = {}                  # clave -> ts del borrado
        self.descartados = 0                # por compactacion
        self.firmados = 0
        self.t0 = 0

    # ── escritura ──────────────────────────────────────────────────────
    def escribir(self, clave, valor, ts=None, serie="default", borrar=False):
        ts = ts if ts is not None else (self.t0 + len(self.hechos))
        k = (self.nombre, serie)
        seq = len(self.series.get(k, []))
        prev = self.series[k][-1].hash if self.series.get(k) else ""
        f = Hecho(self.nombre, serie, seq, clave, "" if borrar else valor, prev, ts)
        self.hechos[f.identidad()] = f
        self.series.setdefault(k, []).append(f)
        if borrar:
            self.borrados[clave] = ts

        # ── firma segun perfil ──
        if self.cfg["firma"] == "por_hecho":
            f.firma = h(f.hash, "firma:" + self.nombre)
            self.firmados += 1
        elif self.cfg["firma"] == "por_bloque":
            n = self.cfg["firma_bloque_n"]
            lista = self.series[k]
            if len(lista) % n == 0:
                sello = h("", "|".join(x.hash for x in lista[-n:]))
                self.bloques.append((k, len(lista), sello))
                self.firmados += 1
        return f

    # ── replicacion ────────────────────────────────────────────────────
    def acepta_de(self, otro_nombre, series_de_otro):
        """Segun el perfil, decide si este nodo replica lo de otro.

        Ojo con 'hub': la politica dice "este nodo solo replica CON el hub", es
        decir, el filtro mira QUIEN SOY YO, no quien envia. La version anterior
        miraba el nombre del emisor y rechazaba todo lo que no empezara por HUB,
        que es justo lo contrario.
        """
        modo = self.cfg["replicacion"]
        if modo == "todos":
            return True
        if modo == "flota":
            # misma flota: aqui simplificado, se acepta (el PKI real va por Ed25519)
            return True
        if modo == "interes":
            interes = set(self.cfg["replicacion_interes"])
            return bool(interes & set(series_de_otro))
        if modo == "hub":
            # Solo se replica si alguno de los dos extremos es el hub.
            return self.nombre.startswith("HUB") or otro_nombre.startswith("HUB")
        return True

    def recibir(self, motor_origen):
        """Recibe hechos de otro nodo, aplicando el filtro del perfil."""
        series_origen = {f.serie for f in motor_origen.hechos.values()}
        if not self.acepta_de(motor_origen.nombre, series_origen):
            return 0, "rechazado por politica de replicacion"
        nuevos = 0
        for f in motor_origen.hechos.values():
            if f.identidad() in self.hechos:
                continue
            self.hechos[f.identidad()] = f
            self.series.setdefault((f.nodo, f.serie), []).append(f)
            nuevos += 1
        return nuevos, ""

    # ── retencion / compactacion ───────────────────────────────────────
    def compactar(self, ahora):
        """Aplica la politica de retencion y compactacion del perfil.

        REGLA QUE SALIO AL PROBAR: nunca se descarta el ULTIMO hecho de una serie.
        Si se tira, se pierde el estado actual y el nodo queda vacio. La
        compactacion archiva historia; el presente se conserva siempre.
        """
        modo = self.cfg["retencion_modo"]
        if modo == "todo":
            return "nada que compactar (retencion total)"
        if modo == "ventana":
            horas = self.cfg["retencion_horas"]
            # Los ts del motor estan en SEGUNDOS. El perfil se declara en horas,
            # que es como lo piensa quien configura. Convertir aqui, una sola vez.
            limite = ahora - horas * 3600
            a_tirar = []
            for ident, f in self.hechos.items():
                if f.ts >= limite:
                    continue
                # proteccion: si es el ultimo de su serie, no se tira
                serie = self.series.get((f.nodo, f.serie), [])
                if serie and serie[-1].identidad() == ident:
                    continue
                a_tirar.append(f)
            if self.cfg["compactacion"] == "descartar":
                for f in a_tirar:
                    del self.hechos[f.identidad()]
                self.descartados += len(a_tirar)
                return "%d hechos descartados (>%dh)" % (len(a_tirar), horas)
            # sellos: se guarda el sello del tramo y se tira el detalle
            if a_tirar:
                sello = h("", "|".join(sorted(x.hash for x in a_tirar)))
                self.bloques.append(("archivo", len(a_tirar), sello))
                for f in a_tirar:
                    self.hechos.pop(f.identidad(), None)
                self.descartados += len(a_tirar)
                return "%d hechos sellados y descartados (>%dh)" % (len(a_tirar), horas)
            return "nada que compactar"
        return "modo desconocido"

    # ── estado derivado ────────────────────────────────────────────────
    def estado(self):
        """Deriva el estado aplicando la politica de conflicto del perfil.

        Ademas de la politica por clave, se comprueba el conflicto por RECURSO:
        dos hechos distintos que reclaman el mismo recurso (p.ej. "pago:A->B" y
        "pago:A->C" sobre el saldo de A) es un doble gasto. Eso NO se detecta
        mirando una sola clave, porque las claves son distintas.
        """
        politica = self.cfg["conflicto"]
        por_clave = {}
        for f in self.hechos.values():
            por_clave.setdefault(f.clave, []).append(f)
        est = {}
        for clave, lista in por_clave.items():
            if politica == "ultimo_gana":
                g = max(lista, key=lambda x: (x.ts, x.nodo))
            elif politica == "primero_gana":
                g = min(lista, key=lambda x: (x.ts, x.nodo))
            else:  # manual
                if len({(x.valor) for x in lista}) > 1:
                    est[clave] = "<CONFLICTO: %d valores>" % len({x.valor for x in lista})
                    continue
                g = lista[0]
            if clave in self.borrados and self.borrados[clave] >= g.ts:
                continue
            est[clave] = g.valor

        # ── conflicto por RECURSO (doble gasto) ──
        # Se agrupan los hechos por el recurso que tocan. El recurso se declara
        # en el campo `recurso` del hecho; si no hay, se deduce de la clave.
        if politica == "manual":
            por_recurso = {}
            for f in self.hechos.values():
                r = getattr(f, "recurso", None) or f.recurso_de_clave()
                if r:
                    por_recurso.setdefault(r, set()).add(f.valor)
            for recurso, valores in por_recurso.items():
                if len(valores) > 1:
                    est["<RECURSO %s>" % recurso] = "<CONFLICTO: %d valores>" % len(valores)
        return est

    def estadisticas(self):
        return {
            "hechos": len(self.hechos),
            "bloques": len(self.bloques),
            "firmados": self.firmados,
            "descartados": self.descartados,
        }
