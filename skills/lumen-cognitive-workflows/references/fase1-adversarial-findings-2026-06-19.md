# FASE 1 Adversarial Findings — June 19, 2026

Execution of FASE 1 Unit Stress from the adversarial benchmark plan.

## Overall Verdict: CONDITIONAL PASS ⚠️

Three blockers found, all diagnosed and fixed (pending /reset).

## Subsystem Results

### 1. Reasoning Chain Engine ⚠️

- **Test**: 40-thought chain with 8 branches, 12 revisions, 20 injected contradictions
- **thought_contradiction recall**: 0% (CRITICAL) — even for literal English contradictions
- **Root cause**: `_sentiment_heuristic()` Spanish-only lexicon. Thresholds too strict (sim>0.15, diff>0.3)
- **Fix**: Added English lexicon + relaxed thresholds (sim>0.08, diff>0.15)
- **thought_similarity**: ✅ 18-42% TF-IDF, correctly finds related thoughts
- **thought_bridge**: ✅ Cross-chain connections (26-43%)
- **thought_summarize**: ✅ 40 thoughts → 5 themes
- **thought_to_plan**: ✅ 40-step plan generated

### 2. Pattern Memory ✅

- **Test**: 14 stress patterns across 5 families with controlled similarity
- **Jaccard similarity**: 12-22% for relevant matches
- **Precision@1**: 100% for specific queries
- **Noise rejection**: "xyz123" → no matches ✅
- **Limitation**: Generic queries ("connection pool problem") → no matches (TF-IDF requires term overlap)
- **Verdict**: Lexical, not semantic — correct behavior for algorithm

### 3. Assumption Tracker ⚠️

- **Test**: 38 assumptions across 6 categories
- **Capacity**: 46+ assumptions without degradation ✅
- **check_assumption state bug**: CRITICAL — accepted calls but never persisted state (0 confirmed/refuted in list_assumptions)
- **Root cause**: Plugin schema mismatch — `id`/`status` in schema, `assumption_id`/`outcome` in server
- **Fix**: Corrected schema in `lumen-shm-bridge/__init__.py`
- **Overconfidence detection**: Not tested (requires >80% confirmed rate)

### 4. Mental Model Builder ⚠️

- **Test**: 24 entities with complex properties
- **Graph traversal**: 0 dependencies in model_stats ❌
- **model_query**: Returned empty for all entities ❌
- **Root cause**: Plugin schema defined `entity` parameter but server needs `query` string
- **Fix**: Corrected schema for `model_add` (added deps/role/notes) and `model_query` (entity→query)
- **Design note**: Model is a file dependency graph, not semantic knowledge graph. Use `deps` for edges.

### 5. Session Management ✅

- **Test**: 6 parallel sessions (bench-session-1 to 5 + audit)
- **session_list**: Shows correct isolation — each session with 0 chains, 0 asmp, 0 model
- **Zero bleed**: Confirmed for basic test ✅
- **50-session hydra**: NOT tested (requires larger scale test)

### 6. Context Preservation ✅

- **Test**: 7 items preserved with HIGH priority
- **context_check**: Shows LOW decay risk, all items intact ✅
- **TTL accuracy**: Not tested (requires time-based decay verification)
- **Cross-session persistence**: Not tested (requires new session)

### 7. Work Tracking ✅

- **Test**: 7 historical items from past sessions
- **work_log**: Correctly shows status (✅ 2 done, 🚫 2 blocked, 🔧 3 in progress)
- **State machine**: Basic OK, but nesting and mismatch detection not tested

## Fixes Applied (require /reset)

1. **thought_contradiction**: English lexicon + relaxed thresholds in `server.py` (lines 306-314, 851-852)
2. **check_assumption**: Schema corrected in `__init__.py` (line 719): `id`→`assumption_id`, `status`→`outcome`
3. **model_add / model_query**: Schema corrected in `__init__.py` (lines 728, 735): added `deps`/`role`/`notes`, `entity`→`query`

## Patterns Recorded

- `reasoning-chain-stress-finding` — contradiction detection 0%
- `pattern-memory-stress-finding` — Jaccard 12-21%, precision@1 100%
- `assumption-tracker-stress-finding` — ID mapping bug, 46 assumptions
- `mental-model-stress-finding` — entities isolated, 0 dependencies
- `blocker-contradiction-tfidf-limitation` — root cause diagnostic
- `blocker-check-assumption-state-not-persisted` — root cause diagnostic
- `blocker-model-no-graph-traversal` — root cause diagnostic
- `lumen-fs-absolute-path-silent-fail` — FS tools silent fail with absolute paths

## Next Steps

- `/reset` Hermes to reload plugin with fixed schemas
- Test contradiction detection with English thoughts
- Verify check_assumption state persistence
- Verify model_query with `query="all"`
- Run 50-session hydra test
- Run TTL decay verification
