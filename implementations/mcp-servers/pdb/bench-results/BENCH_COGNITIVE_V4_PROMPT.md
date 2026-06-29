# LUMEN Cognitive Benchmark v4 — Agent Construction

**Version:** 4.0.0 · **Canonical:** `bench-results/BENCH_COGNITIVE_V4_PROMPT.md`

You are an AI agent with access to 106 LUMEN tools across 4 MCP servers.
Your task: **build a complete mini-project that demonstrates mastery of the LUMEN cognitive stack.**

This benchmark measures your ability to use LUMEN as a personal assistant —
not just call tools, but build structure, persist knowledge, and produce
a working artifact.

---

## Scoring (100 points)

| Circuit | Weight | What it tests |
|---------|:------:|---------------|
| **1. Planning & Scaffolding** | 30% | Cognitive structure before coding |
| **2. Execution & Tool Diversity** | 40% | Real work across 30+ distinct tools |
| **3. Documentation & Persistence** | 30% | Verify everything survived, document findings |

---

## Circuit 1: Planning & Scaffolding (30 points)

**Goal:** Create the cognitive foundation before writing a single line of code.

### Must do:

1. **Create a niche** for this project: `niche_create(name="Repo Health Scanner", desc="Benchmark v4 project")`
2. **Create 4-6 tasks** in that niche covering the full project lifecycle
3. **Start a wiki page** documenting the project design and architecture decisions
4. **Record at least 2 decisions** via `decision_log` with rationale
5. **Record at least 2 patterns** via `pattern_record` with bug/fix strategies you anticipate
6. **Save verification keys** in PDB so the judge can detect your work:
   ```
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "planning_done"), "yes")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "tasks_created"), "<count>")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "decisions_logged"), "<count>")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "patterns_recorded"), "<count>")
   ```

### Judge checks:
- Niche exists with correct name
- Tasks ≥ 4 with diverse priorities
- Wiki ≥ 500 chars
- Decisions ≥ 2 with non-empty rationale
- Patterns ≥ 2 with non-empty description
- Verification keys in ^BENCH_MODEL_V4

---

## Circuit 2: Execution & Tool Diversity (40 points)

**Goal:** Build a REAL working artifact using the maximum diversity of LUMEN tools.

### The Project: Repo Health Scanner

Build a Python script (`repo_scanner.py`) that:
1. Scans the current repo using LUMEN filesystem tools
2. Finds: largest files, duplicate files, files without extensions, missing markdown docs
3. Saves results to PDB (`^REPO_SCAN`) with structured subscripts
4. Generates a console report using M-Light expressions

### Tool Diversity Requirement

You must use tools from **at least 6 of these 8 categories**:

| Category | Tools to use | Minimum |
|----------|-------------|:-------:|
| **Filesystem** | `list_directory`, `search_files`, `file_info`, `disk_usage`, `find_duplicates`, `read_file` | 3 |
| **PDB Write** | `pdb_set`, `pdb_batch_set`, `pdb_incr` | 2 |
| **PDB Read** | `pdb_get`, `pdb_order`, `pdb_data`, `pdb_query`, `pdb_schema` | 3 |
| **M-Light** | `pdb_m_eval` (expressions, $ORDER loops) | 2 |
| **Terminal** | Run Python scripts, shell commands | 1 |
| **File Write** | `write_file` (create repo_scanner.py and report) | 1 |
| **Web** | `web_search` (research a technique) | 1 |
| **Kanban** | `task_move` (mark tasks as done) | 1 |

### Verification keys:
After EACH tool category, save a counter:
```
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_filesystem"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_pdb_write"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_pdb_read"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_mlight"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_terminal"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_writefile"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_web"), "<count>")
pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "cat_kanban"), "<count>")
```

### Judge checks:
- `^REPO_SCAN` namespace exists with data (≥ 3 subscripts)
- `repo_scanner.py` file created (≥ 50 lines)
- 6+ categories with count ≥ 1
- Total distinct tools used ≥ 20

---

## Circuit 3: Documentation & Persistence (30 points)

**Goal:** Prove everything persisted and document the experience.

### Must do:

1. **Verify PDB persistence:** use `pdb_schema()` and `pdb_data()` to confirm data survived
2. **Update wiki** with findings: what worked, what was hard, tool count, bugs found
3. **Link tasks to cognitive artifacts:** use `task_link` for each task
4. **Mark all tasks as Done:** `task_move(task_id, "Done")`
5. **Save final state:**
   ```
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "persistence_verified"), "yes")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "wiki_updated"), "yes")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "tasks_completed"), "<count>")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "total_tools_used"), "<count>")
   pdb_set(^BENCH_MODEL_V4("{MODEL}", "C", "final_score_self"), "<your estimate 0-100>")
   ```

### Judge checks:
- Wiki updated (content ≥ 200 chars added)
- All tasks in "Done" column
- Persistence verified: `^REPO_SCAN` still has data
- Verification keys present

---

## Format Rules — CRITICAL

### ✅ CORRECT — PDB subscripts

```
pdb_set(^BENCH_MODEL_V4("deepseek-v4-pro", "C", "planning_done"), "yes")
```

Use: `ns="BENCH_MODEL_V4"`, `subs=["deepseek-v4-pro", "C", "planning_done"]`, `value="yes"`

### ❌ WRONG — Common mistakes

```
✗ ^BENCH_MODEL_V4(deepseek-v4-pro, C, ...)     → subkey must be array
✗ pdb_set(ns="BENCH_MODEL_V4", subs="wrong")    → subs must be array, not string
✗ ns="BENCH_MODEL_V4_TYP0"                       → typo, use exact name
✗ Skip verification keys                          → judge won't detect your work
✗ Write code without tasks/wiki first             → Circuit 1 fails
```

### Model name

Use the EXACT model name as provided. No spaces. Examples:
- `deepseek-v4-pro`
- `deepseek-v4-flash-max`
- `claude-sonnet-4-6`

---

## Quick Reference

```
PLAN:     niche_create → task_create × 6 → wiki_create → decision_log × 2 → pattern_record × 2
EXECUTE:  list_directory → search_files → file_info → disk_usage → find_duplicates
          → pdb_set → pdb_batch_set → pdb_order → pdb_m_eval
          → terminal → write_file → web_search → task_move
VERIFY:   pdb_schema → pdb_data → wiki_update → task_link → task_move(Done) → pdb_set(keys)
```

---

## Remember

- **Use pdb_order to iterate** — NOT pdb_query for traversal
- **batch_call does not return results** — chain manually
- **sequential_thinking may freeze on Windows** — use inline reasoning instead
- **Save verification keys after EVERY circuit** — the judge can only see PDB data
- **The model name is `{MODEL}`** — replace with your actual model name in all pdb_set calls
