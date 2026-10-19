# P0-2 — Resultado: telemetría por tool

**Fecha:** 2026-10-19 · **Repo:** `lumen-protocol` (`46602785`) + plugin de Hermes
**Estado:** implementado y probado (14/14 checks). **El camino real de esta máquina es el plugin** (ver §5).

---

## ⚠️ Lo más importante de este documento: hay TRES caminos de dispatch

Se implementó la telemetría en `thinking/server.py`, se probó (9/9) y **no escribía nada**. La causa es
estructural y conviene tenerla escrita:

```
Hermes  →  plugin lumen-shm-bridge  →  conn.call_tool()  →  JSON-RPC "tools/call" por SHM
                                                                     ↓
                                                        ShmNativeServer.run()
                                                        (SU PROPIO dispatch)
                                                                     ↓
                                                        self.handlers[tool](args)
```

| Camino | Dónde está el dispatch | ¿Activo en esta máquina? |
|---|---|---|
| **stdio** | `thinking/server.py` → `handle_message()` | ❌ no (aunque los procesos sean `server.py`) |
| **SHM nativo** | `shm_native_server.py` → `ShmNativeServer.run()` | ✅ **SÍ — es el real** |
| **plugin** | `plugins/lumen-shm-bridge/__init__.py` → `call_tool()` | ✅ **es el punto de paso de todas las llamadas** |

**Consecuencia:** la instrumentación de `thinking/server.py` es correcta para instalaciones stdio, pero **en
esta máquina no mide nada**. El punto que ve **todas** las llamadas es `call_tool()` del plugin.

---

## Qué se ha construido

### 1. En `thinking/server.py` (camino stdio, para portabilidad)

| Pieza | Qué hace |
|---|---|
| `_tool_stats` | `{tool: {calls, errors, times_ms}}` en memoria |
| `_record_tool()` | +1 llamada, +1 error si falla, muestra de tiempo |
| `_maybe_flush_tool_stats()` | Volcado **perezoso**: cada 50 llamadas o 60 s |
| `_load_tool_stats()` | Carga al arrancar → sobrevive al reinicio |
| `tool_server_stats()` | Tool nueva: desglose + lista de **nunca usadas** |
| `_telemetry_wrap()` | Envuelve handlers para el camino `ShmNativeServer` |

### 2. En el plugin de Hermes (camino REAL de esta máquina)

`plugins/lumen-shm-bridge/__init__.py` → `call_tool()` instrumentado (10 líneas) +
`_telemetry_record()` / `_telemetry_flush()` / `telemetry_report()`.

**Backup antes de tocar** (el plugin no es repo git): `__init__.py.bak-20261019-195820`.

**Fichero:** `LUMEN_STATE_DIR/tool_stats.json` (default `%LOCALAPPDATA%/lumen/thinking/`) — **fuera del árbol
del repo** (no añade otro `.thinking*` al problema P1-5). Escritura atómica con `tmp` único por `pid+uuid`.
Clave por servidor: `"thinking/assume"`, `"filesystem/read_file"`.

---

## Criterio de aceptación — 14/14

**Camino stdio (9):**
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
```

**Camino SHM/plugin (5):**
```
PASA   SHM-1 el camino SHM registra llamadas
PASA   SHM-2 p50 presente
PASA   SHM-3 error por camino SHM cuenta
PASA   SHM-4 el wrapper no altera el resultado
PASA   SHM-5 volcado a disco
```

**Bug encontrado y corregido en el plugin:** el merge con lo ya volcado sumaba `calls` entero en cada volcado
→ 55 llamadas aparecían como 107. Ahora lleva **delta** por clave: `55 + 40 = 95` (verificado).

---

## Estado de despliegue: pendiente de reinicio de Hermes

El plugin se carga **dentro del proceso del gateway** (`slash_worker`). Python leyó `__init__.py` al iniciar
la sesión, así que **el cambio en disco no se aplica hasta reiniciar**.

| Paso | Estado |
|---|---|
| Código escrito y probado | ✅ |
| Backup del plugin original | ✅ `__init__.py.bak-20261019-195820` |
| Backup del `server.py` original | ✅ en git (`46602785`) |
| **Datos reales acumulándose** | ❌ **falta reiniciar gateway + UI** |

**Tras reiniciar**, verificar:
```bash
ls -la "$LOCALAPPDATA/lumen/thinking/tool_stats.json"
```

---

## La medición que me corrigió a mí mismo

Mi diseño advertía: *"si `work_start` sube, el diseño está mal"*. Lo medí, subió de 6,4 → 8,2 ms, y **fui a
buscar la causa**:

| Medición | Resultado |
|---|---|
| `work_start` con telemetría | **8,32 ms** |
| `work_start` **con la telemetría desactivada** | **15,57 ms** |
| Coste de `_record_tool` | **0,7 µs** |

> La variación era del entorno (caché de disco), no de la instrumentación. Desactivar la telemetría da un
> número *peor*. El "baseline 6,4 ms" era de otra caché.

**Lección:** no dar por buena una regresión de 1,5 ms sin aislar la variable.

---

## Lo que esto desbloquea — y lo que NO autoriza

`server_stats()` / `telemetry_report()` responden *"¿se ha usado `pattern_record`?"* con un número.
**La poda deja de ser un acto de fe.** Pero **no la autoriza**:

- Una sesión da **una** muestra. Astrid pedía inventario; Smith pedía **grafo de tareas**.
- `pattern_record` sin usar hoy no significa inútil: el flujo que la justifica aún no se ha probado.
- **Hay que acumular días de uso real** antes de decidir.

---

## Pendiente

| Pendiente | Por qué |
|---|---|
| **Reiniciar Hermes** (gateway + UI) | único paso para empezar a acumular |
| filesystem / pdb / web | el plugin ya los cubre al instrumentar `call_tool()` (clave por servidor) |
| Arreglar los 35 ficheros `.thinking*` | P1-5 propio; este trabajo no añade uno más |
| Decidir si el plugin pasa a repo git | hoy vive en `AppData/` sin control de versiones |

---

## Riesgo residual

**El estado se pierde si el proceso muere sin volcado** (kill -9). Mitigación: volcado cada 50 llamadas o 60 s.
Pérdida máxima: 49 llamadas. **Aceptable** para decidir qué podar, no para facturación.

**Varios procesos escriben el mismo fichero** (varios `slash_worker`, servidores MCP). El volcado hace *merge*
con lo que ya hay en disco y lleva delta por clave, pero **no hay lock entre procesos**: dos volcados
simultáneos pueden perder el delta de uno. Con volcados cada 60 s y escritura atómica (`os.replace`), el
impacto es una muestra perdida, no corrupción. Si se quiere exactitud, el siguiente paso es un lock de fichero.

**El plugin no está en git.** Cualquier cambio ahí se pierde si se reinstala Hermes. El backup
`__init__.py.bak-20261019-195820` está al lado, pero **conviene llevarlo a un repo**.

