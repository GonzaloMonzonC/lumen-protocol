# 🏆 LUMEN Cognitive Benchmark v2 — Model Results

## deepseek-v4-pro

**Date**: 2026-06-27  
**Score**: **0.525** — 🥉 LUMEN Analyst

---

### 📊 Score Breakdown

| Circuit | Weight | Score | Weighted |
|---------|:------:|:-----:|:--------:|
| 🏗️ Data Modeling | 40% | **0.500** | 0.200 |
| 🐛 Debugging | 30% | **0.333** | 0.100 |
| ⚡ Optimization | 30% | **0.750** | 0.225 |
| **🥉 Final** | 100% | **0.525** | |

---

### Circuit 1 — Data Modeling (0.500)

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| Records loaded | 1.000 | 500/500 ✅ |
| Structure depth | **0.000** | ❌ judge couldn't find ^GLOBAL |
| Field coverage | **0.000** | ❌ because global not found |
| Decision logged | 0.000 | ❌ key not saved |
| Subscript documented | 1.000 | ✅ |

**Issue**: `global_name` saved as `"^FARMA (primary) + ^FARMA_CP (CP index)"` — a description instead of just `"^FARMA"`. The judge can't parse this as a namespace name.

### Circuit 2 — Debugging (0.333)

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| Bugs reported | **0.333** | only 4 (planted ~14) |
| Bug types identified | 0.667 | 4/6 types |
| Decision logged | 0.000 | ❌ |

### Circuit 3 — Optimization (0.750)

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| CP count | 1.000 | ✅ 1 unique |
| Avg latitude | 1.000 | 40.4257 ✅ |
| Top street | 1.000 | CALLE ✅ |
| Max ID | **0.000** | reported "621" not "MAD-621" ❌ |

### 🔍 Issues

1. **global_name format**: Used description instead of raw GLOBAL name. The judge needs `"^FARMA"` not `"^FARMA (primary) + ^FARMA_CP (CP index)"`
2. **Max ID format**: Reported `621` instead of `MAD-621`. The judge expects the full ID string.
3. **Floats in subscripts**: Used `1.0`, `2.0` instead of `1`, `2` for circuit numbers.

---

*Model: deepseek-v4-pro | Seed: 500 farmacias Madrid capital*
