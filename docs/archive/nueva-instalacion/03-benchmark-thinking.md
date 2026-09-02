# 03 — Benchmark `lumen-thinking` (81 tools)

Fecha: 2026-08-18 · Server: `implementations/mcp-servers/thinking/server.py`
· Sesión de prueba: `session_bench` + `default` (para tools sin `session_id`).

## Resultado global

| Resultado | Tools |
|---|---|
| ✅ OK | 79 / 81 |
| ⚠️ BUGS de servidor encontrados y ARREGLADOS | 8 (pdb_watch, pdb_unwatch, pdb_list_watches, pdb_check_notifications, pdb_notifications_pending, pdb_clear_notifications, search_files_fuzzy, search_files_content_fuzzy) |
| ⚠️ BUG de diseño (documentado) | `check_assumption` + tools de análisis de cadenas + wiki: no aceptan `session_id` → solo ven la sesión `default` |

## Bugs encontrados y arreglados

### 1. Handlers con firma posicional (8 tools rotas)

`pdb_watch.py`, `file_tools.py` y `fuzzy_search.py` definían handlers con
firmas Python normales (`tool_pdb_watch(ns, pattern)`, `tool_file_snapshot(
path)`, `tool_search_files_fuzzy(query, path)`) pero el dispatcher del server
siempre llama `handler(args_dict)` → `TypeError` o parámetros dict.

- `pdb_watch` → `Error binding parameter 1: type 'dict' is not supported`
- `pdb_list_watches` / `pdb_check_notifications` → `takes 0 positional
  arguments but 1 was given`
- `file_snapshot` / `file_diff` / `file_snapshots_list` → `argument should be
  a str or os.PathLike, not 'dict'`
- `search_files_fuzzy` / `search_files_content_fuzzy` → `'dict' object has
  no attribute 'strip'`

**Fix**: wrapper `_adapt_pos(fn)` en los 3 módulos — adapta el dict de args
del MCP a los kwargs posicionales de la firma. Verificado vía MCP real:
`pdb_watch` registra watch ✅, `pdb_list_watches` lista ✅,
`pdb_notifications_pending` ✅, `pdb_clear_notifications` ✅,
`pdb_unwatch` ✅.

### 2. Aislamiento de sesión incompleto (documentado, sin fix)

Tools que NO aceptan `session_id` y solo ven la sesión `default`:
`thought_summarize`, `thought_compress`, `thought_similarity`,
`thought_contradiction`, `thought_evaluate`, `thought_to_plan`,
`thought_bridge`, `chain_diff`, `check_assumption`, `wiki_*` (create dice
"Created" pero read/list/delete no la encuentran). Las cadenas creadas en
otras sesiones dan `Chain not found`.

## Detalle por grupo

| Grupo | Tools | Resultado |
|---|---|---|
| Sesión/estado (session_init/list, state_snapshot/feeling, cognitive_pulse, context_check/estimate/preserve, tool_cache, batch_call, checklist) | 13 | ✅ (checklist requería `action` + `task_type`) |
| Work (start, log, block, done) | 4 | ✅ (requieren `work_id`/`item`) |
| Niche/Task/Kanban (create, list, update, create/list/move/search/link/link_url/delete, stats) | 10 | ✅ (niche_update requiere `niche_id`) |
| Objectives (create, plan, status, judge, task_done, archive, delete) | 7 | ✅ flujo builder→judge correcto |
| Model mental (add, scan, query, stats, map, remove) | 6 | ✅ (query: formatos `deps of`, `role=`, `impact of`) |
| PDB ns (set, get, order, kill) | 4 | ✅ escriben en la BD canónica |
| Watches | 6 | ✅ tras fix de firma |
| Wiki | 5 | ⚠️ create OK pero read/list/delete no la ven (bug sesión) |
| Thoughts (sequential_thinking, summarize, compress, similarity, contradiction, evaluate, to_plan, bridge, chain_diff) | 9 | ✅ en sesión default; camelCase en schemas (`chainId`, `thoughtNumber`) |
| Patterns (record, suggest, match, purge) | 4 | ✅ TF-IDF 19-22% match |
| Decisions (log, list) | 2 | ✅ |
| Assumptions (assume, list, check) | 3 | ✅ (check_assumption sin `session_id` → no encuentra las de `session_bench`) |
| File snapshots (snapshot, diff, list) | 3 | ✅ tras fix |
| Fuzzy search | 2 | ✅ tras fix |
| Misc (agent_inbox, agent_message, collision_check) | 3 | ✅ |

## Notas de uso

- Schemas en camelCase: `chainId`, `thoughtNumber`, `targetThoughts`,
  `nextThoughtNeeded`, `totalThoughts`.
- `sequential_thinking` requiere `nextThoughtNeeded` + `totalThoughts`.
- El server expone **88 handlers** (el catálogo de Hermes muestra 81 — 7
  internos no expuestos).
- `checklist` requiere `action` + `task_type` (bug_fix|feature|research|audit).
- Auto-scoring de pensamientos incluido (0-10).
