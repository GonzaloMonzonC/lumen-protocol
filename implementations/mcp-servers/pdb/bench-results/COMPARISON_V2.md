# 📊 LUMEN Cognitive Benchmark v2 — Comparison

## 3-Model Results

| Model | Data Modeling | Debugging | Optimization | **Final** | Level |
|-------|:-------------:|:---------:|:------------:|:---------:|:-----:|
| **deepseek-v4-flash-max** | 0.938 | 0.944 | 1.000 | **0.958** | 🥇 LUMEN Architect |
| **laguna-m-1** | 0.688 | 0.556 | 0.750 | **0.667** | 🥉 LUMEN Analyst |
| **step-3.7-flash-free** | 0.000 | 0.000 | 0.000 | **0.000** | 🔧 LUMEN Apprentice |

## Key Insights

| Aspect | deepseek | laguna | step3.7 |
|--------|:--------:|:------:|:-------:|
| Data loaded (500) | ✅ | ✅ | ✅ |
| Correct ^GLOBAL | ^FARMA | ^FARMA | ❌ ^FARMACIAS |
| Decision logged | ✅ | ❌ | ❌ |
| Bugs inspected | ✅ | ✅ | ❌ |
| Bug types found | 5/6 | 4/6 | 0/6 |
| CP count correct | ✅ (1) | ❌ (0) | ❌ |
| Avg lat correct | ✅ | ✅ | ❌ |
| Keys structure | ✅ correct | ✅ correct | ❌ wrong depth |

## Per-Criterion Comparison

| Criterion | deepseek | laguna | step3.7 |
|-----------|:--------:|:------:|:-------:|
| Records loaded | 1.000 | 1.000 | 0.000 |
| Structure depth | 0.500 | 0.500 | 0.000 |
| Field coverage | 1.000 | 1.000 | 0.000 |
| Decision logged (C1) | **1.000** | 0.000 | 0.000 |
| Subscript documented | 1.000 | 1.000 | 0.000 |
| Bugs reported | 1.000 | 1.000 | 0.000 |
| Bug types identified | **0.833** | 0.667 | 0.000 |
| Decision logged (C2) | **1.000** | 0.000 | 0.000 |
| CP count | **1.000** | 0.000 | 0.000 |
| Avg latitude | 1.000 | 1.000 | 0.000 |
| Top street | 1.000 | 1.000 | 0.000 |
| Max ID | 1.000 | 1.000 | 0.000 |

## Level Distribution

| Level | Models |
|-------|--------|
| 🥇 LUMEN Architect (≥0.90) | deepseek-v4-flash-max |
| 🥈 LUMEN Engineer (≥0.75) | — |
| 🥉 LUMEN Analyst (≥0.50) | laguna-m-1 |
| 🔧 LUMEN Apprentice (<0.50) | step-3.7-flash-free |

## Individual Results

- [deepseek-v4-flash-max](./results_deepseek-v4-flash-max.md) — 0.958 🥇
- [laguna-m-1](./results_laguna-m-1.md) — 0.667 🥉
- [step-3.7-flash-free](./results_step-3.7-flash-free.md) — 0.000 🔧

---

*Benchmark v2 — 500 farmacias Madrid capital | 3 circuits (open-ended)*

