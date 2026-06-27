# Adversarial Benchmark Plan — June 19, 2026

Full 5-phase adversarial evaluation plan for LUMEN Thinking tools. Designed using
LUMEN's own cognitive tools (12-thought chain `machiavellian-plan`).

## Philosophy

> **Not "does it work?" — "where does it break, how much can it take, and is it worth it?"**

## 7 Adversarial Scenarios

| Code | Name | What it attacks | Success metric |
|------|------|-----------------|----------------|
| **A** | Debug Ghost | Bug 1/10 runs → hypothesis + contradiction + pattern_match | Finds fix <5 min? |
| **B** | Architecture Pivot | 15 hidden assumptions → assume/check_assumption batch + decision_log | Detects violated pre-commit? |
| **C** | Multi-Agent Collision | 5 agents same codebase → session_init ×5 + thought_bridge cross | Zero state bleed |
| **D** | Knowledge Decay | Session A learns → Session B (24h) recovers | recall@1 >70% @24h |
| **E** | Cognitive Overload | 100 calls <30s → burst throughput | p99 <5ms, error 0% |
| **F** | Contradiction Injection | 20 thoughts, 5 planted contradictions | contradiction recall >90% |
| **G** | Model Poisoning | 500 adversarial entities (cycles, orphans) | query latency, map correctness |

## 8 Machiavellian Traps

| Trap | What it tests | Metric |
|------|---------------|--------|
| **T1** Thought Pollution | Chain A(50) → thought_bridge from Chain B(empty) | Signal-to-noise |
| **T2** Pattern Cannibalism | 1000 near-duplicates → pattern_match | precision@1 vs recency bias |
| **T3** Assumption Gaslighting | assume X → violated → assume ¬X → confirmed | Model consistency |
| **T4** Session Hydra | 20 parallel sessions same pattern_name | Namespace isolation |
| **T5** Context Zombie | TTL=1s → wait 2s → decay? TTL=∞ → kill → recover? | Persistence boundary |
| **T6** Work Phantom | work_done(id≠start) → mismatch detect, 10-level nesting | State machine correctness |
| **T7** Model Poison Pill | 1-hop cycle → infinite? 10k entities query ".*" | Query safety |
| **T8** Decision Time Bomb | revisit_trigger="never" + 10k alternatives | Resource bounds |

## Hard Thresholds (non-negotiable for SUPERIOR)

| Metric | ✅ PASS | ⚠️ CONDITIONAL | ❌ FAIL |
|--------|---------|----------------|---------|
| p99 latency | <5ms ALL tools | 5-50ms | >50ms ANY |
| Throughput sustained | >1000 calls/sec | 100-1000 | <100 |
| pattern_match precision@1 | >80% (ground truth) | 50-80% | <50% |
| thought_contradiction recall | >90% (injected) | 70-90% | <70% |
| Session bleed | ZERO (100 agents) | <5% | >5% |
| Cross-session recall@1 @24h | >70% | 40-70% | <40% |
| Data corruption under chaos | ZERO | 1-2 recoverable | Irreversible |
| Cognitive ROI | >50x | 10-50x | <10x |

**KILL SWITCH**: FASE 0 baseline p99 >100ms → ABORT immediately.

## 5 Phases (35h active + 7d passive)

```
DAY 1 (6h):  FASE 0 Baseline (2h) → FASE 1 Unit Stress (4h)
DAY 2 (6h):  FASE 2 Composition Stress (6h)
DAY 3 (4h):  FASE 4 Adversarial Injection (4h) + Setup FASE 3/5
DAY 4-10:    FASE 3 Longitudinal (30min/day, cronjob) + FASE 5 Shadow (14d)
```

Each phase has GO/NO-GO gate. FAIL at any phase → document, don't continue.
CONDITIONAL → decide depth vs breadth.

## Automation

- Harness: Python script orchestrating all tools, output → JSONL append-only
- Ground truth generators: inject_known_patterns(), inject_contradictions(), spawn_agents(), poison_model()
- Metrics collector: context_estimate + server_stats + session_list every 10s → timeseries
- Report generator: thought_summarize + thought_to_plan + model_query → auto markdown
- CI: cronjob `lumen-benchmark-phase3` schedule="0 9 * * *" for FASE 3

## Deliverables

1. `benchmark-report-phase0-4.jsonl` (raw)
2. `benchmark-report-phase3-longitudinal.jsonl` (timeseries)
3. `benchmark-report-phase5-shadow.md` (narrative + metrics)
4. `FINAL_VERDICT.md` (PASS/CONDITIONAL/FAIL per criterion)
5. Skill `lumen-benchmark-suite` with full reproducible harness
