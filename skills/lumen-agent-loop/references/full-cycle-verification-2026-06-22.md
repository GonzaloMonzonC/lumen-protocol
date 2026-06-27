# Full Agent Loop Cycle Verification — June 22, 2026

## Test: Documentation Audit (Real-World Case)

**Objective**: Auditar y corregir todos los .md de lumen-protocol

### Cycle

```
BUILDER  → objective_create → Score 8/10 → READY
BUILDING → objective_judge("goal_3") → READY, moves to BUILDING
BUILDING → objective_plan("goal_3") → 7 heuristic tasks
BUILDING → [Execute 7 tasks: grep, read, patch 6 .md files]
BUILDING → objective_judge("goal_3", mark_done=true)
          → Score 10/10 (7/7 tasks, 6/6 criteria)
          → Verdict: PASS → moves to TESTING
TESTING  → objective_judge("goal_3", mark_done=true)
          → auto-test added (mark_done checks phase=="testing")
          → Score 10/10 (1/1 tests passed)
          → Verdict: DONE ✅
```

### Key Observations

1. **BUILDER → BUILDING transition**: `objective_create` returns "READY" but does NOT auto-transition phase. Must call `objective_judge()` explicitly to move to BUILDING. This is because `tool_objective_create()` calls `_judge_objective()` but only `tool_objective_judge()` updates `obj["phase"]`.

2. **`objective_plan()` only works in BUILDING or TESTING**: Returns error if called in BUILDER phase. Judge must approve first.

3. **Heuristic tasks from criteria**: `objective_plan()` generates N+1 tasks (N from criteria + 1 verification task). These are heuristic — the LLM should enrich with `sequential_thinking`.

4. **`mark_done=true` bulk mode**: When the LLM has completed all work, `objective_judge(mark_done=true)` marks all tasks done, verifies all criteria (sets `verified=True`), and in TESTING phase auto-adds a passed test result. This avoids needing separate `objective_task_done` calls for each task.

5. **`objective_task_done` granular mode**: For fine-grained progress tracking, call `objective_task_done(goal_id, task_id)` per task. The task IDs follow pattern `{goal_id}_t{N}` (e.g. `goal_3_t1`).

## Score Calculation

### BUILDING Phase
```python
done = 7, total = 7                    # all tasks done
completion = 7/7 = 1.0                  # 100%
score = 1.0 * 7 = 7.0                   # completion component
verified = 6, total_criteria = 6        # all verified
score += (6/6) * 3 = 3.0               # criteria component
score = 10.0                            # PASS threshold ≥ 8
```

### TESTING Phase
```python
passed = 1, total_tests = 1
score = (1/1) * 10 = 10.0               # DONE threshold ≥ 10
```

## Commits This Session

| Commit | Description |
|--------|-------------|
| `3af9201` | feat: Agent Loop — objective_task_done tool + full cycle verified |
| `02bb18d` | docs: audit .md files — fix tool counts, add PDB as 4th server |
| `4d54391` | feat: Agent Loop panel in dashboard + objectives in /metrics |
| `b2a340e` | fix: PDB-first persistence — PDB primary, JSON periodic backup |
