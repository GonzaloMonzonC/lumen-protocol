# LUMEN Benchmarks Consolidados

> **Fecha**: 2026-06-19
> **Transport**: LUMEN Level 2 — Shared Memory (mmap ring buffers)
> **Referencia**: `docs/benchmarks/internal/thinking-deep-benchmark-2026-06-19.md`, `docs/benchmarks/internal/filesystem-lumen-vs-hermes-2026-06-19.md`

---

## 🧠 Thinking Server — 32 tools

| Métrica | Valor |
|---------|-------|
| Total calls | 250 |
| Errores | 0 (0.00%) |
| Throughput | **3,407 calls/sec** |
| Latencia avg | **0.29ms** |
| Latencia p99 | <1ms |
| Cross-chain ops | 6/6 funcional |
| Pattern match (Jaccard) | 18-38% |
| Contradiction detection | Sentiment-aware (EN+ES) |
| model_scan speedup | 2,375× (19s → 8ms) |
| Wire savings | 10-59% (avg 29%) |
| Server spawn time | ~150ms |

### Per-Tool Thinking Latency (muestra)

| Tool | Latency | Wire Savings |
|------|---------|-------------|
| sequential_thinking | 0.3ms | 60-80% |
| thought_evaluate | 0.2ms | 40-60% |
| thought_contradiction | 0.4ms | 40-60% |
| thought_similarity | 0.5ms | 50-70% |
| model_add | 0.2ms | 30-50% |
| model_query | 0.2ms | 25-40% |
| pattern_record | 0.2ms | 30-50% |
| pattern_match | 1.1ms | 25-40% |
| agent_message 🆕 | ~0.3ms | — |
| agent_inbox 🆕 | ~0.3ms | — |
| collision_check 🆕 | ~0.5ms | — |

---

## 📁 Filesystem Server — 13 tools

### vs Hermes Built-in

| Tool | LUMEN SHM | Hermes (terminal) | Ratio | Wire |
|------|-----------|-------------------|-------|------|
| read_file | 1.7ms | 30ms (head) | **17.5×** | 6% |
| search_files | 4.2ms | 43ms (grep) | **10.4×** | 5% |
| patch | 4.5ms | 27ms (sed) | **5.9×** | 33% |
| read_files (bulk) | 3.2ms | 58ms (2 calls) | **18.1×** | 6% |
| stream_read | 1.1ms | 29ms (head) | **26.8×** | 14% |
| search_filename | 2.1ms | 41ms (find+grep) | **19.8×** | 21% |
| search_with_context | 5.6ms | 33ms (grep -C) | 5.9× | 10% |
| write_file | 8.0ms | 28ms (echo) | 3.5× | 38% |
| **PROMEDIO** | **4.1ms** | **33ms** | **9×** | **19%** |

### Cost Savings (per 1000 calls)
- Tiempo: **33s → 4.1s** = 29s ahorrados
- Wire: **100KB → 81KB** = 19% menos tokens

---

## 🌐 Web Server — 2 tools

| Tool | Latency | Notes |
|------|---------|-------|
| web_search | 49-260ms | Search + extract unificados, zero API keys |
| web_extract | 30-80ms | Zero-copy, multi-agent cache |

---

## 🔥 Cognitive Burst (200 ops mixtas)

| Métrica | Valor |
|---------|-------|
| Total time | 59ms |
| Avg latency | 0.29ms |
| Throughput | 3,407 calls/sec |
| Errors | 0 |

---

## 🚀 SHM Transport — Métricas de Infraestructura

| Métrica | Valor |
|---------|-------|
| Transport errors | 0 |
| Timeouts | 0 |
| Kernel copies | **0** (zero-copy mmap) |
| Avg cognitive latency | 0.29ms |
| Max cognitive throughput | 3,662 calls/sec |
| Server spawn time | ~150ms |
| Warm connection latency | 0.00s |
| SHM region | 1-8 MiB |
| MAX_SPIN | 50M |
| Ring buffer type | Lock-free SPSC |

---

## 📊 Cross-Session Cognition — Benchmarks

| Feature | Latencia | Notas |
|---------|----------|-------|
| agent_message → agent_inbox | ~0.6ms total | Label resolution + session_id matching |
| collision_check (5-min window) | ~0.5ms | File touches scan |
| global pattern_match cross-session | ~1.1ms | Jaccard 18-42% (EN+ES queries) |
| Model entity CRUD via HTTP | ~2ms | POST /model → GET /model?entity=X |
| State persistence (save) | ~5ms | Atomic write every 10 tool calls |

---

## 🔬 Metodología

- **Hardware**: Windows 10, i7, 32GB RAM
- **Transport**: LUMEN SHM Level 2 (mmap, 8 MiB buffer, MAX_SPIN=50M)
- **Server**: thinking/server_shm.py, filesystem/server_shm.py
- **Client**: Hermes Agent + lumen-shm-bridge plugin
- **Métrica**: Latencia end-to-end (client → SHM → server → SHM → client)
- **Cada benchmark**: 100-250 iteraciones, descartando warmup

---

## 📚 Referencias

- [Cognitive OS Architecture](COGNITIVE_OS.md)
- [Full Thinking Benchmark](benchmarks/internal/thinking-deep-benchmark-2026-06-19.md)
- [Filesystem vs Hermes](benchmarks/internal/filesystem-lumen-vs-hermes-2026-06-19.md)
