---
name: lumen-pro-tools
description: '👽 PRO-level LUMEN tools — unified_search, cognitive_integrity, state_snapshot, thought_compress, chain_diff, tool_cache, batch_call. Token-efficient operations and system diagnostics.'
version: 1.0.0
author: Cadences Lab
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [lumen, pro, token-efficient, search, diagnostics, tools]
---

# 👽 LUMEN PRO Tools — Advanced Diagnostics & Efficiency

> 7 tools for system-wide search, health diagnostics, and token-efficient operations. These are the "PRO" layer on top of the base LUMEN tools.

---

## 1. System Snapshot (43 chars)

```
👽 state_snapshot
→ ⚡ 10c · 32t · 10.0★ · 25p · 16w · 440 calls
```

**What it shows:** chains · thoughts · avg score · patterns · works · calls  
**When to use:** Before any task (baseline) and after (comparison)  
**Token cost:** 43 characters — the cheapest tool in the system

---

## 2. Unified Search (8ms)

```
👽 unified_search(query="trading", limit=5)
→ [TASK] 3 results
→ [QA] 1 result
→ [PATTERN] 1 result
```

**Searches across:** tasks, patterns, decisions, Q&A (scratchpad), model entities, web snapshots  
**Searches in:** title, description, **tags** (fix June 2026), **niche names**  
**Tip:** Use short keywords. Search is case-insensitive. No accents normalization.

**Limitations:**  
- Does NOT search in reasoning chains (thoughts) — use `thought_similarity` for that  
- Patterns in local sessions may not appear (only `_global_patterns` indexed)  

---

## 3. Cognitive Integrity (2ms)

```
👽 cognitive_integrity()
→ ⚠ Cognitive Integrity: 1 warning(s)
→ Total: 58 tasks + 3 QA + 8 decisions + 25 patterns + 6 snapshots
→ 58 tasks without links
→ Health score: 85/100
```

**Checks:**  
- Tasks without cognitive links (chains/patterns/decisions)  
- Unanswered Q&A pairs  
- Stale decisions (90+ days without revisit)  
- Patterns never matched (may be obsolete)  

**Health score formula:** `max(0, 100 - warnings * 15)` — each issue deducts 15 points.

---

## 4. Token-Efficient Tools (90-95% savings)

| Tool | Output chars | Use case | Savings vs verbose |
|------|:-----------:|----------|:------------------:|
| `state_snapshot` | 43 | Baseline system health | ~90% vs full metrics |
| `thought_compress(chainId, N)` | ~25 | Summarize chain to N key thoughts | ~95% vs full chain |
| `chain_diff(chainId, from, to)` | ~21 | What changed between two steps | ~95% vs full chain |
| `tool_cache(key, value, ttl)` | ~8 | Store repeated query results | 100% after first hit |
| `batch_call([...])` | ~32 | N tools → 1 output line | ~40% overhead savings |

**Pattern — Before (verbose, 1450 chars):**
```
sequential_thinking(long) → 300 chars
thought_evaluate(chain, 1) → 150 chars
thought_summarize(chain) → 800 chars
pattern_match(desc) → 200 chars
```

**After (compact, 183 chars — 87% savings):**
```
state_snapshot() → 43 chars
batch_call([thought_evaluate, pattern_match]) → 32 chars
tool_cache('key', value) → 8 chars
```

---

## 5. Enterprise Stress Test Results

Tested with 30 niches, 58 tasks, 12 teams (Werfen/Systelabs scenario):

| Test | Latency | Result |
|------|:-------:|:------:|
| `kanban_stats(30 niches)` | 2ms | No pagination needed |
| `unified_search("coagulación")` | 8ms | 4 results across domains |
| `cognitive_integrity(58 tasks)` | 2ms | Health score 85/100 |
| `task_search(priority="critical")` | 10ms | 14 critical tasks |
| `niche_create(name="")` | 3ms | "Name required" ✅ |

**Conclusion:** No degradation with 3× data. LUMEN scales linearly.

---

## Pitfalls

- `_decisions` is per-session, not module-level. `cognitive_integrity` and `unified_search` must iterate `_sessions.values()` to find decisions. Fixed June 2026.
- `_patterns` vs `_global_patterns`: Local session patterns may not appear in global search. `pattern_match` checks both. `unified_search` only checks `_global_patterns`.
- Unicode / accented search: "coagulación" ≠ "coagulacion". LUMEN does ASCII exact match.
- `tool_cache` TTL in seconds. Default 300 (5 min). Max 86400 (24h).
- `batch_call` max 10 tools per call. Tools execute sequentially. If one fails, the rest still execute.
