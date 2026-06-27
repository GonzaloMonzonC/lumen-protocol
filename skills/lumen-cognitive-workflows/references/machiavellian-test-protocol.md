# Machiavellian Test Protocol — 17-Phase Adversarial Validation

## When to Run

After any significant change to the thinking server (new tools, handler fixes, state persistence changes), or at the start of a new session to establish baseline confidence.

## The 5 Phases

### FASE 1 — Kanban Edge (5 tests)
```
niche_create("")              → "Niche name required"
task_create(niche="fake")     → "Niche not found"
task_move(id="fake")          → graceful empty
task_delete(id="fake")        → "Task not found"
kanban_stats(niche="fake")    → "Niche not found"
```

### FASE 2 — Web Edge (3 tests)
```
web_snapshot(url=invalid)     → Error getaddrinfo
task_link_url(task="fake")    → "Task not found"
web_snapshots_list(task="fake") → empty list
```

### FASE 3 — Q&A Edge (3 tests)
```
qa_ask(question="")           → "Question required"
qa_list(tags=["nonexistent"])  → empty result
qa_link(qa_id="fake")         → "Q&A not found"
```

### FASE 4 — PRO Tools Edge (4 tests)
```
unified_search("unicode🔥🚀")  → "No results" (no crash)
unified_search("")             → "Query required"
cognitive_integrity()          → health score 85-100
pattern_match("")              → 0 matches
```

### FASE 5 — Cognitive Stress (2 tests)
```
task_search("a")               → 18+ results, no crash
model_map()                    → 33+ entities, 3 directories
```

## Expected Result

17/17 pass, 0 exceptions, 0 crashes. Every error case returns a graceful message, never a stack trace or silent hang.

## History

- **2026-06-21**: 17/17 pass. Bug found during test: `unified_search` didn't search tags/niche names (commit 6162e87). `cognitive_integrity` showed 0 decisions (fixed, decisions are per-session).
