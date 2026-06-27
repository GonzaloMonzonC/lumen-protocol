---
name: pdb-kv
description: "PDB core KV — 15 herramientas SET/GET/KILL/ORDER/DATA/MERGE/INCR + batch_set + scratchpad + schema + backup. Equivalente MUMPS directo sobre SQLite."
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, pdb, database, kv, core]
---

# PDB Core KV

**15 herramientas** para el dia a dia con PDB. Si necesitas $LOCK, triggers, indices o partitioning, carga `pdb-enterprise`. Si necesitas M-Light, carga `mlight-patterns`.

## Herramientas KV

| Tool | MUMPS | Descripcion |
|------|-------|-------------|
| `pdb_set` | `SET ^ns(subs)=value` | Guardar cualquier valor |
| `pdb_get` | `$GET(^ns(subs))` | Leer valor |
| `pdb_kill` | `KILL ^ns(subs)` | Borrar subarbol |
| `pdb_order` | `$ORDER(^ns(subs),dir)` | Siguiente/anterior subindice |
| `pdb_data` | `$DATA(^ns(subs))` | Existe el nodo? |
| `pdb_merge` | `MERGE ^target=^source` | Copiar subarbol |
| `pdb_incr` | `$INCREMENT(^ns(subs))` | Contador atomico |
| `pdb_batch_set` | - | Insercion masiva atomica |
| `pdb_scratch_set/get/del` | - | Memoria volatil del LLM |
| `pdb_schema` | - | Estructura de la BD |
| `pdb_backup` | - | Backup de la BD |

## Patrones

### Walk con $ORDER
```
F  S I=$O(^ns(I)) Q:I=""  S V=$G(^ns(I,"field")) W V,!
```

### Batch set
```python
pdb_batch_set(items=[{"ns":"X","subs":[1],"value":"a"}])
```

## Pitfalls

- $ORDER retorna "" al final: usa `Q:I=""` para salir
- $DATA: 0=no existe, 1=tiene valor, 10=tiene hijos, 11=ambos
- Siempre inicializa variables: `S I=""` antes de $O
