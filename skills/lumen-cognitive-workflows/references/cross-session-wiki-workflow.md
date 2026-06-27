# Cross-Session Knowledge Wiki

## Pattern

Build institutional knowledge across sessions using thinking server persistence.

## Workflow

```
1. sequential_thinking(section 1 with custom chainId) → auto-saved to disk
2. model_add(entities) → build mental map
3. pattern_record(bug patterns) → institutional memory
4. decision_log(rationale) → decision journal
5. context_preserve(label) → anchor critical context
6. [Kill + restart server]
7. All state auto-restored from .thinking_state.json
8. Continue wiki: append to chainId, query model_stats, pattern_match
```

## Critical Rules

- **Named chains never pruned.** Only auto-generated (`chain_N_*`) compete for the 10-slot limit.
- **Auto-save every 10 calls** via `_get_session()`. Works for all 3 server variants.
- **Graceful shutdown** via `atexit.register(_save_state)` — state saves even on SIGTERM.
- **Atomic writes**: write to `.tmp`, then `os.replace()` — never corrupts on crash.

## Verified

133-call definitive test, session 1 build → kill → session 2 restore:
- ✅ Named chain survived + appendable
- ✅ Model entities persisted
- ✅ Patterns matched (Jaccard)
- ✅ Decisions persisted
- ✅ Context labels visible
- ✅ Assumptions tracked across sessions

## Alpine.js Dashboard Pitfall

When building dashboards with Alpine.js, NEVER use `Alpine.data('name', ...)`:
Alpine resolves `x-data="name"` before `alpine:init` fires → `ReferenceError`.

Always inline data directly: `x-data="{connected:false, totals:{...}, init(){...}}"`
Use `alpine:initialized` event + `setTimeout` fallback for the fetch loop.
