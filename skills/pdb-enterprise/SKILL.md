---
name: pdb-enterprise
description: "PDB Enterprise — 19 herramientas: $LOCK, triggers, auto-indices, global mapping, partitioning, FTS search, pdb_query SQL, DBFIX. Cargan pdb-kv primero."
version: 1.0.1
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, pdb, database, enterprise, advanced]
---

# PDB Enterprise — Features Avanzadas

**19 herramientas** para escalado empresarial. Para operaciones basicas KV, carga `pdb-kv`.

## $LOCK — Bloqueo Distribuido (2 tools)

| Tool | Descripcion |
|------|-------------|
| `pdb_lock` | Bloquear recurso (timeout opcional) |
| `pdb_unlock` | Liberar bloqueo |

## Triggers ON SET/ON KILL (4 tools)

| Tool | Descripcion |
|------|-------------|
| `pdb_trigger_define` | Crear trigger (LOG, INDEX, REPLICATE) |
| `pdb_trigger_drop` | Eliminar trigger |
| `pdb_trigger_list` | Listar triggers |
| `pdb_trigger` | Evaluar trigger manualmente |

Los triggers se guardan en `^TRIGGER` dentro de PDB.

## Auto-indices ^IDX (3 tools)

| Tool | Descripcion |
|------|-------------|
| `pdb_index_define` | Crear indice automatico |
| `pdb_index_drop` | Eliminar indice |
| `pdb_index_list` | Listar indices |

Los indices se guardan en `^IDX_CFG` dentro de PDB.

## Global Mapping (4 tools) + Partitioning (3 tools)

| Tool | Descripcion |
|------|-------------|
| `pdb_map_set` | ^GLOBAL redirige a archivo distinto |
| `pdb_map_get` | Consultar mapping |
| `pdb_map_list` | Listar todos los mappings |
| `pdb_map_drop` | Eliminar mapping |
| `pdb_partition_define` | Partir namespace en N archivos por rango |
| `pdb_partition_drop` | Eliminar particion |
| `pdb_partition_list` | Listar particiones |

## FTS + SQL + DBFIX (3 tools)

| Tool | Descripcion |
|------|-------------|
| `pdb_fts_search` | Busqueda full-text (FTS5) |
| `pdb_query` | SQL directo (SELECT/WITH) |
| `pdb_dbfix` | Reparar/verificar BD |

## Pitfalls

- $LOCK: siempre unlock en finally. Bloqueos huerfanos bloquean para siempre
- Triggers: cada uno anade overhead. Solo para casos necesarios
- Partitioning: requiere key numerica para el rango de subindice
- Global mapping: el path se crea automaticamente si no existe
- **Disponibilidad**: triggers, indices, mapping, M-Light y todas las 43 tools SI estan expuestas via MCP tras el fix del bridge (2026-06-27).
