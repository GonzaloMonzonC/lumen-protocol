---
name: pdb-kv
description: "PDB core KV — 13 herramientas SET/GET/KILL/ORDER/DATA/MERGE/INCR + batch_set + scratchpad + schema + backup. Equivalente MUMPS directo sobre SQLite."
version: 1.0.1
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, pdb, database, kv, core]
---

# PDB Core KV

**13 herramientas** para el dia a dia con PDB. Para $LOCK, triggers, indices o partitioning, carga `pdb-enterprise`. Para M-Light, carga `mlight-cognitive-toolkit`.

## Herramientas KV

| Tool | MUMPS | Descripcion |
|------|-------|-------------|
| `pdb_set` | `SET ^ns(subs)=value` | Guardar cualquier valor |
| `pdb_get` | `$GET(^ns(subs))` | Leer valor |
| `pdb_kill` | `KILL ^ns(subs)` | Borrar subarbol |
| `pdb_order` | `$ORDER(^ns(subs),dir)` | Siguiente/anterior subindice |
| `pdb_data` | `$DATA(^ns(subs))` | Existe el nodo? (0/1/10/11) |
| `pdb_merge` | `MERGE ^target=^source` | Copiar subarbol |
| `pdb_incr` | `$INCREMENT(^ns(subs))` | Contador atomico |
| `pdb_batch_set` | — | Insercion masiva atomica |
| `pdb_scratch_set` | — | Memoria volatil LLM (escribir) |
| `pdb_scratch_get` | — | Memoria volatil LLM (leer) |
| `pdb_scratch_del` | — | Memoria volatil LLM (borrar) |
| `pdb_schema` | — | Estructura de la BD |
| `pdb_backup` | — | Backup de la BD |

## Patrones

### Walk con $ORDER (forward y backward)
```
F  S I=$O(^ns(I)) Q:I=""  S V=$G(^ns(I,"field"))   ; forward
F  S I=$O(^ns(I),-1) Q:I=""                         ; backward
```

### Batch set (mas rapido)
```python
pdb_batch_set(items=[{"ns":"X","subs":[1],"value":"a"}])
```

## Pitfalls

- $ORDER retorna "" al final: usa `Q:I=""` para salir
- $DATA: 0=no existe, 1=tiene valor, 10=tiene hijos, 11=ambos
- Siempre inicializa variables: `S I=""` antes de $O
