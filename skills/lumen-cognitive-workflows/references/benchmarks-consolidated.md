# Benchmarks Consolidados — Condensed Reference

Full doc: `docs/BENCHMARKS.md` in lumen-protocol repo.

## Thinking Server (32 tools)
| Metric | Value |
|--------|-------|
| Total calls | 250 |
| Errors | 0 |
| Throughput | 3,407 calls/sec |
| Latency avg | 0.29ms |
| Latency p99 | <1ms |
| Pattern match (Jaccard) | 18-38% |
| Wire savings | 10-59% (avg 29%) |

## Filesystem vs Hermes Built-in
| Tool | LUMEN | Hermes | Ratio |
|------|-------|--------|-------|
| search_files | 4.2ms | 43ms (grep) | 10.4× |
| stream_read | 1.1ms | 29ms (head) | 26.8× |
| read_files (bulk) | 3.2ms | 58ms | 18.1× |
| search_filename | 2.1ms | 41ms (find+grep) | 19.8× |
| **AVG** | **4.1ms** | **33ms** | **9×** |

## SHM Transport
- Zero kernel copies (mmap ring buffers)
- Lock-free SPSC ring buffer
- 8 MiB buffer, MAX_SPIN=50M
- Server spawn: ~150ms
- Warm latency: 0.00s
