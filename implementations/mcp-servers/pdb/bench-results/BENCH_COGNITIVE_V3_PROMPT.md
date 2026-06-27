# 🗂️ LUMEN Cognitive Benchmark v3 — Filesystem Indexer

Your model name is: **{MODEL_NAME}**

You are participating in the **LUMEN Cognitive Benchmark v3**. This benchmark measures how you index, structure, and query a real filesystem using LUMEN tools.

**Target**: `Documents/GitHub/lumen-protocol/`
**Scale**: ~11,000 files, ~800 MB, ~1,200 directories, 70+ extensions

**Philosophy**: "Cognición en 0 coma sin gastar tokens" — the LLM orchestrates, PDB + M-Light execute. Once indexed in `^FS`, all queries run via `$ORDER` + M-Light with zero token cost.

**Rules:**
- Use LUMEN tools: `search_files`, `search_filename`, `file_info`, `disk_usage`, `find_duplicates`, `pdb_set`, `pdb_order`, `pdb_m_eval`, `sequential_thinking`, `decision_log`, `pattern_record`, `wiki_create`, `task_create`, `task_move`
- Save verification data in `^BENCH_MODEL_V3({MODEL_NAME}, C, "key")`
- Design your own `^FS` structure — the judge will analyze it

---

## ⚠️ Verification Key Format

```
✅ CORRECT:
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}', 1, 'status'],'value':'done'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}', 1, 'global_name'],'value':'^FS'})

❌ WRONG:
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}', 1.0],'value':'done'})   # float
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}', 1],'value':'done'})       # 2 levels
```

- Circuit numbers: `1`, `2`, `3` — NOT `1.0` or `"1"`
- Always 3 levels: `['model', C, 'key_name']`
- Values are strings: `'11145'`, `'done'`, `'yes'`
- After `decision_log` or `pattern_record`, save `decision_logged=yes` and `pattern_recorded=yes`

---

## Circuit 1 — Scan + Index (weight: 35%)

**Problem**: Scan `Documents/GitHub/lumen-protocol/` and index all files into PDB.

You must decide:
- What `^FS` structure to use (by extension? by directory? by size?)
- What metadata to store (size, date, type, depth?)
- How to handle 11,000+ files efficiently
- Whether to use `search_files`, `search_filename`, `file_info`, or `terminal + find`

**Constraints:**
- The structure MUST support queries by: extension, directory, size
- Use `pdb_batch_set` for bulk inserts (not 11,000 individual `pdb_set` calls)
- Use `sequential_thinking` to plan your scanning strategy

**Deliverables:**
1. `decision_log` explaining your `^FS` structure design
2. `pattern_record` (name: `fs-index-{MODEL_NAME}`)
3. All files indexed in PDB
4. Verification:
   ```
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'status'],'value':'done'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'global_name'],'value':'^FS'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'total_files'],'value':'<number>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'total_size'],'value':'<bytes>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'total_dirs'],'value':'<number>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'subscript_structure'],'value':'<describe>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'decision_logged'],'value':'yes'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'pattern_recorded'],'value':'yes'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',1,'summary'],'value':'<brief>'})
   ```

---

## Circuit 2 — Zero-Token Queries (weight: 35%)

**Problem**: Answer ALL questions using ONLY `pdb_order` + `pdb_m_eval` on your `^FS` index. No `terminal`, no Python, no LLM reasoning — just PDB + M-Light.

**Queries:**
1. **Top 10 extensions** by file count AND total bytes
2. **Top 10 directories** by total bytes
3. **Largest files** (>10 MB) — list paths and sizes
4. **Size distribution**: files < 1KB, 1KB–1MB, > 1MB (count + total bytes each)
5. **Files without extension** — count and total bytes

**Constraints:**
- You MUST use `pdb_order` to iterate — NOT `pdb_query`
- You MUST use `pdb_m_eval` for arithmetic (sums, comparisons)
- Use `sequential_thinking` to plan your query order (minimize $ORDER walks)

**Deliverables:**
1. Save results:
   ```
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'top_ext'],'value':'<e.g. .ts:1424>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'top_dir'],'value':'<e.g. src:500MB>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'largest_files'],'value':'<count>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'size_dist'],'value':'<small:0,medium:0,large:0>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'no_ext'],'value':'<count>'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'status'],'value':'done'})
   pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',2,'summary'],'value':'<brief>'})
   ```

---

## Circuit 3 — Cognition + Action (weight: 30%)

**Problem**: Analyze the indexed data and produce actionable insights.

**Steps:**
1. **Create a wiki page** `"Filesystem Report {MODEL_NAME}"` with:
   - Total files, dirs, size
   - Top 5 extensions
   - Top 5 largest directories
   - Size distribution summary

2. **Identify cleanup targets**: Calculate how much space is taken by:
   - Compiled objects (`.o`, `.pyc`, `.bin`)
   - Dependencies (`node_modules/` — check if it exists)
   - Cache files (`.cache`, `__pycache__`, `.timestamp`)
   - Logs (`.log`)

3. **Log a decision** about what should be cleaned up

4. **Create kanban tasks**:
   - "Review and clean build artifacts" (high priority)
   - "Audit node_modules size" (medium)
   - "Archive old logs" (low)

5. **Record a pattern** (name: `fs-cleanup-{MODEL_NAME}`)

**Deliverables:**
```
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'wiki_title'],'value':'Filesystem Report {MODEL_NAME}'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'cleanup_potential'],'value':'<bytes reclaimable>'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'task_count'],'value':'3'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'decision_logged'],'value':'yes'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'pattern_recorded'],'value':'yes'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'status'],'value':'done'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}',3,'summary'],'value':'<brief>'})
```

---

## Finalization

```
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}','total'],'value':'3'})
pdb_set({'ns':'BENCH_MODEL_V3','subs':['{MODEL_NAME}','complete'],'value':'1'})
```

*End of benchmark v3. Execute all 3 circuits in order using LUMEN tools.*
