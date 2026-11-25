# Prototipos A vs B — resultado con las manos

> 2026-11-24. Dos prototipos ejecutables, mismo escenario, medidas reales.
> Código en `experimentos/ddp-modelos/`.

## Cómo ejecutarlos

```bash
cd experimentos/ddp-modelos
python proto_a_hechos.py     # registro append-only
python proto_b_estado.py     # estado convergente (LWW)
python comparar.py           # los dos, con coste medido
```

---

## 1 · Resultado lado a lado

| | **A · Hechos** | **B · Estado (LWW)** |
|---|---|---|
| Cambio de valor | ✅ como hecho nuevo, **con rastro** | ✅ pero **sin rastro** del anterior |
| Borrado | ✅ viaja como hecho | ✅ con **tombstone obligatorio** |
| Conflicto | ✅ **conserva los dos** | 🟡 converge, **uno se pierde en silencio** |
| Hueco en la serie | ✅ **detectado y localizado** | ❌ **indetectable** |
| Manipulación | ✅ **detectada** (`seq=100`) | ❌ no hay nada que verificar |
| Estado actual | derivado (último hecho) | directo |
| Crecimiento | con las **muestras** (tiempo) | con las **claves** (esquema) |
| Compactación | **necesaria** | barata (TTL de tombstones) |

## 2 · Coste medido

Flota de **50 barcos, 1 muestra/s durante 1 hora = 180.000 muestras**:

| Modelo | Tiempo | Guarda | Tamaño |
|---|---:|---:|---:|
| **A (hechos)** | 1.056 ms | 180.000 hechos | **~21,6 MB** |
| **B (estado)** | 221 ms | 50 claves | **~0,006 MB** |

**Después de 24 h:** A tendría **4,3 millones de hechos**; B seguiría con **50 claves**.

Esa es la tensión real: **A es 5× más lento y 3.600× más grande**, y a cambio
prueba cosas que B no puede probar.

## 3 · Un fallo que salió al ejecutarlo

En la primera versión de A, dos barcos que escribían a la vez usaban **`seq=0`
los dos** y colisionaban: el hub **descartaba uno en silencio**. Exactamente el
mismo fallo que estamos intentando arreglar, reapareciendo dentro del arreglo.

**Corrección: la clave del hecho es `(nodo, serie, seq)`, no `(serie, seq)`.**
Así cada barco tiene su propia secuencia y no se pisan. Verificado: ahora
`hub recibe 2 hechos de 2`.

**Lección que vale para el diseño final:** el identificador de un hecho tiene que
llevar el nodo dentro, o vuelve el problema.

## 4 · El veredicto

**No es "A o B". Es A donde hace falta probar, B donde no.**

La pregunta que decide no es técnica: **¿alguien va a tener que demostrar lo que
pasó?** Si la respuesta es sí, hace falta A. Si es no, B es mejor en todo.

| Dato | Modelo | Por qué |
|---|---|---|
| Telemetría de barco | **A** | Hay que probar que no falta ninguna hora |
| Bitácora / auditoría | **A** | Es el sentido del dato |
| Criptomoneda | **A** | Un registro de hechos es lo que es |
| Muestras de dron | **A** | Evidencia de lo volado |
| Config de agentes | B | Nadie audita por qué un agente tiene temperatura 0.7 |
| Preferencias / UI | B | Converger es todo lo que se pide |
| Rutinas M y personalidades | B | Estado, no historia |

**Y aquí está lo importante: los dos comparten el mismo transporte.**

`lumen-znet` mueve mensajes; da igual si el contenido es un hecho o un estado.
Lo que cambia es la capa de arriba. Por eso no hay que elegir de antemano ni
meter los dos en el núcleo: **el núcleo replica hechos; el estado es una vista
derivada de los hechos.**

## 5 · Propuesta de arquitectura

```
  CAPA 3 · VISTAS
    · estado_actual (KV, derivado)  · consultas · índices
  ─────────────────────────────────────────────────────
  CAPA 2 · MODELO
    · hechos firmados (nodo, serie, seq, clave, valor, prev_hash, firma)
    · la cadena de hashes YA existe (cadena.rs, ADR-003)
  ─────────────────────────────────────────────────────
  CAPA 1 · TRANSPORTE
    · lumen-znet (31 tests verdes) — no cambia
```

El estado **no se replica**: se recalcula. Si dos nodos tienen los mismos hechos,
derivan el mismo estado. Eso elimina de golpe los conflictos de la capa de estado:
no hay que fusionar estado, hay que fusionar hechos, y los hechos son inmutables.

**Ventaja que no esperaba:** los conflictos dejan de ser un problema de
transporte. Dos barcos escriben hechos distintos; ambos se conservan; el estado
derivado aplica la política que se elija. Y se puede cambiar la política sin
replicar nada otra vez.

## 6 · Lo que esto implica para `pdb_sync_engine`

Pasa de ser **el mecanismo de sincronización** a ser **la vista derivada**.
Deja de tener que resolver conflictos, tombstones y diffs de valor: si los hechos
están bien replicados, la vista es un `SELECT` sobre ellos.

Y el fallo de hoy (solo replica claves nuevas) deja de importar, porque el estado
ya no es la fuente de verdad.

## 7 · Preguntas abiertas

1. **Compactación de hechos**: ¿cuánto se retiene? Un barco con 6 meses de datos
   a 1 Hz son ~15 M hechos. Con sellos de bloque cada 100, se puede archivar y
   conservar la prueba. **¿Aceptable?**
2. **¿Los hechos se replican todos a todos?** En un enjambre de 1.000 drones, no.
   Ahí hace falta **replicación parcial por interés** (quién necesita qué).
3. **¿Firma por hecho o por bloque?** Por hecho es más seguro y más caro. Por
   bloque de 100 es 100× más barato, pero un fallo afecta a 100 muestras.
4. **¿Dónde vive la política de merge del estado?** En la vista, no en el nodo.
