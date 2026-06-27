# Full System Status Check Pattern

**When**: Starting a session where you need complete situational awareness across all LUMEN cognitive subsystems — context, work, assumptions, patterns, sessions, collisions, and preservation state.

**Frequency**: At session start for complex tasks, or before making architectural decisions.

**Core Tools**: All 34 thinking tools + 13 filesystem tools + 2 web tools (49 total).

## Compact Query Sequence (Token-Efficient)

Use `state_snapshot` (43 chars) as the primary lens, then selectively drill down:

| Tool | Chars | Purpose |
|------|-------|---------|
| `state_snapshot()` | 43 | One-line system health (chains, thoughts, patterns, works, calls) |
| `work_log()` | ~120 | Current work items with status |
| `decision_list()` | ~200 | Architectural decisions with rationales |
| `model_stats()` | ~150 | Mental model entity counts, dependencies |
| `pattern_match("current-topic")` | ~50 | Find relevant patterns from institutional memory |
| `list_assumptions()` | ~180 | Hidden premises flagged for validation |
| `session_list()` | ~200 | Active sessions + collision warnings |
| `collision_check()` | 16 | File conflict detection |
| `context_check()` | ~60 | Preserved contexts still available |
| `server_stats()` | ~80 | Filesystem endpoint health |
| `tool_cache("key")` | ~12 | Cached results for repeated queries |
| `batch_call([...])` | 32 | Multiple tools in one output line |

## Full Status Check Script

```python
# 1. System health snapshot
state_snapshot()  # → 10c · 32t · 9.2★ · 20p · 16w · 289 calls

# 2. Work and decisions
work_log()  # → 8 in progress | 2 blocked | 6 done
decision_list()  # → Review recent architecture decisions

# 3. Knowledge graph state
model_stats()  # → Entities, connections, roles

# 4. Session awareness
session_list()  # → Active sessions with stats, collision warnings
collision_check()  # → Verify no file conflicts

# 5. Assumptions landscape
list_assumptions()  # → Hidden premises requiring validation

# 6. Pattern recall
pattern_match("task-description")  # → Prior bugs/fixes

# 7. Context preservation
context_check()  # → Anchored contexts still valid

# 8. Batch for efficiency (after initial queries)
batch_call([
    {"name": "state_snapshot", "args": {}},
    {"name": "work_log", "args": {}},
    {"name": "model_stats", "args": {}}
])
```

## Signals That Warrant This Check

- Starting a task that spans multiple sessions
- Before making irreversible changes (deletes, rewrites)
- When user says "dale a tope" / "go all out"
- Before implementing Phase C / new features
- After detecting "works >30min" from state_snapshot