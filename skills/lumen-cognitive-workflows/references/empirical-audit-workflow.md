# Empirical Audit Workflow — Protocol for Tool Validation

**When**: You need to verify that a toolset actually works as claimed — not trusting docs, not citing benchmarks, not simulating.

## Protocol

1. `session_init(label="audit-<target>")` — isolated clean state
2. For each subsystem, call EVERY tool at least once with minimal valid args
3. Record: `{tool, success, output_shape, error_if_any}`
4. Cross-verify compositions:
   - `pattern_record → pattern_match` (verify recall)
   - `assume → check_assumption → list_assumptions` (verify state persistence)
   - `sequential_thinking → thought_evaluate → thought_similarity` (verify chain integrity)
   - `session_init → session_list` (verify isolation)
5. Verify failure modes: call with missing required params, wrong types, edge values
6. `session_list()` to confirm isolation held
7. `pattern_record` + `decision_log` + `context_preserve` to persist results

## Anti-Patterns Caught by This Protocol

- **Citing docs without test**: "The docs say 29 tools" → but only 7 appear in system prompt
- **Testing subset**: "I tested 5 tools, they work" → but 24 others have schema mismatches
- **Estimating latency**: "It felt like 5 seconds" → actual SHM transport is 0.3ms
- **Assuming fuzzy match**: "pattern_match should find similar things" → it's lexical TF-IDF, not semantic
- **Trusting parameter names from docs**: "The skill says 'id' parameter" → server expects 'assumption_id'
- **Using absolute paths with FS tools**: Works with terminal, fails silently with LUMEN FS

## Verification Checklist

```
[ ] reasoning chain engine (7): sequential_thinking, thought_evaluate, thought_similarity,
    thought_contradiction, thought_summarize, thought_to_plan, thought_bridge
[ ] assumption tracker (3): assume, list_assumptions, check_assumption
[ ] mental model builder (6): model_add, model_query, model_scan, model_map, model_stats, model_remove
[ ] work tracking (4): work_start, work_block, work_done, work_log
[ ] pattern memory (2): pattern_record, pattern_match
[ ] decision log (2): decision_log, decision_list
[ ] context preservation (2): context_preserve, context_check
[ ] context estimation (1): context_estimate
[ ] session management (2): session_init, session_list
[ ] Composition: pattern_record → pattern_match
[ ] Composition: assume → check_assumption → list_assumptions
[ ] Composition: work_start → work_block → work_done → work_log
[ ] Isolation: session_init(A) → write → session_init(B) → read → must be empty
```
