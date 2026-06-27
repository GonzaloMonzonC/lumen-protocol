# 📊 LUMEN Cognitive Benchmark v2 — Comparison

## Head-to-Head: deepseek-v4-flash-max vs laguna-m-1

| Circuit | deepseek-v4-flash-max | laguna-m-1 | Gap |
|---------|:---------------------:|:----------:|:---:|
| 🏗️ Data Modeling | **0.938** | 0.688 | +0.250 |
| 🐛 Debugging | **0.944** | 0.556 | +0.388 |
| ⚡ Optimization | **1.000** | 0.750 | +0.250 |
| **🥇 Final** | **0.958** | **0.667** | **+0.291** |

## Per-Criterion Comparison

| Criterion | deepseek | laguna | Winner |
|-----------|:--------:|:------:|:------:|
| Records loaded | 1.000 | 1.000 | 🤝 |
| Structure depth | 0.500 | 0.500 | 🤝 |
| Field coverage | 1.000 | 1.000 | 🤝 |
| Decision logged (C1) | **1.000** | 0.000 | 🏆 deepseek |
| Subscript documented | 1.000 | 1.000 | 🤝 |
| Bugs reported | 1.000 | 1.000 | 🤝 |
| Bug types identified | **0.833** | 0.667 | 🏆 deepseek |
| Decision logged (C2) | **1.000** | 0.000 | 🏆 deepseek |
| CP count | **1.000** | 0.000 | 🏆 deepseek |
| Avg latitude | 1.000 | 1.000 | 🤝 |
| Top street | 1.000 | 1.000 | 🤝 |
| Max ID | 1.000 | 1.000 | 🤝 |

## Where deepseek won

1. **Decision logging** — saved `decision_logged=yes` keys in both C1 and C2
2. **Bug type identification** — 5/6 vs 4/6 (better at categorizing bugs)
3. **CP count** — correctly reported 1 (NULL is still a value)

## Where laguna fell short

1. **Did not log decisions** — lost 20% of C1 score and 33% of C2 score
2. **Missed CP count** — reported 0 instead of 1
3. **Fewer bug types** — 4/6 vs 5/6

## Level Distribution

| Level | Models |
|-------|--------|
| 🥇 LUMEN Architect (≥0.90) | deepseek-v4-flash-max |
| 🥈 LUMEN Engineer (≥0.75) | — |
| 🥉 LUMEN Analyst (≥0.50) | laguna-m-1 |
| 🔧 LUMEN Apprentice (<0.50) | — |

## Individual Results

- [deepseek-v4-flash-max](./results_deepseek-v4-flash-max.md) — 0.958
- [laguna-m-1](./results_laguna-m-1.md) — 0.667

---

*Benchmark v2 — 500 farmacias Madrid capital | 3 circuits (open-ended)*
