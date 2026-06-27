# 7-Fix Summary — June 19, 2026 Session

Complete list of all fixes applied during the adversarial benchmark +
cross-session development session. All fixes verified post-`/reset`.

## Fix 1: `thought_contradiction` recall 0% (server.py)
- **Root cause**: Spanish-only lexicon in `_sentiment_heuristic()`, thresholds too strict
- **Fix**: Added English lexicon (positive: good/great/perfect/works/never, negative: fail/fails/errors/broken/downtime/crash). Lowered sim threshold 0.15→0.08, sent_diff 0.3→0.15
- **Verified**: Query "zero errors works perfectly" detected contradiction "Multiple tools frequently fail under load" (11% sim, positive vs negative)

## Fix 2: `check_assumption` schema mismatch (__init__.py)
- **Root cause**: Plugin schema defined `id`/`status`, server expected `assumption_id`/`outcome`
- **Fix**: Corrected schema parameters in plugin registration
- **Verified**: Tool now returns explicit error "Assumption #N not found" instead of silent no-op

## Fix 3: `check_assumption` type mismatch (server.py)
- **Root cause**: `a["id"]` is int, `args["assumption_id"]` is str → `1 == "1"` → False
- **Fix**: `aid = int(args["assumption_id"])`
- **Verified**: Post-/reset, `check_assumption(assumption_id="1", outcome="confirmed")` → ✅

## Fix 4: `_load_state()` ID collision (server.py)
- **Root cause**: `_next_assumption_id` reset to 1 after /reset, colliding with persisted IDs
- **Fix**: Recompute `_next_assumption_id = max(existing_ids) + 1` in `_load_state()`
- **Pattern**: Any counter-based ID system loaded from disk must compute max, not trust saved counter

## Fix 5: `model_add` accepts `properties` (server.py + __init__.py)
- **Root cause**: No support for arbitrary key-value properties on mental model entities
- **Fix**: Added `properties` dict parameter to `model_add`, stored as `session.model[entity]["properties"]`
- **Verified**: `model_add(entity="X", properties={"criticality":"high","sla":"99.95"})` → stored

## Fix 6: HTTP CRUD `/model` endpoints (server.py)
- **Added**: `GET /model` (all entities), `GET /model?entity=X` (single), `POST /model` (create/update/delete via `_action`), `do_OPTIONS` (CORS)
- **Dashboard**: Wiki editor panel with `loadWiki()`, `showEntity()`, `editEntity()`, `saveEntity()`, `deleteEntity()`, `newEntity()`

## Fix 7: Cross-session tools (server.py + __init__.py + dashboard.html)
- **Added**: `agent_message` tool, `agent_inbox` tool, `GET /inbox?session=X`, inbox dashboard panel
- **Fix**: Message routing resolves session labels from IDs, matches by label+ID+wildcard

## Additional Infrastructure Added
- `_agent_messages` global store (max 200, auto-pruned)
- `do_OPTIONS` handler for CORS preflight
- Dashboard panels: Wiki, Inbox (Collisions and Sessions already existed)
- SOUL.md: "Don't use absolute Windows paths" rule
- Memory: LUMEN FS tools require relative paths
