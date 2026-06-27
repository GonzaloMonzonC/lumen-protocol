# LUMEN Thinking — 29-Tool Benchmark (2026-06-19)

All 29 cognitive tools benchmarked over LUMEN Level 2 SHM transport (mmap ring buffers, 8 MiB).

| Tool | Avg Latency | Wire: JSON → LUMEN | Savings |
|---|---|---|---|
| `sequential_thinking` | 0.5ms | 457B → 386B | 16% |
| `thought_similarity` | 0.8ms | 344B → 286B | 17% |
| `thought_contradiction` | 0.7ms | 127B → 69B | 46% |
| `thought_summarize` | 0.8ms | 694B → 621B | 11% |
| `thought_to_plan` | 0.5ms | 737B → 649B | 12% |
| `thought_evaluate` | 0.5ms | 427B → 363B | 15% |
| `thought_bridge` | 0.8ms | 252B → 193B | 23% |
| `assume` | 0.3ms | 304B → 241B | 21% |
| `list_assumptions` | 0.4ms | 303B → 243B | 20% |
| `check_assumption` | 0.4ms | 97B → 49B | 49% |
| `model_add` | 0.3ms | 88B → 40B | 55% |
| `model_query` | 0.2ms | 89B → 41B | 54% |
| `model_stats` | 0.1ms | 98B → 40B | 59% |
| `model_map` | 0.2ms | 98B → 40B | 59% |
| `model_remove` | 0.2ms | 88B → 40B | 55% |
| `model_scan` | 19,123ms | 255B → 193B | 24% |
| `context_preserve` | 0.2ms | 208B → 148B | 29% |
| `context_check` | 0.2ms | 435B → 369B | 15% |
| `work_start` | 0.2ms | 88B → 40B | 55% |
| `work_block` | 0.2ms | 91B → 43B | 53% |
| `work_done` | 0.1ms | 91B → 43B | 53% |
| `work_log` | 0.4ms | 657B → 588B | 11% |
| `context_estimate` | 0.3ms | 257B → 197B | 23% |
| `session_init` | 0.2ms | 280B → 218B | 22% |
| `session_list` | 0.2ms | 317B → 258B | 19% |
| `pattern_record` | 0.2ms | 198B → 139B | 30% |
| `pattern_match` | 0.4ms | 362B → 300B | 17% |
| `decision_log` | 0.3ms | 93B → 45B | 52% |
| `decision_list` | 0.2ms | 155B → 99B | 36% |

**Avg latency**: 0.35ms (excl. model_scan outlier)  
**28/29 tools sub-ms**  
**Wire savings**: 11-59% (avg 33%)  
**Transport**: LUMEN Level 2 SHM — mmap ring buffers, zero kernel copies  
**⚠️ model_scan**: 19.1s — needs investigation (likely scans empty dataset with timeout)