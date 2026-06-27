# Cross-Session Context Recovery

**Quick workflow to answer "¿Qué estábamos trabajando hace un momento?" using LUMEN tools**

## Tool Sequence

When the user asks about recent work in another session, use this exact sequence:

```text
1. state_snapshot()                    → System health: chains, thoughts, works, patterns
2. work_log()                          → Current work items, status, durations
3. session_search(limit=5, sort=newest) → Most recent sessions
4. session_search(query="topic")         → Find specific topic
5. decision_list()                       → Architectural decisions
6. model_stats()                         → Mental model entities
7. pattern_match(description="...")      → Relevant patterns from past work
8. session_list()                        → Active sessions + collision warnings
9. collision_check()                     → File collision detection
10. context_check()                       → Preserved context status
11. tool_cache(key)                      → Cached expensive results
12. thought_bridge(thought="...")          → Cross-chain connections
```

## Real Example: ProjectOS Markdown Audit

**User**: "usa todas las tools de lumen y dime en qué estabamos trabajando hace un momento en otra sesión"

**Sequence executed and results**:

| Tool | Result |
|------|--------|
| `state_snapshot()` | `⚡ 10c · 32t · 10.0★ · 23p · 16w · 302 calls` |
| `work_log()` | 8 in_progress, 2 blocked, 6 done — MD categorization task |
| `session_search(query="LUMEN dashboard")` | Session 20250619_053123 — Cognitive OS v3.0 |
| `decision_list()` | 7 decisions, 2 confirmed, 5 unverified |
| `model_stats()` | 26 files mapped, 15 dependencies |
| `session_list()` | 8 active sessions (default, agent-b variants, stress agents) |
| `collision_check()` | No collisions in last 5 min |
| `context_check()` | No items preserved |
| `tool_cache(lumen-dashboard-state)` | Cache miss (no cached data) |
| `thought_bridge(...)` | No bridges found (insufficient chains) |
| `thought_summarize(chain_c_...)` | Chain not found (invalid chain ID) |
| `list_assumptions()` | 7 assumptions, 2 confirmed, 5 unverified |

**Recovered work**: Markdown file mapping in ProjectOS (1,178 files, 18.3 MB total, 66 duplicates between dist/public), plus LUMEN Cognitive OS Phase C (auto-negotiation, cross-session learning).

## Key Insights

- **Always start with `state_snapshot()`** — gives immediate sense of cognitive load
- **`session_search()` without args** shows most recent sessions chronologically
- **`work_log()`** shows actual work status across multiple sessions
- **`model_stats()`** reveals accumulated knowledge entities
- **`session_list()` collision warnings** prevent repo conflicts

## When to Record

- After completing substantial cross-session analysis
- When user explicitly asks about previous work
- When transitioning between major feature work