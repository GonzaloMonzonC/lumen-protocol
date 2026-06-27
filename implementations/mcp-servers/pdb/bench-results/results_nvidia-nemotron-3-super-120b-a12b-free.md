# 🏆 LUMEN Cognitive Benchmark v2 — Model Results

## nvidia/nemotron-3-super-120b-a12b:free

**Date**: 2026-06-27  
**Score**: **0.106** — 🔧 LUMEN Apprentice

---

### 📊 Score Breakdown

| Circuit | Weight | Score | Weighted |
|---------|:------:|:-----:|:--------:|
| 🏗️ Data Modeling | 40% | **0.265** | 0.106 |
| 🐛 Debugging | 30% | **0.000** | 0.000 |
| ⚡ Optimization | 30% | **0.000** | 0.000 |
| **🔧 Final** | 100% | **0.106** | |

---

### Circuit 1 — Data Modeling (0.265)

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| Records loaded | **0.060** | only 30/500 |
| Structure depth | 0.000 | no structure found |
| Field coverage | 0.000 | 0/11 fields |
| Decision logged | 0.000 | ❌ |
| Subscript documented | 1.000 | ✅ saved structure description |

### Circuit 2 — Debugging (0.000)

Did not complete. No data found in `^BENCH_MODEL_V2` for circuit 2.

### Circuit 3 — Optimization (0.000)

Did not complete. No data found in `^BENCH_MODEL_V2` for circuit 3.

---

### Analysis

Nemotron attempted the benchmark but:
1. **Only loaded 30/500 records** — significantly incomplete
2. **No debugging circuit** — did not inspect `^FARMA_BUGS`
3. **No optimization** — did not compute any queries
4. **Documented subscript structure** ✅ — the only criterion met

The model correctly identified the need to document its structure but did not complete the data loading or the other two circuits.

---

*Model: nvidia/nemotron-3-super-120b-a12b:free | Seed: 500 farmacias Madrid capital*
