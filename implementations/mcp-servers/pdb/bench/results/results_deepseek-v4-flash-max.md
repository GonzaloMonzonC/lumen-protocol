# 🏆 LUMEN Cognitive Benchmark v2 — Model Results

## deepseek-v4-flash-max

**Date**: 2026-06-27  
**Score**: **0.958** — 🥇 LUMEN Architect

---

### 📊 Score Breakdown

| Circuit | Weight | Score | Weighted |
|---------|:------:|:-----:|:--------:|
| 🏗️ Data Modeling | 40% | **0.938** | 0.375 |
| 🐛 Debugging | 30% | **0.944** | 0.283 |
| ⚡ Optimization | 30% | **1.000** | 0.300 |
| **🥇 Final** | 100% | **0.958** | |

---

### Circuit 1 — Data Modeling (0.938)

Designed `^FARMA(id, field)` flat structure with 11 fields per record.

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| Records loaded | 1.000 | 500/500 |
| Structure depth | 0.500 | depth=1 (ideal ≥2: id→field) |
| Field coverage | 1.000 | 11/11 fields |
| Decision logged | 1.000 | ✅ |
| Subscript documented | 1.000 | ✅ |

**Design decision**: Flat structure chosen intentionally since all 500 pharmacies are in Madrid province. No need for province→city hierarchy. 11 fields stored as subscripts for direct access without parsing.

---

### Circuit 2 — Debugging (0.944)

Inspected `^FARMA_BUGS` with `$ORDER` traversal.

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| Bugs reported | 1.000 | 12 affected records |
| Bug types identified | 0.833 | 5/6 types |
| Decision logged | 1.000 | ✅ |

**Bugs detected:**
- ✅ latitud = null (5 records: MAD-2..6)
- ✅ nombre = "" (3 records: MAD-7..9)
- ✅ ciudad/provincia fuera de Madrid (2 records: MAD-15 Barcelona, MAD-16 Valencia)
- ✅ latitud formato inválido (1 record: "cuarenta grados")
- ⬜ teléfono ausente (many natural + 1 planted)
- ✅ ID duplicado (MAD-25 = MAD-2)

---

### Circuit 3 — Optimization (1.000)

F loops + $ORDER traversal with M-Light computations.

| Criterion | Score | Detail |
|-----------|:-----:|--------|
| Unique CPs | 1.000 | 1 (all NULL in dataset) |
| Avg latitude | 1.000 | 40.4257 |
| Top street type | 1.000 | CALLE (399/500 = 79.8%) |
| Max ID | 1.000 | MAD-621 |

**Query results:**
- Top 3 street types: CALLE (399), AVDA (46), PASEO (28)
- Avg latitude: 40.4257
- Max ID: MAD-621
- CPs: 1 unique (all NULL)

---

### 📝 Notes

- Structure depth reduced due to homogeneous data (all Madrid). A hierarchical structure (province→city→id→field) would score higher on depth but be less efficient for this dataset.
- M-Light `$TR` within `$P` has a parsing limitation when using `pdb_m_eval` tool. Python fallback used for street type extraction; `$P` with `|` delimiter works correctly via `m.eval_expr()`.
- Bug type "teléfono ausente" not detected via summary regex because many records naturally have 'NULL' phone values in the original dataset.

---

*Model: deepseek-v4-flash-max | Seed: 500 farmacias Madrid capital*  
*Seed source: farmamap (ProjectOS)*
