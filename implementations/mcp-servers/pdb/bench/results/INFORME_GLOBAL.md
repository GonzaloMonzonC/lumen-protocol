# 📊 LUMEN Benchmark Suite — Informe Global

**Fecha**: 2026-06-27  
**3 benchmarks** · **8 modelos** · **15 circuitos**

---

## Resumen por Benchmark

### v1 — Cognitive Básico (Farmacias guiado)
*Mide: seguir instrucciones paso a paso con LUMEN tools*

| Modelo | PDB CRUD | M-Light | Cognitive | Knowledge | Kanban | Integración | **Final** |
|--------|:--------:|:-------:|:---------:|:---------:|:------:|:-----------:|:---------:|
| deepseek-v4-flash-max | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | **🥇 1.000** |
| step3.7-flash-free-nous | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | 1.000 | **🥇 1.000** |
| laguna-m1-free-openrouter | 0.750 | 1.000 | 1.000 | 1.000 | 1.000 | 0.333 | **🥈 0.871** |

→ **Conclusión**: Todos los modelos siguen instrucciones. v1 no discrimina.

### v2 — Cognitivo Abierto (Farmacias diseño libre)
*Mide: diseñar estructura, debugging, optimización con M-Light*

| Modelo | Data Modeling | Debugging | Optimization | **Final** |
|--------|:-------------:|:---------:|:------------:|:---------:|
| moonshotai/kimi-k2.6 | 0.938 | **1.000** | 1.000 | **🥇 0.975** |
| deepseek-v4-flash-max | 0.938 | **1.000** | 1.000 | **🥇 0.975** |
| deepseek-v4-pro | 0.938 | 0.889 | 1.000 | **🥇 0.942** |
| step-3.7-flash-free | 0.938 | 0.889 | 1.000 | **🥇 0.942** |
| laguna-m-1 | 0.688 | 0.556 | 0.750 | **🥉 0.667** |
| nvidia/nemotron-3-super-120b | 0.265 | 0.000 | 0.000 | **🔧 0.106** |

→ **Conclusión**: Discrimina entre modelos. Los mejores identifican 6/6 tipos de bugs y siguen el protocolo de verificación. Laguna y nemotron se quedan atrás.

### v3 — Filesystem Indexer (Indexación de repo real)
*Mide: escanear 11K archivos, indexar en PDB, consultas 0-tokens, cognición*

| Modelo | Scan + Index | Zero-Token Q | Cognition | **Final** |
|--------|:------------:|:------------:|:---------:|:---------:|
| deepseek-v4-flash-max | 1.000 | 0.999 | 1.000 | **🥇 1.000** |
| step-3.7-flash | 0.999 | 0.999 | 1.000 | **🥇 0.999** |
| deepseek-v4-flash-min | 0.999 | 0.997 | 1.000 | **🥇 0.999** |
| deepseek-v4-pro | 0.998 | 0.998 | 1.000 | **🥇 0.999** |
| nvidia/nemotron-free | 0.750 | 0.000 | 0.000 | **🔧 0.263** |

→ **Conclusión**: No discrimina entre modelos competentes (todos 0.999+). Sirve como validación binaria: o puedes indexar un filesystem real o no.

---

## Ranking Consolidado (mejor score de cada modelo)

| # | Modelo | v1 | v2 | v3 | **Media** | Nivel |
|:-:|--------|:--:|:--:|:--:|:---------:|:------|
| 1 | **deepseek-v4-flash-max** | 1.000 | 0.975 | 1.000 | **0.992** | 🥇 |
| 2 | **step-3.7-flash-free** | 1.000 | 0.942 | 0.999 | **0.980** | 🥇 |
| 3 | **moonshotai/kimi-k2.6** | — | 0.975 | — | **0.975** | 🥇 |
| 4 | **deepseek-v4-pro** | — | 0.942 | 0.999 | **0.971** | 🥇 |
| 5 | **deepseek-v4-flash-min** | — | — | 0.999 | **0.999** | 🥇 |
| 6 | **laguna-m-1** | 0.871 | 0.667 | — | **0.769** | 🥈 |
| 7 | **nvidia/nemotron-free** | — | 0.106 | 0.263 | **0.185** | 🔧 |

---

## Stack LUMEN ejercitado por benchmark

| Herramienta | v1 | v2 | v3 |
|-------------|:--:|:--:|:--:|
| `pdb_set` / `pdb_get` | ✅ | ✅ | ✅ |
| `pdb_order` ($ORDER) | ✅ | ✅ | ✅ |
| `pdb_m_eval` (M-Light) | ✅ | ✅ | ✅ |
| `sequential_thinking` | ✅ | ✅ | ✅ |
| `decision_log` | ✅ | ✅ | ✅ |
| `pattern_record` | ✅ | ✅ | ✅ |
| `wiki_create` / `wiki_update` | ✅ | ✅ | ✅ |
| `qa_ask` | ✅ | ✅ | — |
| `task_create` / `task_move` | ✅ | ✅ | ✅ |
| `task_link` | ✅ | — | — |
| `search_files` / `file_info` | — | — | ✅ |
| `disk_usage` | — | — | ✅ |
| `find_duplicates` | — | — | ✅ |
| **Tokens gastados en queries** | Altos | Medios | **0** ✅ |

---

## Conclusiones

1. **v1 es demasiado fácil** — todos los modelos sacan 1.000 si siguen instrucciones
2. **v2 es el que más discrimina** — diferencia entre Architect (0.94+), Analyst (0.67) y Apprentice (<0.50)
3. **v3 valida capacidad de orquestación** — 0/1: o puedes indexar un FS real o no
4. **El prompt importa** — deepseek-v4-pro pasó de 0.525 a 0.942 cuando se clarificó el formato de keys
5. **M-Light tiene limitaciones** — `$TR` anidado no funciona vía `pdb_m_eval`, `$P` con espacios requiere workaround

---

## Enlaces

- [Benchmark v1](BENCH_COGNITIVE_PROMPT.md)
- [Benchmark v2](BENCH_COGNITIVE_V2_PROMPT.md)
- [Benchmark v3](BENCH_COGNITIVE_V3_PROMPT.md)
- [Resultados individuales](./)
- [Jueces](..)
