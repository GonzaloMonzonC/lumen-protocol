# Plan de evolución: PDB + M-Light + MVM

> Hoja de ruta técnica para el núcleo del ecosistema LUMEN.
> Dirigido al equipo actual y nuevos miembros.
>
> Fecha: 2026-07-14 · Autores: Gonzalo + Zalo + Hermes
> Revisión: v1.1 — corregido contra el código real (ver `ajustes.md` en raíz).
> Documento canónico: este fichero. Los borradores pegados en chat quedan superseded.

---

## 0. Resumen ejecutivo

LUMEN no es "un MUMPS para personas". Es una **pila de ejecución para agentes**:

```
Agentes (Hermes, Zalo, Lisa, Tom, Angi, Campo...)
├── M / M-Light        ← lenguaje de ejecución para agentes
├── MVM                ← jobs, rutinas, mailboxes, cron
├── PDB (^GLOBALS)     ← memoria compartida jerárquica sin esquema
├── LUMEN              ← transporte binario zero-copy (SHM, QUIC)
└── DDP                ← replicación del mismo namespace entre nodos
```

Cada capa está optimizada para el recurso escaso del agente: el **token y el
round-trip**. M comprime el programa (~15 tokens vs ~10.000 en tool-calls JSON),
los globals comprimen el esquema (no hay), LUMEN comprime el cable, DDP comprime
la distancia.

**El problema actual:** la implementación es Python puro (~24.000 líneas, bus
factor 1). El concepto es correcto; el motor tiene techo.

**El plan:** congelar la superficie (spec), optimizar el motor por dentro sin que
los consumidores lo noten.

---

## 1. ¿Qué tenemos hoy? (verificado 2026-07-14)

### PDB — almacén jerárquico KV sobre SQLite

- ~3.200 líneas en `implementations/mcp-servers/pdb/pdb_tools.py`
- Operaciones: SET/GET/$ORDER/$DATA/KILL/$INCREMENT/MERGE/LOCK/batch/query
- Auto-índices ^IDX, triggers ON SET/ON KILL, FTS5, embeddings (sqlite-vec)
- **15 μs/GET, 58K GET/s, 27K insert/s**
- Codificación orden-preservante de subkeys (portable byte a byte)

### M-Light — intérprete M (dos generaciones conviviendo)

- **v1**: ~1.350 líneas en `mcp-servers/pdb/m_light.py` — intérprete directo,
  emulación de memoria de sistema MSM para $VIEW, stub inteligente (41) con
  runtime dispatch (ver `pdb/references/zfuncs-runtime-dispatch.md`)
- **v2**: compilador (`pdb-sync/m_light_compiler.py`) + stack-VM
  (`pdb-sync/m_stackvm.py`, VM_VERSION 2.0.0) con bytecode cache en ^ROUTINE
  e invalidación SHA256
- ~70% de la sintaxis MSM STU: $O/$G/$D/$P/$E/$S/$L/$F/$TR,
  FOR/IF/GOTO/DO/QUIT/NEW, READ/WRITE/OPEN/USE/CLOSE
- Superficies de ejecución: triggers, pdb_m_eval, REPL M, consola web
  (`m_console.py`, puertos 8084/8085, ZW/ZR/ZJOB), API HTTP
  `POST /vm/execute` (`vm_api.py`, puerto 8081), dashboards D^SS/D^GS/D^%SS

### MVM — scheduler de procesos M

- ~1.550 líneas en `mcp-servers/pdb/mvm.py` (⚠ no en pdb-sync como decía el
  borrador anterior)
- Estados: READY/RUNNING/WAITING/BLOCKED/HALTED/HIBERNATE/DEAD
- Mailboxes ($IO 99), jobs background tipo cron, gas por tick
- **Estado de proceso persistido en ^STATE/^PROCESSES** — clave para ejecución durable

### DDP — sincronización distribuida (más avanzado de lo que se creía)

Hay **dos implementaciones paralelas** que hay que consolidar:

1. `implementations/ddp_sync.py` — pull de rutinas desde Cloudflare Worker;
   push local→edge es no-op (`pdb_get_pending_local` devuelve `[]`,
   ddp_sync.py:131-139)
2. **Suite pdb-sync** (la nueva, funcional): `pdb_journal.py` (journal en
   ^CHANGES con source tagging y anti-bucle), `pdb_journal_daemon.py`,
   `pdb_journal_ddp_bridge.py`, `pdb_journal_recovery.py`,
   `pdb_sync_engine.py`, `pdb_ddp_client.py`. Mirroring bidireccional
   local↔edge validado (TEST-01 7/7, TEST-02 5/5, TEST-04 12/12,
   pipeline ~180ms RTT)

⚠ **Colisión de nombres:** el equipo llama "WAL" al journal de aplicación
(`pdb_journal.py` → ^CHANGES). No confundir con el `journal_mode=WAL` de
SQLite. En docs nuevos: "journal DDP" para el de aplicación, "SQLite WAL"
para el pragma.

### Lo que NO funciona bien hoy

| Problema | Impacto | Causa raíz |
|----------|---------|------------|
| ~~Escritura lenta~~ ✅ RESUELTO 2026-07-14 | Era ~115-130 SET/s; ahora 15-21K SET/s vía tool_set (ver BENCHMARKS.md) | `journal_mode=DELETE` → WAL centralizado en `_apply_pragmas()` |
| ~~Conflicto WAL/DELETE activo~~ ✅ RESUELTO 2026-07-14 | Producía `database is locked` intermitentes | Todas las conexiones usan ya WAL; verificado 1 escritor + 3 lectores concurrentes sin errores |
| Sin concurrencia real | Una conexión SQLite única con lock de thread | `check_same_thread=False` + single connection |
| ~~DDP duplicado~~ ✅ RESUELTO 2026-07-14 | `ddp_sync.py` es wrapper deprecated de la suite pdb-sync; push ya no es no-op | Una sola implementación canónica |
| ~~Journal sin seq monótono~~ ✅ RESUELTO 2026-07-14 | `^CHANGES("journal", seq)` + cursores + migrate_legacy | Orden total de replay garantizado |
| ~~22 accesos directos a SQLite~~ ✅ RESUELTO 2026-07-14 | 15 consumidores migrados a `pdb_connect()`/`_pdb.py`; guard ratchet en `tests_contract.py` | Quedan solo bench/tests exentos |
| ~~Rutas hardcodeadas rotas~~ ✅ RESUELTO 2026-07-14 | 83 ficheros migrados a `_paths.py` (repo-relativo) | Quedan solo scripts legacy de bench/debug con rutas Windows |
| Sin spec formal | El código ES la especificación | No hay documento normativo del subset M |
| ~~Sin multi-tenancy~~ ✅ RESUELTO 2026-07-14 | Macaroons con caveats ns_prefix/op en bridge y DDP | Falta verificación en el edge worker (v2) |
| Sin TSTART/TCOMMIT | Dos agentes no pueden mantener invariantes atómicos | Falta transacciones multi-clave |
| Indirection (@) incompleta | No se puede ejecutar un nombre de global contenido en una variable desde M | Existe embrión a nivel tool (`pdb_indirect.py` + tests); falta el operador @ en M-Light |

---

## 2. La estrategia: spec first, motor después

El principio rector: **separar el QUÉ del CÓMO**.

- **QUÉ** (la superficie): globals + M + jobs + DDP. Eso es el producto. No cambia.
- **CÓMO** (el motor): SQLite hoy, redb mañana, Rust pasado mañana. Eso es
  sustituible.

### 2.1 Cerrar el contrato de datos (PDB API)

Hoy el "contrato" son las tools: `pdb_set`, `pdb_get`, `pdb_order`, `pdb_data`,
`pdb_kill`, `pdb_incr`, `pdb_merge`, `pdb_lock`, `pdb_batch_set`, `pdb_query`,
`pdb_fts_search`...

Pero **22 ficheros abren SQLite directamente** (~14 de producción: 10 en
`thinking/`, `ddp_sync.py`, y `pdb_type.py`/`pdb_help_system.py`/`pdb_ttl.py`/
`m_routines.py` en pdb-sync; el resto son bench/tests exentables).

**Acción:** para cada consumidor de producción:
- Si hace algo que ya tiene tool → refactorizar para usar la tool
- Si hace algo nuevo → añadir tool nueva
- Prohibir `sqlite3.connect` fuera de `pdb_tools.py`
- **Una sola fuente de `PDB_PATH`** (env var + default), cero rutas hardcodeadas

Resultado: **1 punto de entrada**. Cambiar SQLite por redb = cambiar 1 sitio.

### 2.2 Spec M-Agent (lenguaje M + modelo de ejecución)

Documento normativo que defina:
1. El subset M soportado: sintaxis, funciones, operadores, bordes
2. La semántica de los globals: $ORDER, $DATA, KILL, MERGE, LOCK
3. El modelo de jobs: estados, mailboxes, gas, persistencia en ^STATE
4. Convención de nombres de ^GLOBALS (ver `pdb-sync/SYSTEM_SCHEMA.md` como base)
5. Modelo de locks: $LOCK semántica, timeouts, deadlock prevention
6. Diagrama de capas: API tools → M-Light → PDB → SQLite
7. Suite de conformidad: tests que cualquier implementación debe pasar

**Para qué sirve:**
- Es el contrato que enseñas a los LLMs para que generen M correcto
- Es la base para portar a Rust: pasas spec + tests, no "porta m_light.py"
- Permite contribuciones externas sin leer 24K líneas
- Separa el QUÉ (spec) del CÓMO (implementación)

**Riesgo a evitar:** que la spec sea muy seca. Cada sección incluye rationale breve.

**Nota de secuencia (corrección v1.1):** `@` y TSTART/TCOMMIT deben
implementarse **en Python primero** (Fase 0-1; `@` ya tiene embrión en
`pdb_indirect.py`) para que la suite de conformidad los cubra antes del port
a Rust. Si no, la spec describiría features sin implementación de referencia.
Alternativa: marcarlos explícitamente como "spec v2".

---

## 3. Plan de ejecución por fases

```
Fase 1a: Fix WAL + rutas                 ✅ HECHA (2026-07-14, ver §3.1)
Fase 1b: Contrato PDB API                ✅ HECHA (2026-07-14, ver §3.2)
Fase 0:  Spec M-Agent                    ✅ v0.1 ENTREGADA (spec-m-agent.md)
Fase 2:  DDP: consolidar + seq monótono  ✅ HECHA (2026-07-14, ver §3.3)
Fase 3:  Macaroons por namespace         ✅ HECHA (2026-07-14, ver §3.4)
Fase 4:  Crate lumen-pdb (redb)           ✅ HECHA (2026-07-15, ver §3.5)
Fase 5:  M-Light en Rust                  ✅ HECHA (2026-07-15, ver §3.6)
Fase 6:  MVM sobre tokio                  ✅ HECHA (2026-07-15, ver §3.7)
```

### Fase 1a — Fix WAL + rutas — ✅ HECHA (2026-07-14)

1. ✅ `PRAGMA journal_mode=WAL` + `synchronous=NORMAL` + `mmap_size=256MB`
   centralizados en `_apply_pragmas()` (pdb_tools.py) — resuelve el
   conflicto activo con pdb_ttl.py. Benchmark vía API: 15-21K SET/s
   sostenidos (era ~115-130); 1 escritor + 3 lectores concurrentes en
   procesos separados, 0 `database is locked` (ver BENCHMARKS.md)
2. ✅ Rutas unificadas: `pdb-sync/_paths.py` (repo-relativo desde
   `__file__`, env `PDB_PATH` > `PDB_DB` > default) — 81 ficheros de
   pdb-sync migrados + ddp_sync.py + ddp_cron.py
3. ✅ Verificado: 83 tests offline en verde (stackvm 28, compiler 12,
   journal 16, indirect 13, bij 14) + smoke test desde cwd ajeno
4. Pendiente menor: statements preparados cacheados (micro-opt, baja prioridad)

**Riesgo (corrección v1.1 — antes decía "ninguno"):**
- `synchronous=NORMAL` en WAL puede perder las últimas transacciones ante
  corte de energía (aceptable para este caso de uso, pero queda dicho)
- WAL deja ficheros `-wal`/`-shm`: los scripts de backup que copien el `.db`
  a pelo deben hacer checkpoint antes o copiar los tres ficheros
- Revertir requiere `PRAGMA wal_checkpoint(TRUNCATE)` previo

### Fase 0 — Spec M-Agent — ✅ v0.1 ENTREGADA (2026-07-14)

- `docs/spec-m-agent.md`: subset M, semántica de globals (encode_subkey
  normativa, $ORDER/$DATA/KILL/LOCK), modelo MVM (estados/gas/mailboxes),
  convención de namespaces, contrato de acceso, versionado
- `pdb-sync/run_conformance.py`: suite por categorías con fixture
  autocontenido. Baseline: **✅ 425/425 (cerrado a 0, doble pasada
  estable)** — cerró 4 bugs de motor reales: $DATA falso positivo de
  hijos, bytecode cache desordenado (idx string) y sin labels,
  StackVM sin call_stack fuera de compile, daemon stop lento
- Pendiente v0.x: revisar la spec con Gonzalo (visión)

### Fase 1b — Contrato PDB API — ✅ HECHA (2026-07-14)

1. ✅ `pdb_connect(readonly=)` público en pdb_tools (ruta env-aware
   PDB_PATH>PDB_DB, PRAGMAs WAL, readonly vía query_only) + `thinking/_pdb.py`
2. ✅ 15 consumidores de producción migrados (~30 sitios): thinking/
   (server, objective_loop, pdb_ns, m_commands, file_tools, pdb_watch,
   fuzzy_search, d_routine_server, replace_gl), pdb-sync (ttl, type,
   help_system, m_routines, pdb-sync.py), ddp_sync.py
3. ✅ Bonus: los dos bridge plugins tenían `_find_server()` roto
   (solo miraba ~/Documents/GitHub) — arreglados con __file__-relativo
   + env LUMEN_PDB_SERVER
4. ✅ Guard ratchet `tests_contract.py` (5/5): prohíbe sqlite3.connect
   y rutas hardcodeadas fuera del allowlist; el allowlist solo encoge

### Fase 2 — DDP: consolidar + seq monótono — ✅ HECHA (2026-07-14)

1. ✅ **Journal v2**: `^CHANGES("journal", seq)` con seq atómico
   ($INCREMENT), cursores por consumidor (`^CHANGES("cursor", name)`) y
   `migrate_legacy()` idempotente para las entries v1 ts-keyed.
   Verificado: 15/15 tests nuevos (`tests_journal_seq.py`) — colisiones
   de ts resueltas, orden total, purge por seq
2. ✅ **Push incremental**: `SyncEngine.push_pending` usa cursor "push"
   (at-least-once; el cursor solo avanza tras push confirmado)
3. ✅ **Consolidación**: `ddp_sync.py` es ahora wrapper deprecated de la
   suite pdb-sync (misma API para `ddp_cron.py`); su push ya NO es no-op
4. ✅ **Bugs reales cazados por el smoke E2E contra el edge vivo**:
   `pull_and_apply` crasheaba con claves formato encode_subkey (las que
   subió full_sync) y `SyncEngine._log` no existía
5. ✅ **Verificado contra edge real** (ddp-v0.2): pull 500 entries,
   pull incremental por checkpoint, round-trip journal→push→edge
6. Pendiente: changefeed para suscripciones (mover a Fase 3+, sin bloqueo)

### Fase 3 — Macaroons por namespace — ✅ HECHA (2026-07-14)

1. ✅ `pdb/pdb_macaroon.py`: port 1:1 de `macaroon.rs` — **compat byte a
   byte verificada** con test golden cruzado (`rust/tests/macaroon_golden.rs`,
   cargo test 2/2: Rust codifica idéntico a Python y verifica tokens Python)
2. ✅ Caveats: `ns_prefix` (varios = intersección), `op = read|write`,
   `expiry` auto-verificado, `tool`. Fail-closed ante caveats desconocidos
3. ✅ Enforcement bridge: gate en `_call_tool` de ambos plugins
   (`PDB_MACAROON_REQUIRED=1`; token en `_macaroon` arg o env)
4. ✅ Enforcement DDP: header `X-DDP-Macaroon` (client) + gate local en
   SyncEngine (push=read, pull/apply=write)
5. ✅ CLI mint/inspect/verify/keygen; root key env o `~/.hermes/` (0600)
6. ✅ `tests_macaroon.py` 31/31 → conformidad **456/456**
7. Pendiente (v2): verificación en el edge worker (Cloudflare, repo aparte)

**Por qué:** multi-agente externo seguro. La sinergia LUMEN+PDB está aquí.

### Fase 4 — Crate lumen-pdb (redb) vía FFI — ✅ HECHA (2026-07-15)

1. ✅ `subkey.rs`: puerto 1:1 de `encode_subkey`/`decode_subkey`; 31 vectores
   golden Python fijan vacíos, `None`, negativos, floats, Unicode y multinivel.
2. ✅ `globals.rs`: SET/GET/$ORDER/$DATA/KILL/$INCREMENT/MERGE sobre redb.
3. ✅ `ffi.rs`: C ABI + `cdylib`, bulk set y flush durable.
4. ✅ `lumen_pdb.py`: wrapper ctypes y `PDB_ENGINE=redb|sqlite` con fallback.
5. ✅ `pdb_migrate.py`: bulk SQLite→redb, destino seguro y verificación raw
   completa opcional.
6. ✅ `tests_redb.py` incorporado a conformidad: storage 38/38; suite offline
   completa 494/494. Rust: 4/4 + fmt + clippy sin warnings.
7. ✅ Benchmark reproducible y JSON raw en `implementations/rust/lumen-pdb/`.

**Riesgo:** divergencias en el encoding — mitigado con tests golden.

**Resultado de rendimiento local:** GET equivalente (~321k SQLite vs ~328k
redb ops/s), pero redb pierde claramente en commits unitarios (~5.5k vs ~90k
SET/s). No cambiar el motor por rendimiento sin benchmark concurrente/batch en
el hardware objetivo. La API redb cubre el núcleo; extensiones como historial,
triggers, particionado y SQL libre permanecen SQLite-only.

**Decisión:** producción continúa sobre SQLite. redb queda como motor
experimental/intercambiable y prueba de portabilidad, no como default.

### Fase 5 — M-Light en Rust — ✅ HECHA (2026-07-15)

1. ✅ Crate `lumen-m-light`: compilador a bytecode versionado (SHA256) y
   stack-VM Rust contra spec M-Agent v0.2.
2. ✅ Indirection `@` integrada en lecturas, SET y KILL, local y global.
3. ✅ TSTART/TCOMMIT/TROLLBACK anidables; rollback automático en error;
   secciones atómicas no ceden a mitad de transacción.
4. ✅ Estado serializable: IP, stack, locals, call stack, scopes, frames FOR,
   output, error y gas. `save_state/load_state` persisten en ^STATE.
5. ✅ C ABI JSON (`cdylib`) + wrapper ctypes; `MLIGHT_ENGINE=rust` opt-in con
   fallback Python. SQLite sigue siendo canónico y la persistencia pasa por
   `pdb_tools` (triggers, índices y journal).
6. ✅ 8 vectores golden compartidos Rust/Python; Rust 17/17 tests (3 unit +
   14 integración), wrapper 21/21 y categoría de conformidad dedicada.
7. ✅ Benchmark reproducible: Rust acelera el FOR 100 ~4x incluso pagando
   ABI JSON; scripts diminutos quedan dominados por serialización.

**Límite deliberado de Fase 5:** el adaptador SQLite usa snapshot optimista
de los namespaces referenciados y aplica el diff final en una transacción
SQLite única por la API PDB. El commit es atómico y valida precondiciones para
rechazar lost updates sobre las claves tocadas. Ese límite solo aplica a
`execute_sqlite()` aislado: el Host live de Fase 6 ya elimina el snapshot para
Jobs y cubre namespaces mapeados/partidos.

**Importante:** no se sustituye M por otro lenguaje. M es el ISA de los
agentes. Se porta, no se reemplaza.

### Fase 6 — MVM sobre tokio — ✅ HECHA (2026-07-15)

1. ✅ Crate `lumen-mvm`: un actor/task Tokio por Job, scheduler cooperativo
   round-robin y mailbox `tokio::sync::mpsc`.
2. ✅ Host SQLite live mediante callback C ABI: `$GET/SET/$ORDER/$DATA/KILL`,
   rutinas y TSTART/TCOMMIT/TROLLBACK pasan por `pdb_tools`; desaparece el
   snapshot/diff de Fase 5 para Jobs y funcionan namespaces mapeados.
3. ✅ Estado completo M-Light + gas persistido automáticamente por transición
   en `^STATE(pid,"rust_snapshot")`, junto con los campos legacy, mediante un
   batch SQLite atómico. Restore automático al crear el scheduler.
4. ✅ `READ` sin entrada produce `WAITING` sin avanzar el IP; un mensaje
   durable despierta el Job y reintenta la misma instrucción.
5. ✅ `HIBERNATE` y restore del tiempo restante con `tokio::time` +
   `^SCHEDULE`; cron M persistente en `^CRON`, también sin polling.
6. ✅ C ABI + wrapper `lumen_mvm.py`; `MVM_ENGINE=rust|python`, Rust opt-in y
   fallback Python si la dylib no está disponible. Las herramientas MCP no
   cambian de API.
7. ✅ Integración real SQLite cubre yield/gas, mapping, transacciones,
   mailbox, timer, restart y cron. Benchmark reproducible en
   `rust/lumen-mvm/benchmark_tokio_vs_python.json`.

**Lectura del benchmark:** con 50 Jobs pequeños, spawn y tick quedan
equivalentes (diferencia <1,1%) aun persistiendo snapshot + legacy. Rust
restaura 100 Jobs ~2,6× más rápido. El mailbox Rust es más costoso porque sí
persiste mensaje y transición WAITING→READY; el Python medido ya había dejado
morir esos lectores. El objetivo sigue siendo aislamiento, reanudación exacta
y timers reactivos, no reemplazar la decisión SQLite de Fase 4.

---

## 4. Lo que NO cambia (el producto)

Los agentes y consumidores siguen viendo exactamente lo mismo:

```
^GLOBAL(subs)=valor         ← read/write
$ORDER(^GLOBAL(subs))       ← iteración ordenada
$DATA(^GLOBAL(subs))        ← existencia
KILL ^GLOBAL(subs)          ← borrado
MERGE ^A(subs)=^B(subs)     ← copia de subárbol
LOCK ^GLOBAL                 ← exclusión mutua
DO ^ROUTINE                  ← ejecución de rutina M
F  S N=$O(^T(N)) Q:N=""     ← tersura M (15 tokens vs 100 tool-calls)
```

**La sintaxis M no es deuda: es la apuesta.** Para un consumidor que paga por
token y por round-trip, un programa de 15 tokens compite contra 10.000 tokens
de tool-calls JSON. M no es para personas — es el conjunto de instrucciones de
los agentes.

---

## 5. Lo que aprende un equipo que se incorpora

1. **El modelo de datos** — árbol jerárquico sin esquema, ordenado por defecto.
   FoundationDB y DynamoDB venden hoy lo mismo como "sorted KV". Nosotros lo
   tenemos integrado con el lenguaje de ejecución.
2. **$ORDER no es magia** — es un range-scan del B-tree con la codificación
   orden-preservante de subkeys. Esa codificación (`encode_subkey`) es la pieza
   más valiosa y portable del proyecto.
3. **La MVM no es un proceso de OS** — es un estado persistido en ^STATE que un
   scheduler cooperativo reanuda. Eso permite ejecución durable y migración de
   jobs entre nodos vía DDP. Temporal/DBOS/Restate venden hoy lo mismo como
   "durable execution" — nosotros lo tenemos desde el diseño original.
4. **DDP no es sync de ficheros** — es replicación del mismo namespace entre
   nodos. El código y los datos viajan por el mismo canal.
5. **LUMEN no es REST** — es un protocolo binario con compresión, macaroons y
   zero-copy SHM. Cada capa (M, globals, DDP, LUMEN) está optimizada para
   minimizar tokens, round-trips y bytes en el cable.

---

## 6. Referencias

- `ajustes.md` (raíz) — revisión v1.1: discrepancias plan vs código
- `alternativas.md` (raíz) — análisis de motores de almacenamiento alternativos
  (redb, heed/LMDB, fjall, rusqlite, sled, RocksDB)
- `alternativa2.md` (raíz) — análisis complementario
- `docs/ROADMAP_MLIGHT.md` — estado del subset M
- `docs/BENCHMARKS.md` — benchmarks de rendimiento
- `docs/COGNITIVE_OS.md` — visión del sistema operativo cognitivo
- `docs/INDEX.md` — mapa de toda la documentación
- `implementations/mcp-servers/pdb/m_light.py` — intérprete M v1
- `implementations/python/pdb-sync/m_stackvm.py` — stack-VM v2
- `implementations/mcp-servers/pdb/pdb_tools.py` — core PDB
- `implementations/mcp-servers/pdb/mvm.py` — la MVM
- `implementations/python/pdb-sync/SYSTEM_SCHEMA.md` — schema ^System
