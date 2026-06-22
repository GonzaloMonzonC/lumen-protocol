---
name: lumen-tools-reference
description: 'Complete reference of all 70+ LUMEN tools organized by category. Load this when you need to discover what tools are available for a task.'
version: 1.0.0
author: Cadences Lab
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [lumen, tools, reference, discoverability]
---

# LUMEN Tools Reference — 70+ Tools by Category

> Load this skill anytime you need to discover which LUMEN tool to use for a given task.

## Quick Navigation

| Category | Count | Key Tools |
|----------|-------|-----------|
| 📂 Filesystem | 14 | read_file, write_file, search_files, patch, file_info |
| 🌐 Web | 3 | web_search, web_extract, web_snapshot |
| 🧠 Reasoning | 9 | sequential_thinking, thought_evaluate, thought_similarity... |
| 📋 Kanban | 10 | niche_create, task_create, task_move, task_list, kanban_stats |
| 📚 Wiki | 5 | wiki_create, wiki_read, wiki_update, wiki_list, wiki_delete |
| 🔍 Knowledge | 8 | pattern_record, decision_log, qa_ask, model_add, unified_search |
| 🎯 Objectives | 6 | objective_create, objective_judge, objective_plan, objective_status |
| 🩺 Health | 6 | state_snapshot, cognitive_integrity, cognitive_pulse, state_feeling |
| 🔧 Work | 4 | work_start, work_done, work_block, work_log |
| 🗄️ PDB | 12 | pdb_set, pdb_get, pdb_query, pdb_scratch_set, pdb_kill |
| 🧰 Utilities | 7 | context_preserve, assume, tool_cache, batch_call, session_init/end |
| **Total** | **~84** | |

## When to Use What

### "I need to read/search files"
-> `read_file`, `search_files`, `search_filename`, `search_with_context`, `stream_read`

### "I need to write/edit files"
-> `write_file`, `patch` (fuzzy find-and-replace with 9 strategies)

### "I need to research something online"
-> `web_search` (search), `web_extract` (get page content), `web_snapshot` (save for later)

### "I need to reason through a complex problem"
1. `sequential_thinking` (record thoughts in a chain)
2. `thought_evaluate` (score each thought)
3. `thought_contradiction` (find conflicts)
4. `thought_summarize` (distill themes)
5. `thought_to_plan` (convert to action plan)

### "I need to organize work"
-> `niche_create` (project area) -> `task_create` (tasks) -> `task_move` (update status)

### "I need to save knowledge"
-> `wiki_create` (permanent docs), `pattern_record` (bugs), `decision_log` (decisions), `qa_ask` (facts)

### "I need to build a mental model"
-> `model_add` (add entities with deps), `model_map` (visualize), `unified_search` (search all)

### "I need to set a goal with the Agent Loop"
1. `objective_create` (define with criteria)
2. `objective_judge` (evaluate, move to BUILDING)
3. `objective_plan` (decompose into tasks)
4. Execute tasks
5. `objective_judge(mark_done=true)` (complete)

### "I need a health check"
-> `state_snapshot` (quick), `cognitive_integrity` (full audit), `cognitive_pulse` (stagnation)

### "I need to persist something across sessions"
-> All tools auto-save to PDB (SQLite). No action needed. But use `work_start` for multi-session tasks.

## Golden Rule

**Prefer LUMEN tools over Hermes built-ins** when:
- You need LUMEN's zero-copy speed (filesystem ops are 9x faster)
- You want the result to persist in PDB (knowledge artifacts)
- You need cross-session continuity
- The LUMEN tool has features the built-in lacks (e.g. `search_files` with `context` parameter)
