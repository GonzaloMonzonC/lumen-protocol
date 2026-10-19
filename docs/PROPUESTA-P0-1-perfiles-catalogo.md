# P0-1 — Perfiles de catálogo: propuesta basada en el código real

**Fecha:** 2026-10-19 · **Repo:** `lumen-protocol` @ `4eae8b09`
**Estado:** propuesta para decidir. **No hay código escrito todavía.**

---

## Hallazgo previo que cambia el trabajo

> **P0-1 ya está implementado — en el servidor `pdb`, y solo ahí.**
> El estudio decía «0 ocurrencias de `LUMEN_MCP_PROFILE`» y era cierto, pero por la razón equivocada:
> la variable se llama **`LUMEN_PDB_PROFILE`** y el concepto se llama **«perfil»**, no `PROFILE`.

Lo que existe hoy en `pdb/pdb_tools.py`:

| Pieza | Qué hace |
|---|---|
| `PROFILE_AGENT = "agente"` / `PROFILE_ADMIN = "admin"` | dos perfiles |
| `tools_for_profile(profile)` | filtra el catálogo |
| `resolve_profile(argv)` | `--profile X` gana sobre `LUMEN_PDB_PROFILE`; **un typo cae a `agente` con aviso** |
| `_synthetic_schema()` | genera `inputSchema` mínimo para handlers sin schema (admin) |
| `_EXPOSED_NAMES` en `server.py` | al llamar una tool no expuesta: *«existe pero no está en el perfil 'agente'»* en vez de «Unknown tool» |
| `test_pdb_catalog_allowlist.py` | **tests propios del allowlist** |

**Esto no hay que inventarlo: hay que replicarlo.** El patrón está probado y tiene tests. Copiarlo a
`thinking` es trasladar 60 líneas, no diseñar un sistema.

---

## El mapa real: dónde se sirve `tools/list`

Cinco sitios en el código. **Pero en esta máquina solo uno está activo** (verificado 2026-10-19):

| Server | Fichero | Línea | Estado del filtro | ¿Activo aquí? |
|---|---|---|---|---|
| **pdb** | `pdb/server.py` | 32 | ✅ **ya filtra** (`EXPOSED`) | ✅ sí |
| **thinking** | `thinking/server.py` | 4237 | ❌ `TOOLS` completo — **82 tools, el 74 % del coste** | ✅ **sí (stdio)** |
| **filesystem** | `filesystem/server.py` | 59 | ❌ `shared_tools.TOOLS` (13) | — |
| **web** | `web/server.py` | 581 | ❌ `TOOLS` (2) | — |
| shm (nativo) | `shm_native_server.py` | 207 | ❌ sirve sin filtro | ❌ **NO** |
| shm (bridge) | `shm_bridge_plugin.py` | 174 | ❌ `tools/list` reenviado tal cual | ❌ **NO** |

### ⚠️ CORRECCIÓN (2026-10-19, tras medir en vivo)

**Este documento afirmaba antes:** *"en este PC los tools llegan por el plugin SHM; filtrar solo `server.py`
no cambia nada"*. **Es FALSO.** Verificado con `psutil` sobre los procesos vivos:

```
8040  19:44:48  .../mcp-servers/thinking/server.py     ← el que sirve las tools
3520  19:44:48  .../mcp-servers/thinking/server.py     ← hijo del anterior
```

- **Todos los procesos thinking corren `server.py`**, ninguno `server_shm.py`.
- El plugin (`lumen-shm-bridge`) **declara** `_THINKING_SHM = .../thinking/server_shm.py`, pero el proceso
  resultante es `server.py`: **el intento de SHM cae a stdio**.
- Consecuencia práctica: **en esta máquina SHM no está activo para thinking.** Las tools llegan por stdio.

**Qué implica para P0-1:**

1. **El paso crítico es `thinking/server.py`** (línea 4237), no los SHM. Eso **simplifica** el trabajo.
2. Los SHM siguen habiendo que tocarlos **para otras máquinas** donde sí arranquen — pero **no bloquean aquí**.
3. La misma corrección aplica a `shm_bridge_plugin.py`: es código a mantener, no la vía activa.

**Lección de método:** di por hecho que el plugin SHM estaba activo porque estaba instalado. Instalado ≠
en el camino. Se comprueba con `psutil` sobre los procesos vivos, no leyendo la config.

---

## Corrección a la tesis del estudio (medida, no opinada)

El `02` y el `04` concluyen: *"filesystem y web duplican nativas, veredicto: eliminar del contexto del agente"*.

**Medido en esta máquina, eso es falso.**

| | LUMEN filesystem | Hermes nativo |
|---|---|---|
| `read_file` p50 | **0,31 ms** | — |
| `search_files` p50 | **0,28 ms** | — |
| `disk_usage`, `file_info`, `find_duplicates`, `stream_read` | **existen** | **no existen** |

Y `lumen_web`:

| | LUMEN web | Hermes nativo |
|---|---|---|
| `web_search` | cadena **DDG (sin clave) → Tavily** | proveedor gestionado |
| Coste marginal | **0 en el camino DDG** | por llamada |

**Los dos argumentos del estudio caen:**

1. *"Duplican con menos capacidades"* → filesystem aporta **4 tools que no tenemos** y es **más rápido**
   (0,31 ms). No es un duplicado: es una vía distinta.
2. *"No aportan nada al agente"* → los usó el agente **del Asus**, en una instalación limpia.
   **Corrección (2026-10-19):** dije que *"en esta máquina `read_file`/`web_search` nativos ya son LUMEN vía
   SHM, y el estudio se contradice"*. **Eso era falso** — verificado que SHM no está activo aquí y las tools
   llegan por stdio. El estudio **no se contradice**; simplemente midió otra instalación. Lo que sí sigue en
   pie es el punto 1: filesystem aporta 4 tools que Hermes no tiene y es más rápido.

> **Conclusión:** `filesystem` y `web` **se quedan en el perfil `agent`**. Lo que sobra no es el servidor,
> son **las 13 tools de filesystem que solapan** parcialmente — y eso es otra conversación (P2).

---

## Dónde está el ahorro de verdad: `thinking`

Del catálogo de 14.138 tokens, thinking son **10.513 (74,3 %)**. Desglose por familia:

| familia | n | tokens~ | ¿uso real? |
|---|---|---|---|
| `thought_*` | 7 | 1.042 | ❌ |
| `model_*` | 6 | 916 | ❌ |
| `pdb_*` (namespaces) | 10 | 787 | ❌ duplican `pdb_get/set` |
| `pattern_*` | 4 | 777 | ❌ |
| `task_*` | 7 | 739 | ⚠️ kanban |
| `objective_*` | 7 | 636 | ❌ |
| `work_*` | 4 | 628 | ✅ **sí** |
| `wiki_*` | 5 | 542 | ❌ |
| `sequential_thinking` | 1 | 522 | ❌ |
| `agent_*` | 2 | 293 | ✅ **sí** (promocionar) |
| `assume` | 1 | 232 | ✅ **sí** |
| `decision_log` | 2 | 391 | ✅ **sí** |
| resto (context, state, session, check, checklist, search, niche…) | 24 | ~2.100 | mixto |

---

## Propuesta concreta

### Perfil `agent` — lista blanca verificada

**Regla: se incluye lo que (a) el estudio midió que se usa, o (b) aporta algo que no tenemos por otra vía.**

#### En `thinking` — 17 tools · 2.531 tokens *(medido, no estimado)*

| # | tool | por qué entra |
|---|---|---|
| 1 | `agent_message` | **primitiva más útil y menos visible** (el estudio la promociona) |
| 2 | `agent_inbox` | ídem |
| 3 | `assume` | dejar constancia |
| 4 | `decision_log` | dejar constancia |
| 5 | `work_start` | abrir trabajo |
| 6 | `work_done` | cerrar trabajo |
| 7 | `work_log` | ver trabajo |
| 8 | `state_snapshot` | diagnóstico |
| 9 | `session_init` | arranque de sesión (contrato LUMEN) |
| 10 | `checklist` | tareas del turno |
| 11-17 | `task_list`, `task_create`, `task_move`, `task_search`, `task_delete`, `task_link`, `task_link_url` | **kanban: familia completa** (7, uso diario) |

> **Las 4 `pdb_*` (get/has/set/vec_search) NO están aquí**: viven en el servidor `pdb`, que ya las tiene
> expuestas con su propio perfil. Ponerlas en el whitelist de thinking es un error — no existen en su `TOOLS`.

**72 de los 89 handlers de thinking quedan fuera del catálogo de agente**, todos invocables por nombre.

#### En `filesystem` y `web` — se dejan COMPLETOS

13 + 2 tools. **No son un duplicado: son otra vía.** `read_file` 0,31 ms, `search_files` 0,28 ms, y 4 tools
que Hermes no tiene (`disk_usage`, `file_info`, `find_duplicates`, `stream_read`). `web_search` es cadena
**DDG sin clave → Tavily**: coste marginal 0 en el camino DDG.

### Decisión tomada: `task_*` DENTRO (2026-10-19)

`task_*` son **7 tools / 739 tokens**. Se quedan en el perfil `agent`. Razón: con **256 tareas y 14 nichos en
uso real**, el kanban no es una tool de usar «algún día» — es trabajo diario. 739 tokens (~5 % del catálogo)
frente a tener que ir a buscar la tool cada vez que aparece una tarea no compensa el ahorro.

**Se incluye la familia completa, no a medias.** Media familia rompe el flujo: creas la tarea y no la puedes
mover. Las 7 o ninguna.

### El resto va a `operator`

`thought_*`, `model_*`, `pattern_*`, `objective_*`, `wiki_*`, `niche_*`, `task_*`, `context_*`,
`file_*`, `pdb_ns_*`, `sequential_thinking`, `thought_to_plan`… — **siguen existiendo e invocables por
nombre**, solo dejan de cargarse en el prompt.

### Ahorro estimado *(cifras verificadas contra el código)*

| | hoy | propuesta |
|---|---|---|
| **thinking** | 82 tools · 10.513 tok | **17 tools · 2.531 tok** |
| filesystem | 13 · 1.904 | **13 · 1.904** (se quedan) |
| web | 2 · 333 | **2 · 333** |
| pdb | 20 · 1.388 | 20 · 1.388 |
| **TOTAL** | **117 · 14.138** | **52 · ~6.156** |

**−7.982 tokens por turno (−56 %)**, sin perder ninguna capacidad: los 72 handlers de thinking que salen del
catálogo siguen existiendo e invocables por nombre.

---

## Plan de ejecución (5 pasos, cada uno verificable)

| # | paso | verificación |
|---|---|---|
| 1 | Extraer `tools_for_profile` + `resolve_profile` de `pdb_tools.py` a un módulo compartido | los tests de pdb siguen verdes |
| 2 | **Aplicarlo en `thinking/server.py` con lista blanca de 17** | `censo_stdio.py` → thinking ≤ 17 tools |
| 3 | Aplicarlo también en `shm_native_server.py` / `shm_bridge_plugin.py` **para las máquinas donde SHM sí arranca** | el escaneo de tools baja también ahí |
| 4 | Añadir `test_thinking_catalog_allowlist.py` copiando el de pdb | test verde |
| 5 | `LUMEN_MCP_PROFILE` (genérico) con fallback a `LUMEN_PDB_PROFILE` | typo → cae a `agent` con aviso |

**Corrección (2026-10-19):** este documento decía *"el paso 3 es el único que cambia algo en esta máquina"*.
**Falso.** Verificado con `psutil`: en este PC **todos** los procesos thinking corren `server.py` (stdio);
SHM no está activo. **El paso que cambia algo aquí es el 2.** El 3 sigue siendo necesario para portabilidad,
no como desbloqueo local.

---

## Lo que NO propongo

- **No** filtrar `filesystem` ni `web`: aportan y son más rápidos. Decisión medida, no opinión.
- **No** borrar handlers: se poda el **catálogo**, no el servidor.
- **No** tocar `work_start` (P0-4) en la misma tanda: una entrada = un defecto.
- **No** cambiar nombres: rompe el contrato de los clientes.

---

## Decisión cerrada (2026-10-19)

**Perfil `agent` = 52 tools · ~6.156 tokens · −7.982 tokens por turno (−56 %).**

- **thinking**: 82 → **17 tools** (2.531 tok). Verificado contra `TOOLS` real: `task_update` no existe
  (es `task_link`), y las 4 `pdb_*` NO están en thinking — viven en el servidor `pdb`.
- **filesystem (13) y web (2) completos** dentro: aportan y son más rápidos (0,31 ms / DDG sin clave).
- **`task_*` dentro**: uso diario, 256 tareas vivas. Familia completa, no a medias.
- El resto, a `operator`, **sin borrar nada**: 72 handlers siguen invocables por nombre.

**Siguiente paso:** ejecutar el plan de 5 pasos, empezando por el **2** (`thinking/server.py`) — es el que
cambia algo en esta máquina, porque las tools llegan por stdio (verificado 2026-10-19). El 3 (SHM) es
portabilidad para otras máquinas, no un desbloqueo local.

---

## Erratas corregidas en este documento (2026-10-19)

| Afirmaba | Realidad medida |
|---|---|
| "en este PC los tools llegan por el plugin SHM" | **Falso.** Todos los procesos thinking corren `server.py` (stdio). El plugin declara `server_shm.py` pero cae a stdio |
| "filtrar solo `server.py` no cambia nada" | **Falso.** Es exactamente lo que cambia algo |
| "el paso 3 (SHM) es el único que cambia algo aquí" | **Falso.** El paso 2 es el que cambia algo aquí |
| "el estudio se contradice: critica la duplicación mientras corre sobre ella" | **Falso.** El estudio midió otra instalación; no se contradice. El argumento de las 4 tools únicas sigue en pie |

**Causa de las cuatro:** di por hecho que el plugin SHM estaba en el camino porque estaba **instalado**.
Instalado ≠ activo. Se comprueba con `psutil` sobre procesos vivos, no leyendo config.
