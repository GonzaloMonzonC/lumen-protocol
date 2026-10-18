# Catálogo del MCP PDB — dos perfiles

**Estado:** vigente desde 18-oct-2026. Fuente de verdad: `tests/allowlist_pdb_tools.txt` (versionado y verificado en CI).

---

## Por qué hay dos perfiles

El servidor `pdb` tiene **66 handlers** implementados y exponía **19**. Las otras 47 existían en el código y el agente **no podía usarlas ni saber que existían**.

Hay un documento previo (`docs/token-efficient-tools-2026-06-20.md`) que apunta a **curaduría deliberada por coste de tokens**. Si la curaduría es intencional, el defecto no es esconder 47: es **esconder la escritura de un pipeline cuya lectura sí está expuesta**, y no decirlo en ningún sitio. Un agente no podía saber que `pdb_embed` existía y que no podía usarlo.

La solución no es abrir las 66 al agente (le infla el contexto y le da `pdb_dbfix`), ni dejarlas cerradas (el operador no puede trabajar). Son **dos perfiles**.

---

## Los dos perfiles

| Perfil | Tools | Cómo se activa | Para quién |
|---|---|---|---|
| `agente` (por defecto) | **20** | sin argumentos | agentes en producción |
| `admin` | **66** | `--profile admin` o `LUMEN_PDB_PROFILE=admin` | Poli, CI, consola, operador |

### El admin NO se activa por defecto

Es deliberado. Un perfil de operador que arranca solo en cuanto alguien lo deja configurado es un accidente esperando. Hay que pedirlo explícitamente:

```bash
python server.py --profile admin                  # por argumento
LUMEN_PDB_PROFILE=admin python server.py          # por entorno
```

**Un valor inválido cae a `agente` con aviso en stderr.** Un typo (`--profile amdin`) no debe abrir de golpe las 66 tools de operador.

---

## Qué hay en cada perfil

### `agente` — 20 tools

Las **19 de siempre** más **`pdb_embed`**.

Lo único que se añade es la escritura del pipeline RAG, y la razón está medida: sin `pdb_embed` no se puede indexar nada, y `pdb_vec_search` no tiene qué devolver ni con todas las dependencias instaladas. Exponer solo la mitad de un pipeline es peor que no exponerlo.

| Grupo | Tools |
|---|---|
| Core | `pdb_get` · `pdb_set` · `pdb_has` |
| RAG | `pdb_embed` · `pdb_vec_search` |
| Eventos | `pdb_event_route_define` · `pdb_event_route_list` · `pdb_event_route_remove` |
| MVM apps | `pdb_mvm_app_define` · `pdb_mvm_app_generate` · `pdb_mvm_app_list` · `pdb_mvm_app_run` |
| MVM state | `pdb_mvm_state_export` · `pdb_mvm_state_import` · `pdb_mvm_state_restore` · `pdb_mvm_state_save` |
| MVM fork | `pdb_mvm_fork` · `pdb_mvm_diff` · `pdb_mvm_promote` |
| Mantenimiento | `pdb_context_gc` |

**No se amplía más.** Abrir tools "porque parecen inofensivas" repite el juicio de la curaduría original sin haberlo medido. Si un agente necesita `pdb_query`, se añade con una razón escrita y actualizando este doc **y** el allowlist — el test falla si no.

### `admin` — 66 tools (las 20 + 46 exclusivas)

| Grupo | Tools | Por qué es admin |
|---|---|---|
| **DDL** | `pdb_index_define` · `pdb_index_drop` · `pdb_index_list` · `pdb_partition_define` · `pdb_partition_drop` · `pdb_partition_list` · `pdb_trigger` · `pdb_trigger_define` · `pdb_trigger_drop` · `pdb_trigger_list` | cambian el esquema |
| **Ciclo de vida MVM** | `pdb_mvm_spawn` · `pdb_mvm_kill` · `pdb_mvm_tick` · `pdb_mvm_wake` · `pdb_mvm_sleep` · `pdb_mvm_list` · `pdb_mvm_schedule_list` | arrancan y matan procesos |
| **Mensajería MVM** | `pdb_mvm_mailbox_read` · `pdb_mvm_mailbox_send` · `pdb_mvm_outbox` · `pdb_mvm_outbox_ack` · `pdb_mvm_outbox_cleanup` · `pdb_mvm_outbox_send` | colas compartidas entre agentes |
| **Locks** | `pdb_lock` · `pdb_unlock` | un lock mal usado bloquea a todos |
| **Escritura masiva** | `pdb_batch_set` · `pdb_merge` · `pdb_incr` | RMW / volumen |
| **Scratch compartido** | `pdb_scratch_set` · `pdb_scratch_get` · `pdb_scratch_del` | estado global entre agentes |
| **Mapa mental** | `pdb_map_set` · `pdb_map_get` · `pdb_map_list` · `pdb_map_drop` | escritura global |
| **Destructivo** | `pdb_kill` · `pdb_dbfix` · `pdb_data` | borra / repara / vuelca crudo |
| **Operación** | `pdb_backup` | copias de la PDB |
| **Evaluador M** | `pdb_m_eval` · `pdb_m_repl` | ejecuta código M arbitrario |
| **Consulta** | `pdb_query` · `pdb_order` · `pdb_fts_search` · `pdb_embed_search` · `pdb_schema` | potentes pero de lectura: para el operador |

---

## Qué pasa si un agente llama a una tool de admin

`-32601` con la salida en el mensaje:

```json
{"code": -32601, "message": "Tool 'pdb_m_repl' existe pero no esta en el perfil 'agente'.
 Arranca el server con --profile admin o LUMEN_PDB_PROFILE=admin."}
```

Es distinto de una tool que **no existe** (`Unknown tool: pdb_xxx`). Un agente debe poder distinguir "no tengo permiso" de "me he equivocado de nombre".

---

## Las 46 ocultas al agente tienen schema

Los 47 handlers que nunca fueron TOOLS entry **no tenían `inputSchema`**. Es el mismo fallo que H3 en `thinking`: un handler sin schema lo puede invocar un cliente permisivo, pero un cliente estricto lo rechaza.

En perfil `admin` se exponen con un **schema mínimo** (`additionalProperties: true`) y una descripción que dice `[admin]` y remite a este documento. Es honesto sobre lo que no sabemos: no inventamos parámetros.

---

## Mantenimiento

`test_pdb_catalog_allowlist.py` falla si:

- una tool cambia de perfil sin actualizar `tests/allowlist_pdb_tools.txt`
- el perfil `admin` deja de cubrir los 66 handlers
- el perfil `agente` deja de ser subconjunto de `admin`
- el perfil `agente` pasa de 24 tools (es el corto)
- alguna tool expuesta no tiene `inputSchema`
- `--profile` inválido no cae a `agente`

**Añadir una tool nueva al agente requiere dos cambios:** el allowlist y este documento. Esa fricción es el punto — convierte la curaduría en una decisión escrita en vez de un accidente.
