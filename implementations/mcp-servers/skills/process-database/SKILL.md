---
name: process-database
description: "👽 PDB — SQLite-backed hierarchical KV with MUMPS heritage. 40 tools: $ORDER/$DATA/$GET, global mapping, partitioning, triggers, indices, $LOCK, M-Light evaluator, M REPL, MVM. Umbrella skill: carga pdb-kv + pdb-enterprise + mlight-cognitive-toolkit."
version: 2.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, database, kv, mumps, sqlite, composition]
---

# Process Database (PDB) — Umbrella

**40 herramientas en 4 servidores.** Este skill es un paraguas que anida los skills atomicos. Para uso diario, carga solo el que necesites. Para todo, carga este.

## Skills anidados

| Skill | Contenido | Herramientas | Cuando cargarlo |
|:------|:----------|:------------|:----------------|
| `pdb-kv` | SET/GET/KILL/ORDER/DATA/MERGE + scratch + schema | 15 | Operaciones diarias |
| `pdb-enterprise` | $LOCK, triggers, indices, mapping, partitioning, FTS, SQL | 13 | Features avanzadas |
| `mlight-cognitive-toolkit` | M-Light patrones, M + Thinking, triggers cognitivos | 5 (eval/REPL/MVM) | Procesar datos con M |

## Core Insight

SQLite IS a B-tree. Una tabla `_globals(ns, subkey, value)` con PK `(ns, subkey)` es un KV ordenado. PDB anade semantica MUMPS ($ORDER, $DATA, $LOCK) sobre esa base.

## Quick Start

```python
# Carga todo
skill_view('process-database')

# O carga solo lo que necesites
skill_view('pdb-kv')              # Solo KV
skill_view('pdb-enterprise')      # Solo enterprise
skill_view('mlight-cognitive-toolkit')  # Solo M-Light
```

## Arquitectura

```
^GLOBAL(sub1, sub2, ...) = value
   |
   v
SQLite _globals(ns, subkey BLOB, value BLOB)
   |
   v
$ORDER / $DATA / $GET / $LOCK / triggers / indices
```

## Pitfalls

- journal_mode DELETE: no crea .shm/.wal. Escribe directo al .db
- No mezclar ns con subindices: `pdb_get("ns", [1])`
- $ORDER retorna "" al final del arbol
- Siempre inicializa variables M: `S I=""` antes de $O
