# Ajustes al plan de evolución PDB + M-Light + MVM

> Revisión del plan contrastada con el código real del repo.
> Fecha: 2026-07-14 · Revisor: Claude (verificación sobre working tree)

Veredicto general: **la estrategia (spec first, cerrar el contrato, motor
después) es sólida y el diagnóstico de Fase 1 es correcto, pero el documento
subestima lo que ya está construido y hay un conflicto activo de journal_mode
que conviene resolver ya, no en Fase 1.**

---

## 1. Lo que verifica bien

- `PRAGMA journal_mode=DELETE` confirmado en `pdb_tools.py:131`, 146, 168,
  223 y 289. El diagnóstico de escritura lenta es correcto.
- El push no-op de DDP confirmado: `ddp_sync.py:131-139` tiene el
  `TODO: implement local change tracking` y devuelve lista vacía.

---

## 2. Discrepancias con la realidad del repo

### 2.1 Hay un conflicto de journal_mode activo hoy

`pdb_ttl.py:70` (y líneas 148, 174) ya pone `journal_mode=WAL` sobre
`lumen-pdb.db`, mientras `pdb_tools.py` fuerza `DELETE` en cada conexión.
WAL es una propiedad persistente de la base de datos: cada proceso está
cambiando el modo del otro, y salir de WAL requiere lock exclusivo, así que
esto puede producir errores `database is locked` intermitentes ahora mismo.

No es solo una optimización pendiente — es un bug latente que refuerza hacer
Fase 1 primero (o incluso antes de Fase 0).

### 2.2 Fase 2 está parcialmente construida

El plan dice "falta change-tracking", pero en `pdb-sync/` ya existen:

- `pdb_journal.py` — journal en `^CHANGES` con source tagging y anti-bucle
- `pdb_journal_daemon.py`, `pdb_journal_ddp_bridge.py`, `pdb_journal_recovery.py`
- `pdb_sync_engine.py`
- Tests de mirroring bidireccional: `test_mirroring.py`, `test_bidirectional.py`

Es decir: hay **dos implementaciones DDP paralelas** — `ddp_sync.py` (push
no-op) y la suite de pdb-sync (SyncEngine bidireccional). Fase 2 debería
empezar por consolidarlas, no por construir de cero.

Nota: el journal existente se indexa por timestamp ISO, no por seq monótono
como pide el plan — migrar eso es una tarea concreta que falta nombrar.

### 2.3 Los "23 accesos directos" son 22, y ~8 son bench/tests/debug

`bench/judge_v3.py`, `bench/results/*`, `test_thinking_tools.py`, etc. se
pueden exentar del contrato. El inventario real de producción son ~14
ficheros: 10 en `thinking/`, `ddp_sync.py`, y `pdb_type.py` /
`pdb_help_system.py` / `pdb_ttl.py` / `m_routines.py` en pdb-sync. La tarea
es más pequeña de lo que suena.

### 2.4 Indirection tiene un embrión

`pdb_indirect.py` ya resuelve referencias dinámicas `^NS(subs)` a nivel tool
(con `tests_indirect.py`). Lo que falta es el operador `@` dentro de M-Light,
pero no se parte de cero.

### 2.5 Rutas hardcodeadas rotas

`pdb_ttl.py`, `pdb_journal.py` y `pdb_indirect.py` apuntan a
`~/Documents/GitHub/lumen-protocol/...`, pero el repo vive en
`~/Desktop/projects2/lumen-protocol`. O esos módulos están rotos ahora mismo,
o están operando contra una copia vieja de la base de datos (lo cual sería
peor: dos PDBs divergentes).

El inventario de Fase 1 debería incluir "una sola fuente de `PDB_PATH`"
junto con la prohibición de `sqlite3.connect`.

---

## 3. Ajustes sugeridos al plan

### 3.1 Fase 5 tiene una tensión de secuencia

Propone añadir `@` y TSTART/TCOMMIT directamente en el port a Rust, pero la
premisa del plan es "pasas spec + tests, no porta m_light.py" — y para esas
dos features no habría referencia Python ni tests de conformidad.

Sugerencia: implementarlas en Python (son pequeñas, y `@` ya tiene base)
durante Fase 0-1 para que la suite de conformidad las cubra antes del port,
o marcarlas explícitamente como "spec v2".

### 3.2 Fase 1: "Riesgo: ninguno" es casi cierto pero no del todo

- `synchronous=NORMAL` en WAL puede perder las últimas transacciones ante un
  corte de energía (aceptable aquí, pero conviene decirlo en el doc).
- WAL deja ficheros `-wal`/`-shm` que afectan a scripts de backup que copien
  el `.db` a pelo.
- Revertir requiere checkpoint previo.

### 3.3 Nit

La referencia del plan dice `alternativas2.md` pero el fichero en disco se
llama `alternativa2.md` (sin la primera "s").

---

## 4. Acciones inmediatas derivadas

1. Resolver el conflicto WAL/DELETE entre `pdb_ttl.py` y `pdb_tools.py`
   (accionable hoy, independiente de las fases).
2. Unificar `PDB_PATH` — eliminar rutas hardcodeadas a `~/Documents/GitHub/`.
3. Al planificar Fase 2, partir del journal existente en `pdb-sync/` y
   decidir consolidación `ddp_sync.py` vs `pdb_sync_engine.py`.
