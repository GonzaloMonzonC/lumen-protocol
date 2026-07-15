# Spec M-Agent v0.1 — lenguaje M + modelo de ejecución LUMEN

> Documento normativo del subset M soportado, la semántica de los globals,
> el modelo de jobs (MVM) y el contrato de acceso a datos.
>
> Fecha: 2026-07-14 · Estado: **v0.1 borrador** (Fase 0 del PLAN_EVOLUCION)
> Fuente de verdad: este documento + la suite de conformidad (§9).
> Cualquier motor (Python hoy, Rust mañana) DEBE pasar la suite sin leer
> la implementación de referencia.

**Convenciones**: DEBE/NO DEBE = obligatorio para conformidad.
PUEDE = opcional. *Rationale* = por qué, no vinculante.

---

## 1. Capas y contrato

```
Agente (LLM / humano / job M)
   │  tools MCP (pdb_set, pdb_get, m_eval, mvm_spawn...)
   ▼
pdb_tools.py  ──── único dueño de las conexiones (pdb_connect)
   │
   ├── M-Light  (compilador + stack-VM; triggers, REPL, consola, /vm/execute)
   ├── MVM      (jobs, mailboxes, gas, ^SCHEDULE)
   ▼
PDB (_globals en SQLite WAL)  ──── DDP replica ^namespaces entre nodos
```

- Los consumidores DEBEN acceder al PDB vía tools o `pdb_connect()`
  (pdb_tools) / `_pdb.py` (thinking). `sqlite3.connect` directo está
  prohibido — lo vigila `tests_contract.py`.
- Ruta de BD: env `PDB_PATH` > env `PDB_DB` > `mcp-servers/pdb/lumen-pdb.db`.
- SQLite DEBE operar en `journal_mode=WAL`, `synchronous=NORMAL`.

*Rationale*: un punto de entrada = cambiar el motor es cambiar un sitio.

## 2. Modelo de datos: globals

Un global es un árbol ordenado sin esquema:

```
^NS(sub1, sub2, ..., subN) = valor
```

- **Namespace** (`NS`): string; por convención MAYÚSCULAS o CamelCase (§7).
  En el almacén va SIN el `^` (columna `ns`).
- **Subscripts**: strings o números, hasta cualquier profundidad.
- **Valor**: cualquier JSON (string, número, objeto, lista). Se almacena
  como `json.dumps(valor, ensure_ascii=False)`; al leer se intenta
  `json.loads` con fallback a string crudo. `None` = sin valor.

### 2.1 Codificación de subscripts (encode_subkey) — NORMATIVA

Cada subscript se codifica como `[type_byte][data][0xFF]`:

| Tipo | Formato | Colación |
|------|---------|----------|
| numérico | `0x01` + 8 bytes IEEE 754 double *sortable* + `0xFF` | antes que strings |
| string | `0x02` + UTF-8 + `0xFF` | orden de bytes UTF-8 |
| string vacío `""` | `0x02 0xFF` | primero entre strings |

- La concatenación de subscripts codificados DEBE ordenar igual que el
  orden M canónico: **números primero (valor numérico), después strings
  (orden de bytes)**.
- "Sortable double": se transforma el IEEE 754 para que la comparación de
  bytes coincida con la numérica (flip de signo).
- Toda implementación DEBE producir estos bytes exactos (tests golden).

*Rationale*: $ORDER es un range-scan del B-tree. Esta codificación es la
pieza más portable del proyecto — portarla mal rompe la interoperabilidad
de BD entre motores.

## 3. Operaciones núcleo

| Op | Semántica |
|----|-----------|
| `SET ^NS(s...)=v` | Upsert del nodo. Dispara triggers ON SET e ^IDX. |
| `$GET(^NS(s...))` | Valor del nodo, o `""`/default si no existe. Nunca error. |
| `$DATA(^NS(s...))` | `0` no existe · `1` valor sin hijos · `10` hijos sin valor · `11` ambos. |
| `$ORDER(^NS(s...,x))` | Siguiente subscript del último nivel tras `x` en colación §2.1. `x=""` → primero. Devuelve `""` al agotar. `direction=-1` → anterior (con `""` → último). |
| `KILL ^NS(s...)` | Borra el nodo Y todo su subárbol. Dispara ON KILL. |
| `$INCREMENT(^NS(s...))` | Incremento atómico (+1 o delta). Devuelve el nuevo valor. |
| `MERGE ^A(s)=^B(t)` | Copia el subárbol completo de ^B(t) bajo ^A(s). |

- Los niveles intermedios NO existen implícitamente: `SET ^A(1,2)=x` da
  `$DATA(^A(1))=10`, no crea nodo ^A(1).
- `$ORDER` con menos de 1 subscript es error.

## 4. LOCK

```
LOCK ^NS(s...) [timeout]    → adquirir
UNLOCK ^NS(s...)            → liberar; sin args libera todos los del proceso
```

- Multi-proceso: el lock vive en SQLite (tabla propia), no en memoria.
- `owner = pid_threadid`. Reentrada del mismo owner PUEDE permitirse.
- `timeout=None` bloquea indefinidamente; con timeout devuelve
  `{"locked": false, "error": "timeout"}` — el llamante DEBE comprobarlo.
- No hay detección de deadlock en v0.1: la prevención es responsabilidad
  del llamante (adquirir siempre en el mismo orden). *(spec v2: detección)*

## 5. Lenguaje M-Agent (subset M)

### 5.1 Comandos

`SET/S` (múltiple con coma) · `KILL/K` (local y global) · `NEW/N` ·
`IF/ELSE` (con bloques `{}`) · `FOR/F` (`F i=a:b:c`, infinito con `F `) ·
`QUIT/Q` (con postcondicional `Q:cond`) · `GOTO/G label` ·
`DO/D label|^RUTINA` (call stack, args `$1..$n`) · `WRITE/W`
(`!`, `?n`, `*n`, texto) · `READ/R prompt:var` · `OPEN/USE/CLOSE` ·
`HALT` · comentario `;`

### 5.2 Funciones intrínsecas

`$GET/$G` · `$DATA/$D` · `$ORDER/$O` · `$PIECE/$P` · `$EXTRACT/$E` ·
`$SELECT/$S` · `$LENGTH/$L` · `$FIND/$F` · `$TRANSLATE/$TR` · `$VIEW`
(emulación de memoria MSM; ver `pdb/references/zfuncs-runtime-dispatch.md`)

### 5.3 Variables de sistema

`$J` (pid del job) · `$IO` (dispositivo actual) · `$ECODE`/`$ZERROR`
(error trap nativo en la stack-VM)

### 5.4 Semántica de evaluación

- **Aritmética estrictamente izquierda-a-derecha, sin precedencia**
  (es M: `2+3*4 = 20`). Operadores: `+ - * / \ #` (`\` división entera,
  `#` módulo).
- `+expr` fuerza cast numérico; variable indefinida vale `0` en aritmética.
- Literales hex `#FF` = 255.
- Strings: comillas dobles; `""` dentro de string = comilla escapada.

### 5.5 Fuera del subset v0.1 (reservado spec v2)

- **Indirection `@`** — existe embrión a nivel tool (`pdb_indirect.py`);
  el operador en el evaluador es v2.
- **TSTART/TCOMMIT/TROLLBACK** — transacciones multi-clave.
- `$QUERY`, `$NAME`, `XECUTE`, patrones `?`.

*Rationale*: lo que no está aquí NO se promete. Un LLM entrenado con esta
spec no debe generar sintaxis fuera del subset.

## 6. Modelo de ejecución: MVM

Un **job** es un proceso M cooperativo persistido en PDB:

- `$J`: entero secuencial. Estado en `^PROCESSES($J)` + `^STATE($J,...)`.
- **Estados**: `READY → RUNNING → WAITING|BLOCKED → READY → ... → DEAD`,
  más `HALTED` (pausa externa) e `HIBERNATE` (despierta vía `^SCHEDULE`).
- **Gas**: `gas_limit` = instrucciones por tick (default 1000);
  `gas_budget` = presupuesto de vida (0 = ilimitado). Agotar el budget →
  error `GAS_EXHAUSTED` y el proceso muere.
- **Dispositivos** (`$IO`): 0 consola · 99 **mailbox IPC entre jobs** ·
  HTTP · webhook (servidor efímero) · log · dashboard · PDB device.
- **Mailbox**: `mvm_mailbox_send/read`; el job en `WAITING` despierta al
  recibir. **Outbox**: mensajes job→agente con ack.
- **Durabilidad**: `mvm_state_export/import/save/restore` — un job puede
  serializarse, viajar por DDP y reanudarse en otro nodo. El gas viaja
  con el estado.
- El scheduler es cooperativo: `mvm_tick` ejecuta un slice de cada READY.
  Nada DEBE asumir preemption.

*Rationale*: "durable execution" (Temporal/DBOS) desde el diseño: el
proceso ES datos en ^STATE, no un proceso de OS.

## 7. Convención de namespaces

| Namespace | Uso | Dueño |
|-----------|-----|-------|
| `^System` | pulse, decisions, identidad, gobernanza (ver `pdb-sync/SYSTEM_SCHEMA.md`) | Lisa escribe, todos leen |
| `^STATE` | estado de jobs MVM + thinking server | MVM/thinking |
| `^PROCESSES` | tabla de procesos MVM | MVM |
| `^SCHEDULE` | despertares HIBERNATE/cron | MVM |
| `^ROUTINE` | rutinas M + bytecode cache (SHA256) | M-Light |
| `^CHANGES` | journal DDP v2: `("seq")` contador, `("journal",seq)` entries, `("cursor",name)` consumidores | pdb_journal |
| `^IDX` | auto-índices | pdb_tools |
| `^SUBSCRIPTIONS` | suscripciones persistentes | pdb_tools |
| `^CONTEXT` | memoria de trabajo cognitiva (con GC) | agentes |
| `MAP_CFG` / `PART_CFG` | mapeo ns→fichero / particionado | pdb_tools |
| `^TEST`, `^STRESS` | libres para tests — pueden borrarse | tests |
| `^Zalo`, `^Hermes`... | namespace propio por agente | cada agente |

Regla: un subsistema NO DEBE escribir en namespace ajeno sin pasar por
su dueño (hasta que existan macaroons por namespace — Fase 3).

## 8. Contrato de acceso (resumen ejecutable)

1. Operaciones de datos → tools `pdb_*` (aplican triggers, índices, journal).
2. SQL crudo justificado (bulk, migraciones, lecturas raw) →
   `pdb_connect()` / `pdb_connect(readonly=True)`. Nunca `sqlite3.connect`.
3. Rutas → `_paths.py` (pdb-sync) / `_pdb.py` (thinking). Cero absolutas.
4. El guard es `tests_contract.py`; su allowlist solo puede encoger.

## 9. Suite de conformidad

Runner: `implementations/python/pdb-sync/run_conformance.py`.
Un motor es conforme si pasa todas las categorías **offline**:

| Categoría | Tests |
|-----------|-------|
| lenguaje | tests_stackvm, tests_compiler, tests_compiler_full, tests_bytecode_vm, tests_funcs, tests_for, tests_m_light_errors |
| imperativos | tests_imp01_write, tests_imp02_arith, tests_imp03_global, tests_imp04_do, tests_imp05_for_order |
| globals | tests_type, tests_contains, tests_d6, tests_bij |
| rutinas | tests_routines, tests_mrepl |
| journal | tests_journal, tests_journal_integration, tests_journal_daemon |
| mvm | tests_msajob, tests_msasys |
| contrato | tests_contract |
| integridad | tests_integrity, tests_watchdog |

Categorías **online** (necesitan edge/red, no bloquean conformidad):
ddp (tests_ddp_client, tests_sync_engine), consola (tests_console*,
tests_logon — necesitan puertos).

### Fixture de conformidad

Los tests legacy asumían la BD viva del equipo. El runner siembra un
fixture mínimo si `^System` está vacío (claves agents..startup, config
sin valor propio, 12 rutinas ZFIXnn en ^ROUTINE) — la suite es
autocontenida en una BD nueva. En la BD del equipo el fixture no escribe.

### Baseline de la implementación de referencia (2026-07-14)

**✅ 425/425 — baseline cerrado a 0**, estable en doble pasada (BD virgen
y re-ejecución sobre la misma BD).

Bugs de motor encontrados y arreglados al cerrar el baseline (regla de
la spec: test incorrecto → se arregla el test; motor incorrecto → se
arregla el motor; nunca se ignora en silencio):

1. **`tool_data` daba falso positivo de hijos**: con el nodo ausente,
   `$DATA` devolvía 10 si existía CUALQUIER clave posterior del
   namespace (query `subkey > key+0x00` sin cota de prefijo). Ahora
   usa prefix-check del siguiente subkey, como el branch con valor.
2. **Bytecode cache indexaba instrucciones como string**: `$ORDER`
   devolvía "10" antes que "2" → bytecode reordenado en rutinas de
   ≥11 instrucciones. Ahora índice numérico + sort defensivo.
3. **El cache no persistía `labels`**: `D label`/`GOTO` fallaban al
   ejecutar desde cache (solo funcionaba recién compilado).
4. **`StackVM.__init__` no creaba `call_stack`/`labels`**: ejecutar
   bytecode sin pasar por `compile()` lanzaba AttributeError (M99).
5. **`JournalDaemon.stop()` tardaba hasta `interval` segundos**:
   `sleep` en el loop → `Event.wait` interrumpible.
6. `tests_imp04_do.py` usaba `f` sin definir en print/exit — nunca
   había reportado resultado.

Tests hechos autocontenidos: `tests_msajob` (siembra sus pulses),
`tests_bij` (limpia sus tx previas); fixture de rutinas con
`^ROUTINE("INDEX")` para `tests_integrity`.

## 10. Versionado de la spec

- v0.1 (2026-07-14): estado actual congelado. Cambios de semántica → PR
  que toque spec + tests a la vez. Incluye journal DDP v2 (seq monótono
  + cursores, Fase 2).
- v2 (previsto): `@`, TSTART/TCOMMIT, changefeed de suscripciones,
  detección de deadlock, macaroons por namespace.
