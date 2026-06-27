# Benchmark: Hermes Built-in vs LUMEN MCP Filesystem

Date: 2026-06-16 | Machine: Windows 10, Python 3.11, Node 22

## Raw Results (14 tests, 6 categories)

### Concurrency
- ✅ 50 simultaneous reads (same file): all correct, no corruption
- ✅ 30 interleaved writes+reads: all data intact

### Edge Cases
- ✅ Special chars in paths (`!@#`)
- ✅ Unicode + spaces (`cañón español`)
- ✅ Directory rejected as file
- ✅ File not found → proper error message
- ✅ Invalid regex → proper error message
- ✅ File search with glob pattern
- ✅ Patch: "not found" detection
- ✅ Patch: multiple occurrences without replace_all

### Stress
- ✅ 100 consecutive reads: avg 0.5ms, no degradation (-50% last vs first)
- ✅ 100 writes + random verify: all data intact

### Recovery
- ✅ Kill server + respawn: data survives, reconnection works

### Latency (sequential, fair comparison)
```
  Operation             OS Direct  LUMEN MCP   Overhead
  read_file (100 lines)   0.16ms     0.42ms    +0.25ms
  write_file                  —      0.82ms         —
  search_files                —      1.25ms         —
```

### Multi-Agent
- ✅ 5 agents × 20 operations each: 38ms total, all data intact

## Wire Savings (real measurements)

| Payload | JSON-RPC | LUMEN | Savings | Why |
|---------|----------|-------|---------|-----|
| `tools/list` (4 tools) | 1128 B | 581 B | **48%** | Structural keys compress well |
| `tool call` (echo) | 118 B | 61 B | **48%** | Small payload, structure dominates |
| `error response` | 169 B | 102 B | **40%** | Error keys in dictionary |
| `agent loop` (30 turns) | 2669 B | 1334 B | **50%** | Pure structure |
| `read_file` (500 lines) | 12584 B | 12029 B | **4%** | ⚠️ Content dominates |

**Key insight:** LUMEN compresses JSON *structure*, not file *content*.
For read_file/write_file, the wire savings are modest. The real benefit
is multi-agent (N agents → 1 server), streaming, and Macaroon security.

## Overhead

- Per operation: ~0.3ms (imperceptible vs 500-5000ms LLM latency)
- Per turn (100 ops): ~25ms extra
- MCP stdio is NOT thread-safe: concurrent writes corrupt JSON-RPC framing
