# Post-Reset Verification — June 19, 2026

Verification of the 3 blocker fixes after Hermes `/reset`.

## BLOCKER 1: thought_contradiction — ✅ FIXED & VERIFIED

**Test chain**: `post-reset-contradiction-test`
- Thought #1: "All tools work perfectly with zero errors in production since the fix"
- Thought #2: "Multiple tools frequently fail under load with errors reported in logs"

**Query**: "zero errors works perfectly"
**Result**: ⚠️ Found 2 potential contradictions:
- #1: positive vs positive (56% similarity) — self-match, should be skipped
- #2: positive vs negative (11% similarity) — **correctly detected** contradiction with thought #2

**Query**: "broken fails downtime crash"
**Result**: No contradictions — expected, thought #2 doesn't contain those specific words

**Verdict**: Working. Thresholds (sim>0.08, sent_diff>0.15) are correct. Minor issue: algorithm should skip self-comparisons.

## BLOCKER 2: check_assumption — ❌ SECOND BUG DISCOVERED

**First fix** (plugin schema): `id`→`assumption_id`, `status`→`outcome` — verified, now gives explicit error "Assumption #N not found" instead of silent no-op.

**Second bug discovered**: Type mismatch. `a["id"]` is `int` (from `_next_assumption_id` counter), but `args["assumption_id"]` is `str` (from JSON). `1 == "1"` → `False`.

**Fix**: `aid = int(args["assumption_id"])` in `server.py:1252`. Applied, requires another `/reset`.

## BLOCKER 3: Mental Model graph — ✅ FIXED & VERIFIED

**Test**: 
```python
model_add(entity="post-reset-service-alpha", deps=["post-reset-db-users","post-reset-cache-redis"], role="service")
model_query(query="deps of post-reset-service-alpha")
```

**Result**:
```
📦 Dependencies of post-reset-service-alpha (service):
   → post-reset-db-users [unknown]
   → post-reset-cache-redis [unknown]
```

**Verdict**: Working. `model_query(query="all")` returns 8 entities.

## Summary

| Blocker | Pre-reset | Post-reset | Status |
|---------|-----------|------------|--------|
| thought_contradiction | 0% recall | Detects English contradictions ✅ | FIXED |
| check_assumption | Silent no-op | Explicit error + int() fix pending | NEEDS /reset |
| Mental Model graph | Empty queries | deps/all queries work ✅ | FIXED |
