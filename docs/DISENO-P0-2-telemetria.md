# P0-2 — Telemetría por tool: diseño y plan

**Fecha:** 2026-10-19 · **Repo:** `lumen-protocol` @ `a29a964c`
**Estado:** diseño. **Sin código todavía.**
**Origen:** revisión de la cadena (`REVISION-cadena-decisiones.md`) — Astrid: *"sin telemetría, la poda es un
acto de fe"*.

---

## El requisito, en una línea

> Saber **qué tool se usa, cuántas veces, cuánto tarda y cuántas veces falla** — y que sobreviva a un reinicio.

## El criterio de aceptación (fijado antes de codificar)

Del `05` original, que sigue valiendo:

> *"Contador `{tool: {calls, errors, p50_ms}`, persistido junto al estado, expuesto en `server_stats`.
> Tras 10 llamadas, `server_stats` muestra el desglose; **sobrevive a un reinicio**."*

---

## Estado actual (medido, no supuesto)

| Server | Qué tiene hoy | Persiste | Sirve para podar |
|---|---|---|---|
| **thinking** | `_global_tool_calls` (un solo contador), `_tool_recent` (últimas 12, **en RAM**) | ❌ solo el global | ❌ |
| **filesystem** | `_tool_usage: {tool: count}` + `server_stats` | ❌ RAM, se pierde al reiniciar | ⚠️ parcial |
| **pdb** | nada | — | ❌ |
| **web** | nada | — | ❌ |

**Conclusión:** hoy **no hay forma de saber** si `pattern_record` se ha usado alguna vez en producción. La
poda de mañana sería a ciegas — exactamente lo que Astrid señaló.

---

## Dónde se instrumenta

### El punto único en `thinking/server.py`

Existe **un solo** sitio donde se ejecuta cualquier tool (línea ~4263, método `tools/call`):

```python
handler = HANDLERS.get(tool_name)
if handler:
    try:
        result = handler(tool_args)
        send(...)
    except Exception as e:
        send({"error": ...})
```

**Es el sitio correcto:** cubre todas las tools sin tocar 89 handlers.

### La estructura

```python
_tool_stats: dict[str, dict] = {}
# {
#   "task_list": {"calls": 42, "errors": 0, "times_ms": [0.31, 0.28, ...]},
# }
```

**p50** se calcula sobre la lista de tiempos. Para no crecer sin límite: **ventana deslizante de 200 muestras**
por tool (deque). Con 200 muestras el p50 ya es estable y la memoria queda acotada.

### El instrumento

```python
def _record_tool(tool: str, ms: float, ok: bool) -> None:
    st = _tool_stats.setdefault(tool, {"calls": 0, "errors": 0, "times_ms": deque(maxlen=200)})
    st["calls"] += 1
    if not ok:
        st["errors"] += 1
    st["times_ms"].append(ms)
```

Envolviendo el handler existente:

```python
t0 = time.perf_counter()
try:
    result = handler(tool_args)
    _record_tool(tool_name, (time.perf_counter()-t0)*1000, True)
except Exception:
    _record_tool(tool_name, (time.perf_counter()-t0)*1000, False)
    raise
```

**3 líneas de instrumentación por server.** Nada más.

---

## La persistencia (aquí está el trabajo real)

### No usar `_auto_save()` para esto

`_auto_save()` serializa **el estado entero** (18 KB) y ya cuesta **34 ms** en el PC y **127 ms** en el Asus
(D4 del estudio). Meter la telemetría ahí **empeora el defecto que estamos midiendo**.

### Diseño: fichero propio, volcado perezoso

```
LUMEN_STATE_DIR/tool_stats.json      (default %LOCALAPPDATA%/lumen/thinking)
```

| Regla | Por qué |
|---|---|
| Volcar **cada 50 llamadas o 60 s**, lo que llegue antes | Con 1 volcado cada 50 llamadas, el coste amortizado es despreciable |
| Volcar **también al cerrar** (SIGTERM/atexit) | No perder la sesión |
| Escritura **atómica** (`tmp` único por `pid+uuid` + rename) | Es el bug P1-5: dos procesos compitiendo por el mismo `.tmp` → EACCES silencioso |
| Fuera del árbol del repo | P1-5: hoy hay 35 ficheros `.thinking*` contaminando `git status` |

**Esto resuelve P1-5 de paso**, al menos para el fichero nuevo. No arregla los `.thinking_state.*` existentes
(eso es su propia entrada), pero **no añade uno más al problema**.

---

## La exposición

`server_stats` hoy devuelve métricas del server. Se le añade:

```json
{
  "tool_stats": {
    "task_list":  {"calls": 42, "errors": 0, "p50_ms": 0.31},
    "work_start": {"calls": 17, "errors": 0, "p50_ms": 34.2},
    "pattern_record": {"calls": 0, "errors": 0, "p50_ms": null}
  },
  "tool_stats_since": "2026-10-19T18:20:00Z"
}
```

**`p50_ms: null` para tools nunca llamadas** — la distinción importa: *"nunca usada"* ≠ *"usada y rápida"*.

---

## Cobertura por server (alcance realista)

| Server | Fase | Esfuerzo | Por qué |
|---|---|---|---|
| **thinking** | **1 (ahora)** | bajo — 1 punto de instrumentación + 1 fichero | 82 tools, el 74 % del catálogo. Es donde está la decisión |
| **filesystem** | 2 | bajo — ya tiene `_tool_usage`, solo falta persistir y añadir ms | 13 tools |
| **pdb** | 2 | bajo — mismo patrón | 20 tools, pero el server ya tiene perfil |
| **web** | 3 | trivial | 2 tools; no hay decisión que tomar |

**Fase 1 sola responde la pregunta que bloquea P0-1:** ¿cuáles de las 82 tools de thinking se usan?
Las demás fases no bloquean nada.

---

## Plan de ejecución

| # | paso | verificación |
|---|---|---|
| 1 | `_tool_stats` + `_record_tool` + instrumentar el dispatch | 10 llamadas → `server_stats` muestra desglose |
| 2 | Persistencia en `LUMEN_STATE_DIR` (atómica, fuera del repo) | reiniciar → los contadores siguen |
| 3 | Volcado por umbral (50 llamadas / 60 s) + `atexit` | `work_start` no se degrada (medir antes/después) |
| 4 | `server_stats` expone `tool_stats` | formato de arriba |
| 5 | Test: `test_tool_telemetry.py` | 0 llamadas ≠ p50 null; reinicio conserva |

**Criterio de cierre:** tras una sesión de trabajo real, `server_stats` responde *"¿se ha usado
`pattern_record`?"* con un número, no con una intuición.

---

## Lo que NO hace esta entrada

- **No** decide qué podar. Solo mide. La poda es P0-1, y va **después**.
- **No** reconcilia las 5 cifras de agentes. Eso es otra entrada (y otra ontología).
- **No** arregla los 35 ficheros `.thinking*` existentes. Solo no añade uno más.
- **No** toca `_auto_save()` ni el presupuesto de 100 (P0-4 y D3).

---

## Riesgo principal y mitigación

**Riesgo:** que la instrumentación degrade `work_start` (que ya está a 34 ms / 127 ms) y acabemos midiendo
un sistema más lento por medirlo.

**Mitigación:** el volcado **no** va en el camino de la llamada. `_record_tool` solo toca un `dict` en memoria
(~µs). El volcado a disco ocurre cada 50 llamadas, fuera del handler. **Medir antes y después con
`bench_handlers.py` y publicar el delta** — si `work_start` sube, el diseño está mal.
