# P0-2 — Resultado medido: telemetría por tool en producción

**Fecha:** 2026-10-19 · **Repo:** `lumen-protocol` · **Commit:** pendiente
**Estado:** implementado y **verificado** (9/9 checks). Sin desplegar todavía.

---

## Qué se ha construido

Telemetría por tool en `thinking/server.py`, en el **punto único de dispatch** (`tools/call`), que cubre
las 89 handlers sin tocar ninguno.

| Pieza | Qué hace |
|---|---|
| `_tool_stats` | `{tool: {calls, errors, times_ms}}` en memoria |
| `_record_tool()` | +1 llamada, +1 error si falla, muestra de tiempo |
| `_maybe_flush_tool_stats()` | Volcado **perezoso**: cada 50 llamadas o 60 s, fuera del handler |
| `_load_tool_stats()` | Carga al arrancar → **sobrevive al reinicio** |
| `tool_server_stats()` | Tool nueva: desglose + lista de **nunca usadas** |
| `atexit` | Volcado forzado al cerrar |

**Fichero:** `LUMEN_STATE_DIR/tool_stats.json` — **fuera del árbol del repo** (evita añadir otro `.thinking*`
al problema P1-5). Escritura atómica con `tmp` único por `pid+uuid`.

---

## Criterio de aceptación — 9/9 PASA

```
PASA   P0-2a telemetria registra llamadas
PASA   P0-2b p50 calculado
PASA   P0-2c tool nunca llamada NO tiene p50 (null != 0)
PASA   P0-2d toda tool con calls>0 tiene p50
PASA   P0-2e fichero escrito
PASA   P1-5  fichero FUERA del repo
PASA   P0-2f sobrevive a reinicio (recarga)
PASA   P0-2g cuenta errores
PASA   P0-2h server_stats tool registrada

9 checks · 9 PASA · 0 FALLA
```

**Nota de método:** el test llama por el **dispatch real** (JSON-RPC), no a los handlers sueltos. Llamar al
handler directo **salta la telemetría por diseño** — la primera versión del test daba 4 fallos falsos por eso.

---

## La medición que me corrige a mí mismo

Mi diseño advertía: *"si `work_start` sube, el diseño está mal"*. Lo medí, subió de 6,4 → 8,2 ms, y **fui a
buscar la causa**. La causa no era mi código:

| Medición | Resultado |
|---|---|
| `work_start` con telemetría | **8,32 ms** |
| `work_start` **con la telemetría desactivada** (lambda no-op) | **15,57 ms** |
| Coste de `_record_tool` | **0,7 µs** |

> **La variación es del entorno (caché de disco, carga), no de la instrumentación.** Desactivar la telemetría
> da un número *peor*. El "baseline 6,4 ms" era una medición con otra caché.

**Lección aplicada:** no dar por buena una regresión de 1,5 ms sin aislar la variable. Si hubiera confiado en
la primera medición, habría "arreglado" un problema inexistente y probablemente roto algo.

---

## Lo que esto desbloquea

Con esta telemetría, la pregunta que bloqueaba P0-1 **ya tiene respuesta medible**:

```python
server_stats()
# → 42 tools usadas · 47 nunca llamadas · 89 en total
# → NUNCA usadas (47): pattern_record, model_add, objective_create, ...
```

**La poda deja de ser un acto de fe.** Pero — y esto es importante — **no la autoriza todavía**:

- Una sesión de trabajo real da **una** muestra. Astrid pedía inventario, Smith pedía **grafo de tareas**.
- `pattern_record` sin usar **hoy** no significa inútil: significa que el flujo que la justifica aún no se ha
  probado (el propio estudio del Asus lo dice).
- **Falta acumular uso real** (días, no una sesión) antes de podar.

---

## Lo que NO se ha hecho (deliberadamente)

| Pendiente | Por qué |
|---|---|
| **filesystem / pdb / web** | Fase 2. `filesystem` ya tiene `_tool_usage`; falta persistir. No bloquea nada |
| **Arreglar los 35 ficheros `.thinking*`** | P1-5 propio. Este trabajo **no añade uno más**, pero no limpia los viejos |
| **Desplegar** | Requiere reinicio del server; se decide tras tu revisión |
| **Podar** | Es P0-1, y va **después** de acumular uso |

---

## Riesgo residual

**El estado se pierde si el proceso muere sin `atexit`** (kill -9). Mitigación actual: volcado cada 50 llamadas
o 60 s. Pérdida máxima: 49 llamadas. **Aceptable** para el propósito (decidir qué podar), no para facturación.

**`_maybe_flush_tool_stats` se llama en cada `_record_tool`** — comprueba dos contadores, ~0,1 µs. No escribe.
El volcado real ocurre 1 de cada 50 llamadas.
