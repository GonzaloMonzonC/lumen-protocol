# Spec M-Agent v0.3 — lenguaje M + modelo de ejecución LUMEN

> Documento normativo del subset M soportado, la semántica de los globals,
> el modelo de jobs (MVM) y el contrato de acceso a datos.
>
> Fecha: 2026-07-15 · Estado: **v0.3** (Fases 0-6 del PLAN_EVOLUCION)
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
   ├── M-Light  (Python o Rust; compilador + stack-VM)
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
LOCK ^NS(s...)[:timeout]    → adquirir (comando M: LOCK/L)
UNLOCK ^NS(s...)[,...]      → liberar; sin args libera todos los del proceso
LOCK                        → sin argumento libera todos (M estándar)
```

- Multi-proceso: el lock vive en SQLite (`_lock_table`), no en memoria.
- `owner = pid_threadid` para llamadas por tools; los jobs MVM usan
  `owner = mvm_<$J>`. La reentrada del mismo owner adquiere (contador).
- **Comando M (v0.3, stack-VM Rust)**: sin timeout el LOCK bloquea
  *cooperativamente* — la VM hace un intento no bloqueante y, si falla,
  cede el slice y el job queda `BLOCKED`; el scheduler reintenta la misma
  instrucción en ticks posteriores. Nunca se bloquea el scheduler.
- Con `:timeout` (segundos; `0` = un intento) el resultado queda en
  `$TEST` y la ejecución continúa — el llamante DEBE comprobarlo.
  Vía tools, el timeout devuelve `{"locked": false, "error": "timeout"}`.
- Un job que muere (`DEAD`) libera automáticamente todos sus locks.
- No hay detección de deadlock en v0.3: la prevención es responsabilidad
  del llamante (adquirir siempre en el mismo orden). *(spec v2: detección)*

## 5. Lenguaje M-Agent (subset M)

### 5.1 Comandos

`SET/S` (múltiple con coma) · `KILL/K` (local y global) · `NEW/N` ·
`IF/ELSE` (con bloques `{}`) · `FOR/F` (`F i=a:b:c`, infinito con `F `) ·
`QUIT/Q` (con postcondicional `Q:cond`) · `GOTO/G label` ·
`DO/D label|^RUTINA` (call stack, args `$1..$n`) · `WRITE/W`
(`!`, `?n`, `*n`, texto) · `READ/R prompt:var` · `OPEN/USE/CLOSE` ·
`LOCK/L` / `UNLOCK` (v0.3, semántica en §4) · `HALT` · comentario `;`

### 5.2 Funciones intrínsecas

`$GET/$G` · `$DATA/$D` · `$ORDER/$O` · `$PIECE/$P` · `$EXTRACT/$E` ·
`$SELECT/$S` · `$LENGTH/$L` · `$FIND/$F` · `$TRANSLATE/$TR` ·
`$ASCII/$A` (posición 1-based; fuera de rango → -1) ·
`$CHAR/$C` (código inválido → `?`, paridad con la referencia) ·
`$FNUMBER/$FN` (v0.3; códigos `,` `+` `-` `T` `P`, redondeo mitad-lejos-de-cero) ·
`$VIEW` (emulación de memoria MSM; ver `pdb/references/zfuncs-runtime-dispatch.md`)

### 5.3 Variables de sistema

`$J` (pid del job) · `$IO` (dispositivo actual) · `$ECODE`/`$ZERROR`
(error trap nativo en la stack-VM) · `$TLEVEL` (nivel de transacción) ·
`$HOROLOG/$H` (v0.3; `días,segundos` desde 1840-12-31 **en UTC** —
determinismo entre motores y nodos) · `$TEST/$T` (v0.3; resultado del
último LOCK con timeout, serializado en el estado del job)

### 5.4 Semántica de evaluación

- **Aritmética estrictamente izquierda-a-derecha, sin precedencia**
  (es M: `2+3*4 = 20`). Operadores: `+ - * / \ #` (`\` división entera,
  `#` módulo).
- `+expr` fuerza cast numérico; variable indefinida vale `0` en aritmética.
- Literales hex `#FF` = 255.
- Strings: comillas dobles; `""` dentro de string = comilla escapada.

### 5.5 Extensiones v0.2

- **Indirection `@`**: `@expr` y `@(expr)` evalúan `expr` y usan el string
  resultante como nombre de variable local o referencia global completa.
  Es válido en lectura, `SET` y `KILL`. Un destino vacío produce
  `MINDIRECT`; no se ejecuta texto arbitrario como código.
- **`TSTART` / `TCOMMIT` / `TROLLBACK`**: transacciones multi-clave,
  anidables. Commit o rollback sin `TSTART` activo produce `MTRANSACTION`.
  Un error revierte todos los niveles abiertos.
- Una sección transaccional es atómica también para el scheduler: NO cede
  por `gas_limit` entre `TSTART` y commit/rollback. `gas_budget` sí se aplica
  y evita una transacción infinita.
- **Las rutinas externas (`D ^RUTINA`) son igualmente atómicas respecto al
  scheduler** (v0.3): no ceden por `gas_limit` a mitad — una rutina
  reiniciada a mitad repetiría efectos. `gas_budget` sí las corta. Un
  `READ`/`LOCK` bloqueante dentro de una rutina externa reinicia la rutina
  al reintentar: mantenerlos en el código top-level del job.

Continúan fuera del subset: `$QUERY`, `$NAME`, `XECUTE` y patrones `?`.

*Rationale*: lo que no está aquí NO se promete. Un LLM entrenado con esta
spec no debe generar sintaxis fuera del subset.

## 6. Modelo de ejecución: MVM

Un **job** es un proceso M cooperativo persistido en PDB:

- `$J`: entero secuencial. Estado en `^PROCESSES($J)` + `^STATE($J,...)`.
- **Estados**: `READY → RUNNING → WAITING|BLOCKED → READY → ... → DEAD`,
  más `HALTED` (pausa externa) e `HIBERNATE` (despierta vía `^SCHEDULE`).
  `BLOCKED` = LOCK sin adquirir: el scheduler reintenta la misma
  instrucción en cada tick; al morir el job se liberan sus locks.
- **Gas**: `gas_limit` = instrucciones por tick (default 1000);
  `gas_budget` = presupuesto de vida (0 = ilimitado). Agotar el budget →
  error `GAS_EXHAUSTED` y el proceso muere.
- Los frames de `FOR`, el instruction pointer, call stack, scopes locales,
  variables, pila y contadores de gas forman parte del estado serializado.
  Reanudar NO repite iteraciones ya ejecutadas.
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

### 8.1 Autorización por namespace: macaroons (Fase 3)

Tokens de capacidad atenuables, port 1:1 de `rust/src/macaroon.rs`
(`pdb/pdb_macaroon.py`) — **compatibilidad byte a byte verificada con
test golden cruzado** (`rust/tests/macaroon_golden.rs`).

- **Cadena**: `sig = HMAC-SHA256(root_key, id)`; cada caveat encadena
  `sig = HMAC-SHA256(sig, caveat)`. Atenuar NO requiere la root key;
  solo estrecha permisos.
- **Caveats PDB**: `ns_prefix = X` (el ns accedido DEBE empezar por X;
  varios = intersección) · `op = read|write` · `expiry < ISO8601`
  (auto-verificado) · `tool = nombre`. Caveat desconocido → rechazo
  (fail-closed).
- **Root key**: env `PDB_MACAROON_KEY` (hex 64) > `~/.hermes/pdb-macaroon.key`
  (auto-generada, 0600).
- **Enforcement**: bridge PDB (`PDB_MACAROON_REQUIRED=1`, token en
  `args["_macaroon"]` o env `PDB_MACAROON`; tools de lectura en
  `READ_TOOLS`, el resto es write fail-closed) y DDP (env `DDP_MACAROON`:
  header `X-DDP-Macaroon` hacia el edge + gate local en SyncEngine —
  pull/apply=write, push=read).
- **CLI**: `pdb_macaroon.py keygen|mint|inspect|verify`.

*Rationale*: multi-agente externo con permisos por subárbol sin
coordinar con el emisor — un agente puede delegar a otro un token más
estrecho que el suyo.

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
| mvm | tests_msajob, tests_msasys, tests_mvm_rust (Tokio/live SQLite), tests_mvm_differential |
| contrato | tests_contract |
| M-Light Rust | tests_rust_mlight (golden compartido, FFI, gas, SQLite) |
| integridad | tests_integrity, tests_watchdog |

Categorías **online** (necesitan edge/red, no bloquean conformidad):
ddp (tests_ddp_client, tests_sync_engine), consola (tests_console*,
tests_logon — necesitan puertos).

### Fixture de conformidad

Los tests legacy asumían la BD viva del equipo. El runner siembra un
fixture mínimo si `^System` está vacío (claves agents..startup, config
sin valor propio, 12 rutinas ZFIXnn en ^ROUTINE) — la suite es
autocontenida en una BD nueva. En la BD del equipo el fixture no escribe.

### Baseline de la implementación de referencia (2026-07-15)

**✅ 519/519 — baseline cerrado a 0**. Incluye `storage` redb (38),
`seguridad` macaroons (31) y `mlight_rust` (21), además del baseline Python.
La persistencia canónica usada por conformidad continúa siendo SQLite.

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
- v0.1 addendum (2026-07-14): macaroons por namespace (§8.1, Fase 3).
- v0.2 (2026-07-15): `@`, TSTART/TCOMMIT/TROLLBACK y contrato de estado/gas
  serializable; implementación Rust + golden compartido (§5.5, Fase 5).
- v0.3 (2026-07-15): comando `LOCK/UNLOCK` en la stack-VM Rust (bloqueo
  cooperativo, estado `BLOCKED`, `$TEST`, liberación al morir, owner
  `mvm_<$J>` sobre `_lock_table`); `$ASCII/$A` y `$CHAR/$C` (paridad con
  la referencia Python); `$FNUMBER/$FN` (ambos motores) y `$HOROLOG/$H`
  en UTC (stack-VM Rust); `RedbHost` — el trait Host de la VM directamente
  sobre el crate lumen-pdb (redb), con TSTART anidado por undo-log: la VM
  Rust corre standalone sin el puente Python.
- v0.4 (previsto): changefeed de suscripciones, detección de deadlock y
  verificación de macaroons en el edge worker.
