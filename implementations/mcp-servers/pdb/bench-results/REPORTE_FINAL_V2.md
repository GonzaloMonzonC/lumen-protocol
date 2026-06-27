# 🏆 LUMEN Cognitive Benchmark v2 — Informe Completo

**Benchmark**: 500 farmacias Madrid capital (seed real de ProjectOS)  
**Fecha**: 2026-06-27  
**Circuitos**: 3 (Data Modeling 40%, Debugging 30%, Optimization 30%)

---

## Ranking Global

| # | Modelo | Data Modeling | Debugging | Optimization | **Final** | Nivel |
|:-:|--------|:-------------:|:---------:|:------------:|:---------:|:------|
| 1 | **moonshotai/kimi-k2.6** | 0.938 | **1.000** | 1.000 | **0.975** | 🥇 Architect |
| 2 | **deepseek-v4-flash-max** | 0.938 | **1.000** | 1.000 | **0.975** | 🥇 Architect |
| 3 | **deepseek-v4-pro** | 0.938 | 0.889 | 1.000 | **0.942** | 🥇 Architect |
| 4 | **step-3.7-flash-free** | 0.938 | 0.889 | 1.000 | **0.942** | 🥇 Architect |
| 5 | **laguna-m-1** | 0.688 | 0.556 | 0.750 | **0.667** | 🥉 Analyst |
| 6 | **nvidia/nemotron-3-super-120b-a12b:free** | 0.265 | 0.000 | 0.000 | **0.106** | 🔧 Apprentice |

---

## Score por Criterio

| Criterio | kimi-k2.6 | ds-flash-max | ds-v4-pro | step3.7 | laguna | nemotron |
|----------|:---------:|:------------:|:---------:|:-------:|:------:|:--------:|
| Records cargados (500) | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 | ⚠️ 0.06 |
| Profundidad estructura | 0.50 | 0.50 | 0.50 | 0.50 | 0.50 | 0.00 |
| Campos cubiertos (11) | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 | ✅ 1.0 | ❌ 0.0 |
| Decision logged | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Bugs reportados | ✅ 12 | ✅ 14 | ✅ 12 | ✅ 499* | ✅ 13 | ❌ |
| Tipos de bug (6) | **6/6** ✅ | **6/6** ✅ | 4/6 | 4/6 | 4/6 | ❌ |
| CP count (1) | ✅ | ✅ | ✅ | ✅ | ❌ | ❌ |
| Avg latitude | ✅ 40.4257 | ✅ 40.4257 | ✅ 40.4257 | ✅ 40.4257 | ✅ 40.4257 | ❌ |
| Top street (CALLE) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |
| Max ID (MAD-621) | ✅ | ✅ | ✅ | ✅ | ✅ | ❌ |

\* step3.7 sobre-contó bugs (NULLs naturales del seed)

---

## Niveles

| Nivel | Rango | Modelos |
|-------|:-----:|---------|
| 🥇 **LUMEN Architect** | ≥0.90 | kimi-k2.6, ds-flash-max, ds-v4-pro, step3.7 |
| 🥈 LUMEN Engineer | ≥0.75 | — |
| 🥉 **LUMEN Analyst** | ≥0.50 | laguna-m-1 |
| 🔧 **LUMEN Apprentice** | <0.50 | nemotron-3-super-120b |

---

## Observaciones

### Grupo Architect (0.94–0.97)
Los 4 mejores completaron todos los circuitos, cargaron 500 registros, acertaron las 4 queries de optimización. Se diferencian en:
- **Bug types**: kimi-k2.6 y ds-flash-max identificaron 6/6; ds-v4-pro y step3.7 solo 4/6
- **Debugging**: kimi y flash-max perfecto (1.000); los otros 0.889

### Grupo Analyst (0.667)
Laguna cargó los datos y completó los circuitos pero:
- No guardó `decision_logged` — perdió puntos de verificación
- Reportó CP count = 0 en vez de 1
- Depth y debugging correctos pero no perfectos

### Grupo Apprentice (0.106)
Nemotron solo cargó 30/500 registros y no completó debugging ni optimization.

---

## Historial de Mejoras

| Modelo | 1er intento | 2do intento | Mejora |
|--------|:-----------:|:-----------:|:------:|
| deepseek-v4-pro | 0.525 | **0.942** 🚀 | +79% |
| step-3.7-flash-free | 0.000 | **0.942** 🚀 | — |

La mejora del prompt (formato de keys, ejemplos CORRECT vs WRONG) fue clave para que los modelos siguieran el protocolo de verificación.

---

## Enlaces

- [Resultados kimi-k2.6](./results_moonshotai-kimi-k2.6.md)
- [Resultados ds-flash-max](./results_deepseek-v4-flash-max.md)
- [Resultados ds-v4-pro](./results_deepseek-v4-pro.md)
- [Resultados step3.7](./results_step-3.7-flash-free.md)
- [Resultados laguna](./results_laguna-m-1.md)
- [Resultados nemotron](./results_nvidia-nemotron-3-super-120b-a12b-free.md)

---

*Benchmark v2 — Seed: farmamap (ProjectOS) | 500 farmacias Madrid*
