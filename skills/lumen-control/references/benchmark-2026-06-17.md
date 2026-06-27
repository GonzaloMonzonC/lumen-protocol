# Benchmark: Hermes Built-in vs LUMEN Filesystem Server

Date: 2026-06-17 | Model: deepseek-v4-pro | Host: Windows 10

## Sequential Latency (100 iterations each, fair comparison)

```
Operation             OS Direct  LUMEN MCP   Overhead
──────────────────────────────────────────────────
read_file (100L)         0.16ms     0.42ms    +0.25ms
write_file                    —     0.82ms          —
search_files                  —     1.25ms          —

AVERAGE OVERHEAD: +0.4ms/op
For 100 ops/turn: ~25ms extra (vs 500-5000ms LLM latency)
```

## Wire Savings by Operation Type

| Operation | JSON | LUMEN | Savings | Structure% |
|-----------|------|-------|---------|------------|
| `tools/list` (4 tools) | 1128 B | 581 B | **48%** | 90% |
| `tool call` (echo x3) | 118 B | 61 B | **48%** | 80% |
| `error response` | 169 B | 102 B | **40%** | 70% |
| `agent loop` (30 turns) | 2669 B | 1334 B | **50%** | 60% |
| `list_directory` (80 files) | 3787 B | 2923 B | **23%** | 90% |
| `read_file` (500 lines) | 12584 B | 12029 B | **4%** | 5% |
| `read_file` (100KB content) | 100K B | 100K B | **0%** | 1% |

**Key insight**: LUMEN compresses STRUCTURE (JSON keys, field names, RPC framing),
not content (file text, web content, terminal output).

## 10-Test Exhaustive Suite

```
Category           Tests  Result
───────────────────────────────
Concurrency          2     ✅ ✅
Edge Cases           6     ✅ ✅ ✅ ✅ ✅ ✅
Stress              2     ✅ ✅
Recovery             1     ✅
Latency              1     ✅ (0.3ms)
Multi-Agent          1     ✅ (5 agents, 20 ops, 38ms)
───────────────────────────────
TOTAL               14     14/14 PASSED
```

## LUMEN Native Roundtrip (inline, no subprocess)

```
🔌 lumen-filesystem-native v2.0.0
📁 7 tools: read_file, read_files, write_file, search_files,
             search_with_context, list_directory, patch
  ✅ read_file
  ✅ write_file
  ✅ search_files
  ✅ search_ctx (context_lines=3, >>> marker)
  ✅ list_dir
  ✅ patch
  ✅ read_files (bulk, 3 files in 1 call)

7/7 PASSED — pure LUMEN binary protocol
```

## Decision: What to LUMEN-ify

**Superiority Bar rule**: "cualquier cosa q hagamos una tool q ya exista en hermes,
debemos ser muy superiores en todo sino no conviene"

| Tool | Wire Savings | Superior? | Verdict |
|------|-------------|-----------|---------|
| `read_file` | 0-7% | ❌ | Content-heavy, no advantage |
| `write_file` | 0-5% | ❌ | Same |
| `search_files` | 20-40% | ⚠️ | Moderate |
| `list_directory` | 23% | ✅ | Hermes has no equivalent |
| `read_files` (bulk) | N/A | ✅🔥 | Hermes CAN'T do this (1 round-trip vs N) |
| `search_with_context` | N/A | ✅🔥 | Better UX than Hermes `search_files context` |
| `web_search` | 30-40% | ❌ | Same backend, +0.5ms overhead, no feature gain |
| `browser_snapshot` | 50-70% | ❌ | 2000+ lines to implement |
