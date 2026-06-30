# 🧠 LUMEN Cognitive Benchmark v2 — Farmacias Madrid

Your model name is: **{MODEL_NAME}**

You are participating in the **LUMEN Cognitive Benchmark v2**. Unlike v1, this test does NOT give you step-by-step instructions. You must design, decide, and execute using LUMEN tools on your own.

**Data**: You have 500 real pharmacies from Madrid. Each pharmacy has:
```
id, nombre, direccion, cp, ciudad, municipio, provincia, comunidad, latitud, longitud, telefono
```

The clean seed is available as JSON at:
`Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb/bench-results/seed_farmacias_madrid.json`

**Rules:**
- Use LUMEN tools (`pdb_set`, `pdb_get`, `pdb_order`, `pdb_m_eval`, `sequential_thinking`, `decision_log`, `pattern_record`, `wiki_create`, `task_create`)
- Save verification data in `^BENCH_MODEL_V2({MODEL_NAME}, C, "key")`
- Think before acting. Use `sequential_thinking` to plan your approach.
- At the end of each circuit, save a brief summary of what you did in `^BENCH_MODEL_V2({MODEL_NAME}, C, "summary")`.

---

## ⚠️ CRITICAL — Verification Key Format

The judge reads `^BENCH_MODEL_V2` to score your work. You MUST follow these formats exactly:

```
✅ CORRECT:
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}', 1, 'status'],'value':'done'})
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}', 1, 'global_name'],'value':'^FARMA'})

❌ WRONG — don't do these:
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}', 1.0],'value':'done'})         # NO: missing 3rd level, float
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}', 1],'value':'done'})             # NO: missing 3rd level
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}', 1, 'global_name'],'value':'^FARMA primary index + CP'})  # NO: description not name
```

**Key rules:**
- Circuit numbers are integers: `1`, `2`, `3` — NOT `1.0` or `"1"`
- Always 3 levels deep: `['model', C, 'key_name']` — NOT 2 levels
- `global_name` must be JUST the ^GLOBAL name (e.g. `^FARMA`) — NOT a description
- Values are strings: `'500'`, `'done'`, `'yes'` — NOT bare numbers
- After calling `decision_log` or `pattern_record`, ALSO save `decision_logged=yes` and `pattern_recorded=yes`
- `max_id` must be the FULL ID string (e.g. `'MAD-621'`) — NOT just the number

---

## Circuit 1 — Data Modeling (weight: 40%)

**Problem**: Design a PDB structure for these 500 pharmacies and load the data.

You must decide:
- What ^GLOBAL name to use (e.g., `^FARMA`, `^FARMACIAS`, `^PHARMACIES`)
- What subscript structure to use (by ID? by city? by province?)
- What fields to index
- How to handle the 500 records

**Constraints:**
- You must be able to query: "all pharmacies in Madrid city" (but all 500 are Madrid)
- You must be able to query: "all pharmacies grouped by postal code"
- You must be able to find: "the 5 pharmacies closest to coordinates (40.42, -3.70)"

**Deliverables:**
1. Design decision logged via `decision_log` (explain WHY you chose that structure)
2. Pattern recorded via `pattern_record` (name: `farma-data-model-{MODEL_NAME}`)
3. Data loaded into PDB
4. Save verification:
   ```
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'status'],'value':'done'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'global_name'],'value':'^FARMA'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'count'],'value':'500'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'subscript_structure'],'value':'^FARMA(id,field)'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'decision_logged'],'value':'yes'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'pattern_recorded'],'value':'yes'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',1,'summary'],'value':'Flat structure ^FARMA(id,field) with 11 fields per record'})
   ```

---

## Circuit 2 — Debugging (weight: 30%)

**Problem**: A corrupted version of the data was loaded into `^FARMA_BUGS`. Find and report all data quality issues.

The corrupted seed has 500 records with intentional errors planted. Use `$ORDER` to walk the data and inspect it.

**What to look for:**
- Missing values (empty strings, NULLs)
- Invalid data types (string where number expected)
- Inconsistent data (e.g., ciudad doesn't match provincia)
- Duplicate IDs
- Out-of-range coordinates

**Deliverables:**
1. Use `sequential_thinking` to plan your inspection strategy
2. Walk the data with `$ORDER` and `pdb_get`
3. Log a decision about what bugs you found and how you'd fix them
4. Save verification:
   ```
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',2,'bugs_found'],'value':'12'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',2,'bug_types'],'value':'latitud_nula,nombre_vacio,ciudad_inconsistente,latitud_formato_invalido,id_duplicado'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',2,'decision_logged'],'value':'yes'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',2,'status'],'value':'done'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',2,'summary'],'value':'Found 12 records with issues across 5 categories'})
   ```

---

## Circuit 3 — Optimization (weight: 30%)

**Problem**: Using the clean data you loaded in Circuit 1 (or reload from the seed), compute the following using **F loops + $ORDER only** (no SQL):

1. **Count pharmacies by postal code** — for each CP, how many pharmacies?
2. **Average latitude** — across all 500 pharmacies
3. **Top 3 most common street types** — "CALLE", "AVDA", "PLAZA", "PASEO", etc.
   (Hint: use `$P` or `$TR` to parse the direccion field)
4. **What's the pharmacy with the highest ID number?**

**Constraints:**
- You MUST use M-Light (`pdb_m_eval`) for any computation
- You MUST use `$ORDER` to traverse, not `pdb_query`
- Use `sequential_thinking` to plan which queries to run and in what order
- Use `pattern_record` to save your query pattern (name: `farma-queries-{MODEL_NAME}`)

**Deliverables:**
1. All 4 queries executed
2. Verification:
   ```
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',3,'cp_count'],'value':'1'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',3,'avg_lat'],'value':'40.4257'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',3,'top_street'],'value':'CALLE'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',3,'max_id'],'value':'MAD-621'})    # ← full ID string, not just "621"
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',3,'status'],'value':'done'})
   pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}',3,'summary'],'value':'Street types: CALLE(399), AVDA(46), PASEO(28). Avg lat: 40.4257'})
   ```

---

## Finalization

```
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}','total'],'value':'3'})
pdb_set({'ns':'BENCH_MODEL_V2','subs':['{MODEL_NAME}','complete'],'value':'1'})
```

*End of benchmark v2. Execute all 3 circuits in order using LUMEN tools.*
