# 🗂️ LUMEN Cognitive Benchmark v3 — Filesystem Indexer

## deepseek-v4-flash-min

**Date**: 2026-06-27  
**Score**: **0.699** — 🥉 LUMEN Analyst

---

### Score Breakdown

| Circuit | Weight | Score | Weighted |
|---------|:------:|:-----:|:--------:|
| 🔍 Scan + Index | 35% | **0.999** | 0.349 |
| ⚡ Zero-Token Queries | 35% | **0.997** | 0.349 |
| 🧠 Cognition + Action | 30% | **0.000** | 0.000 |
| **🥉 Final** | 100% | **0.699** | |

### Key Observations

- **Best structure depth** of all models (depth=3)
- **No C3**: Did not create wiki, kanban tasks, cleanup analysis, or patterns
- Matches flash-max and step3.7 on scanning and queries
- Loses 30% of total score by skipping the cognitive/action phase

### Comparison vs flash-max

| Criterion | flash-min | flash-max |
|-----------|:---------:|:---------:|
| Files | 11,177 | 11,156 |
| Depth | **3** 🏆 | 2 |
| Queries | 0.997 | 0.999 |
| Wiki/Kanban | ❌ 0.000 | ✅ 1.000 |
| **Final** | **0.699** | **1.000** |

---

*Model: deepseek-v4-flash-min | Target: lumen-protocol/*
