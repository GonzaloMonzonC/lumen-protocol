# 🏋️ LUMEN Raw Speed — Local Benchmark (bench.py)

**Date**: 2026-06-27  
**Script**: `bench.py`  
**Purpose**: Measure raw PDB + M-Light throughput running directly on local CPU.  
**Important**: This does NOT measure LLM model intelligence. It measures local LUMEN infrastructure speed.

---

## 📐 What each KPI measures

| KPI | Description | Layer |
|-----|-------------|-------|
| **SET_s** | PDB writes/s — 100 iterations of `pdb_tools.tool_set()` | PDB (SQLite B-tree) |
| **GET_s** | PDB reads/s — 100 iterations of `pdb_tools.tool_get()` | PDB (SQLite B-tree) |
| **M_SET_s** | M-Light SETs/s — 50 iterations of `m.eval('S ^G(n)=v')` | M-Light + PDB |
| **M_GET_s** | M-Light GETs/s — 50 iterations of `m.eval_expr('$G(^G(n))')` | M-Light + PDB |
| **M_EXPR_s** | M expressions/s — 40 evaluations of `$L`, `$P`, `$TR`, `$C` | M-Light pure (no I/O) |
| **F_LOOP_ms** | $ORDER traversal — F loop over 100 nodes via `$O(^G(I))` | M-Light + PDB |

---

## 📊 Results by model (8 models)

| Model | SET_s | GET_s | M_SET_s | M_GET_s | M_EXPR_s | F_LOOP_ms |
|-------|:-----:|:-----:|:-------:|:-------:|:--------:|:---------:|
| **ds-v4pro-max** | 115 | 6,712 | 106 | 23,605 | 26,539 | 11,287.7 |
| **stepfun/step-3.7-flash** | 115 | 7,418 | 1,464 | 38,165 | 27,986 | 11,481.1 |
| **nemotron-3-super-120b** | 119 | 10,459 | 2,530 | 45,679 | 33,272 | 9,302.5 |
| **qwen-3-7-max** | 124 | 10,004 | **2,976** | 61,185 | 70,922 | **8,330.2** |
| **laguna-m1-free** | 124 | **11,359** | 2,447 | **65,325** | **74,752** | 8,823.2 |
| **deepseek-v4-pro** | 125 | 9,585 | 2,383 | 47,290 | 70,348 | 8,657.7 |
| **deepseek-v4-flash-max** | 127 | 10,859 | 2,657 | 60,140 | 69,444 | 8,751.4 |
| **claude-sonnet-4-6** | **130** | **12,784** | 2,761 | 38,168 | 36,755 | 8,388.8 |

---

## 🏆 KPI Rankings

| KPI | 🥇 1st | 🥈 2nd | 🥉 3rd |
|-----|--------|--------|--------|
| **SET_s** | claude-sonnet-4-6 (130) | ds-v4-flash-max (127) | ds-v4-pro (125) |
| **GET_s** | claude-sonnet-4-6 (12,784) | laguna-m1-free (11,359) | ds-v4-flash-max (10,859) |
| **M_SET_s** | qwen-3-7-max (2,976) | claude-sonnet-4-6 (2,761) | ds-v4-flash-max (2,657) |
| **M_GET_s** | laguna-m1-free (65,325) | qwen-3-7-max (61,185) | ds-v4-flash-max (60,140) |
| **M_EXPR_s** | laguna-m1-free (74,752) | ds-v4-pro (70,348) | qwen-3-7-max (70,922) |
| **F_LOOP_ms** | qwen-3-7-max (8,330.2) | claude-sonnet-4-6 (8,388.8) | ds-v4-pro (8,657.7) |

---

## 🏆 Wins per model

| Model | KPIs won | Where |
|-------|:--------:|-------|
| **laguna-m1-free** | 2 | M_GET_s, M_EXPR_s |
| **claude-sonnet-4-6** | 2 | SET_s, GET_s |
| **qwen-3-7-max** | 2 | M_SET_s, F_LOOP_ms |

*Note: qwen also wins 2*  

---

## 🔬 Observations

### Stability
- **SET_s** is the most stable KPI (±4%): range 115–130 across all models
- **GET_s** varies 2× between slowest and fastest
- **M_SET_s** is the most volatile: ds-v4pro-max does 106/s, qwen does 2,976/s (28× difference)
- **M_EXPR_s** and **M_GET_s** also vary significantly per model

### Patterns
- Models fastest at SET_s (claude, ds-flash) are NOT the fastest at M-Light
- laguna-m1-free dominates pure M-Light (M_GET_s, M_EXPR_s) but is middling on raw SET/GET
- qwen-3-7-max is king of M_SET_s and F_LOOP — the best $ORDER traversal
- ds-v4pro-max is slowest across the board — 7th/8th in 5 out of 6 KPIs

---

## 💾 Raw data in PDB

All results are stored in `^BENCH(model, metric)` in `lumen-pdb.db`.

```m
$O(^BENCH(""))           → lists all models
$G(^BENCH("qwen-3-7-max","SET_s")) → 124
$G(^BENCH("claude-sonnet-4-6","GET_s")) → 12784
```

To view the live report:
```bash
cd implementations/mcp-servers/pdb
python bench.py --report
```

---

## ⚠️ Limitations

1. **Runs on local CPU** — does not measure the LLM model, only the hardware
2. **Run-to-run variability**: SQLite cache, system load, fragmentation
3. **Single run per model** — no quality control
4. **Does NOT measure**:
   - Model intelligence
   - Accuracy in using LUMEN tools
   - Network / provider latency
   - Data structure quality

---

*Baseline benchmark for the LUMEN cognitive benchmark (next phase).*
