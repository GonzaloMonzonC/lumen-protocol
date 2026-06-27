---
name: pdb-enterprise
description: "PDB Enterprise — $LOCK, triggers, auto-indices, global mapping, partitioning, FTS search, DBFIX, pdb_query SQL. Features de escalado empresarial."
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, pdb, database, enterprise, advanced]
---

# PDB Enterprise — Features Avanzadas

**13 herramientas** para escalado empresarial. Para operaciones basicas KV, carga `pdb-kv`.

## $LOCK — Bloqueo Distribuido

| Tool | Descripcion |
|------|-------------|
| `pdb_lock(ns, timeout?, owner?)` | Bloquear recurso |
| `pdb_unlock(ns)` | Liberar bloqueo |

```
pdb_lock("CRITICAL", timeout=30)  ; bloquea por 30s
; ... operacion critica ...
pdb_unlock("CRITICAL")
```

## Triggers — ON SET / ON KILL

| Tool | Descripcion |
|------|-------------|
| `pdb_trigger_define(ns, event, action, params)` | Crear trigger |
| `pdb_trigger_drop(ns, trigger_id)` | Eliminar trigger |
| `pdb_trigger_list(ns?)` | Listar triggers |
| `pdb_trigger(args)` | Evaluar/ejecutar trigger |

```
; Audit log automatico
pdb_trigger_define("PATIENT", "ON_SET", "LOG", {"dest_ns":"AUDIT"})
; Indice automatico
pdb_trigger_define("PATIENT", "ON_SET", "INDEX", {"idx_name":"^IDX_NAME","sub_pos":2})
```

## Auto-indices ^IDX

| Tool | Descripcion |
|------|-------------|
| `pdb_index_define(ns, idx_name, sub_pos)` | Crear indice |
| `pdb_index_drop(ns, idx_name)` | Eliminar indice |
| `pdb_index_list(ns?)` | Listar indices |

## Global Mapping + Partitioning

| Tool | Descripcion |
|------|-------------|
| `pdb_map_set(ns, path)` | ^GLOBAL redirige a archivo distinto |
| `pdb_map_get(ns)` | Consultar mapping |
| `pdb_map_list()` | Listar mappings |
| `pdb_map_drop(ns)` | Eliminar mapping |
| `pdb_partition_define(ns, ranges)` | Partir namespace en N archivos |
| `pdb_partition_drop(ns)` | Eliminar particion |
| `pdb_partition_list()` | Listar particiones |

## FTS + SQL + DBFIX

| Tool | Descripcion |
|------|-------------|
| `pdb_fts_search(query, limit?, ns?)` | Busqueda full-text |
| `pdb_query(sql, params?)` | SQL directo |
| `pdb_dbfix()` | Reparar/verificar BD |

## Pitfalls

- $LOCK: siempre hacer unlock en finally
- Triggers: cada trigger anade overhead. Usar solo los necesarios
- Partitioning: requiere key numerica para el rango
- Global mapping: si el path no existe, se crea automaticamente
