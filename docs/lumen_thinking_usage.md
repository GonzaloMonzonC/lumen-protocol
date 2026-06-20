# Lumen Thinking Tools — Usage Guide
## Updated June 20, 2026 (post-session experience)

**34 tools** across thinking, filesystem, and web servers. **49 total**.
Token-efficient output: 90-95% savings with compact mode.

---

## Table of Contents
1. [Core Philosophy](#core-philosophy)
2. [The 5 New Token-Efficient Tools](#the-5-new-token-efficient-tools)
3. [Compact Mode](#compact-mode)
4. [Proactive System](#proactive-system)
5. [Pattern: Token-Conscious Workflow](#pattern-token-conscious-workflow)
6. [Pattern: Debugging with Cache](#pattern-debugging-with-cache)
7. [Pattern: Enterprise Monitoring](#pattern-enterprise-monitoring)
8. [Dashboard Integration](#dashboard-integration)
9. [Common Pitfalls](#common-pitfalls)
10. [Example – Real Session Flow](#example--real-session-flow)

---

## Core Philosophy

LUMEN thinking tools externalize reasoning so it survives context compaction.
The key insight from 20+ hours of intensive use:

**Output tokens cost 10-20× more than input tokens** (input caches, output doesn't).
Every tool should return the minimum text needed. The LLM already knows what
arguments it sent — don't echo them back.

**The system is now proactive.** `state_snapshot` reminds you of works pending >30min
and suggests patterns based on your current reasoning. The cognitive exoskeleton
doesn't wait to be asked.

---

## The 5 New Token-Efficient Tools

### `state_snapshot()` — 43 chars
One-line system health. Replaces 3-4 separate tool calls.
```
⚡ 10c · 34t · 10.0★ · 17p · 14w · 263 calls ⏰ 2 works >30min 💡 3 pattern suggestions
```
Use as your first call in any session. See pending works and pattern suggestions
instantly.

### `thought_compress(chainId, target=3)` — 25 chars
Compresses N thoughts to M key thoughts. Selects first, last, and top-scored middle.
```
✅ Compressed 6→3 thoughts
```
Use instead of `thought_summarize` when you just need the count, not themes.

### `chain_diff(chainId, from=1, to=last)` — 21 chars
Shows only what changed between two points in a chain.
```
Δ #1→#3: +3 · ↻0 · 🌿0
```
Use to check if progress was made since last check. No need to re-read all thoughts.

### `tool_cache(key, value=..., ttl=300)` — 8-22 chars
Cache expensive results across tool calls.
```
💾 Cached          # SET
🎯 Cache hit: ...  # GET — pays off from 2nd query
❌ Cache miss      # key not found or expired
```
Cache anything that might be queried again: bug findings, DB results, analysis.

### `batch_call(tools=[...])` — 32 chars for 5 tools
Execute N tools in sequence, ONE output line.
```
Batch: 4/4 OK — ✅ state_snapshot ✅ tool_cache ✅ chain_diff ✅ thought_compress
```
Saves 40% overhead vs N individual calls. Max 10 tools per batch.

---

## Compact Mode

All tools now default to compact output. Key changes:

| Tool | Old (verbose) | New (compact) | Savings |
|---|---|---|---|
| `sequential_thinking` | 5 previous thoughts (~400 chars) | "Last: #X: ..." (~100 chars) | 75% |
| `thought_summarize` | Full theme preview (~800 chars) | "📋 N themes · M thoughts" (~23 chars) | 97% |
| `pattern_match` | All matches with scores (~400 chars) | Top match only (~50 chars) | 87% |
| `state_snapshot` | N/A | 43 chars | — |
| `tool_cache` | N/A | 8-22 chars | — |

Pass `verbose=true` when you need full output. Default is compact.

---

## Proactive System

The system now reminds you of things without being asked.

**`state_snapshot` shows:**
```
⏰ 2 works >30min    ← Works that should be closed
💡 3 pattern suggestions  ← Similar patterns to consider
```

**`pattern_record` suggests:**
When you record a new pattern with >30% keyword overlap to existing ones,
it automatically shows up to 3 similar patterns. No manual `pattern_match` needed.

**Auto-evaluate:**
Every new thought gets scored automatically (heuristic: specificity,
actionability, length). No more chains with zero scores.

---

## Pattern: Token-Conscious Workflow

Use this when starting any new task. It gives you full context in ~50 tokens.

```text
1. state_snapshot()           # 10t — system health, pending works
2. sequential_thinking(plan)  # 25t — compact mode
3. tool_cache('plan', plan)   # 2t — cache for follow-up queries
4. batch_call([               # 12t — batch next checks
     state_snapshot,
     tool_cache('plan')
   ])
Total: ~49 tokens
```

Compare to old way: `thought_summarize` + `pattern_match` + `work_start` = ~60 tokens,
with far less information density.

---

## Pattern: Debugging with Cache

Debug a production issue across multiple sessions.

```text
Session 1:
1. state_snapshot()                           # baseline
2. sequential_thinking(investigate bug)       # reasoning
3. tool_cache('bug_db', 'pool exhausted')     # save finding
4. state_snapshot()                           # verify after work

Session 2 (next day — all state persists):
1. state_snapshot()                           # check system
2. tool_cache('bug_db')                       # 22 chars — cache hit!
3. chain_diff('bug_chain', from=1)            # what was the conclusion?
4. batch_call[state_snapshot, tool_cache]      # monitor after fix

Cost: Session 2 costs ~40 chars vs ~200 chars if you re-investigated.
```

---

## Pattern: Enterprise Monitoring

Monitor system health across multiple services.

```text
Every hour:
1. state_snapshot()              # 43 chars — full system state
2. tool_cache('hourly_state')    # 22 chars — cached for comparison

Every 8 hours:
3. chain_diff('monitoring', ...)  # 21 chars — what changed?
4. batch_call[                   # 32 chars — final report
     state_snapshot,
     tool_cache('hourly_state')
   ]

Total for 8h monitoring: ~500 chars.
Old way (no cache, verbose): ~2000+ chars.
```

---

## Dashboard Integration

The dashboard at `http://localhost:9876/` auto-starts with the plugin.

**What it gives you:**
- KPIs: thoughts, chains, avg score, contradictions, tool calls
- Activity chart: bezier curve with gradient area
- System Pulse: NOW (active), RECENT (completed), BLOCKED
- Chain explorer with clickable modals
- Wiki, Clusters, Model, Decisions, Assumptions panels
- Live status indicator (WebSocket or HTTP polling)

**Pro tip:** The data comes from `.thinking_state.json` — the same file the
MCP server saves to. Every 10 tool calls, the dashboard auto-refreshes.

---

## Common Pitfalls (learned the hard way)

| Pitfall | Symptom | Fix |
|---|---|---|
| **Zombie dashboard** | Connection refused on :9876 | Plugin now kills stale processes. Restart Hermes. |
| **File locking** | WinError 32 on save | Fixed: exponential backoff (5 retries, 10-80ms) |
| **Empty params crash** | KeyError in tool | Fixed: all tools use `.get()` with defaults |
| **Chains without scores** | All chains show 10.0★ | Fixed: auto-evaluate ALL chains now |
| **Broken HTML dashboard** | Dashboard shows "Updated: --" forever | Check for stale server process (PID != current) |
| **Missing new tools** | `state_snapshot` not found | Restart Hermes — plugin caches tools on start |

---

## Example – Real Session Flow

This is what a typical LUMEN session looks like with the current tools:

```text
→ USER: search for the bug in the DB timeout code

→ AGENT:
  1. state_snapshot()                    # 43c — "⚡ 10c · 34t ... ⏰ 1 work >30min"
  2. sequential_thinking("DB timeout...") # 100c — plan investigation
  3. search_files("timeout.*pool")        # search codebase
  4. read_file("db/pool.py")              # read config
  5. tool_cache("db_pool", "max=50")      # 8c — save finding
  6. batch_call[                          # 32c — verify + cache check
       state_snapshot,
       tool_cache("db_pool")
     ]
  7. pattern_record("timeout-pool", ...)  # 30c — save pattern (auto-suggests similar)

  Total: ~200 chars output
  Old way (no compact, no cache): ~800+ chars
  Savings: 75%
```

---

## References

- README: [`README.md`](../README.md)
- Cognitive OS architecture: [`docs/COGNITIVE_OS.md`](../docs/COGNITIVE_OS.md)
- Enterprise stress testing: [`docs/enterprise-stress-testing-2026-06-20.md`](../docs/enterprise-stress-testing-2026-06-20.md)
- Token-efficient tools: [`docs/token-efficient-tools-2026-06-20.md`](../docs/token-efficient-tools-2026-06-20.md)
- Cognitive Workflows skill: `skills/lumen-cognitive-workflows/SKILL.md`
- LUMEN WebSocket dashboard: [`docs/lumen-ws-dashboard.md`](../docs/lumen-ws-dashboard.md)

---

*This document reflects practical experience from 20+ hours of LUMEN tool usage.
Output token savings: 90-95% vs traditional verbose mode.*
