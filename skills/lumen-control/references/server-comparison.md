# Servers LUMEN — Comparativa completa (18/06/2026)

## 3 servidores, 18 tools

| Server | Tools | Wire Savings | Latency Overhead | Multi-agent | Unique Features |
|--------|-------|-------------|-----------------|-------------|-----------------|
| **Filesystem** | 9 | 32-70% | +0.3ms/op | ✅ | `read_files` (bulk), `search_with_context` (±N lines), `stream_read` (chunks), `server_stats` (health) |
| **Web** | 2 | 40-50% | ~200ms | ✅ | Search+extract unified, zero API keys, DuckDuckGo+stdlib |
| **Thinking** | 7 | 60-80% | 0.1ms/thought | ✅ | Sequential reasoning, TF-IDF similarity, contradiction detection, chain→plan |

## Filesystem tools (9)

| Tool | Hermes Built-in | LUMEN | Wire | LUMEN Only? |
|------|----------------|-------|------|-------------|
| `read_file` | ✅ 0.16ms | ✅ 0.42ms | 32-50% | No |
| `read_files` | ❌ | ✅ 0.9ms | 40-60% | **Sí 🔥** |
| `write_file` | ✅ <1ms | ✅ 0.8ms | 36% | No |
| `search_files` | ✅ 13.8ms | ✅ 2.2ms ⚡ | 50% | No (but faster +output_mode) |
| `search_with_context` | ❌ | ✅ 1.4ms | 50-60% | **Sí 🔥** |
| `list_directory` | ❌ | ✅ 0.9ms | 23% | **Sí 🔥** |
| `stream_read` | ❌ | ✅ ~1ms | 50-60% | **Sí 🔥** |
| `server_stats` | ❌ | ✅ <0.1ms | 40-50% | **Sí 🔥** |
| `patch` | ✅ 0.5ms | ✅ 9.5ms | 29% | No |

## Web tools (2)

| Tool | Hermes (Firecrawl) | LUMEN | Verdict |
|------|-------------------|-------|---------|
| `web_search` | Professional quality, subscription | Free, DuckDuckGo, search+extract unified | Complementary |
| `web_extract` | AI-powered markdown | HTML→text, stdlib | Hermes better for quality, LUMEN for speed+free |

## Thinking tools (7) — All LUMEN-exclusive 🔥

| Tool | Latency | Wire | Use Case |
|------|---------|------|----------|
| `sequential_thinking` | 0.1ms/op | 60-80% | Complex multi-step problems |
| `thought_similarity` | <1ms | 50-70% | Avoid redundant thoughts |
| `thought_contradiction` | <1ms | 40-60% | Detect inconsistent reasoning |
| `thought_summarize` | 15ms (30 thoughts) | 55-75% | Condense long chains |
| `thought_to_plan` | <1ms | 50-70% | Convert reasoning to action |
| `thought_evaluate` | <1ms | 40-60% | Score thought quality /10 |
| `thought_bridge` | <1ms | 40-60% | Cross-session knowledge |

## LUMEN Transport (protocol wire savings)

| Operation | JSON-RPC | LUMEN | Savings |
|-----------|----------|-------|---------|
| `tools/list` (4 tools) | 1128 B | 581 B | **48%** |
| `tool call` (echo) | 118 B | 61 B | **48%** |
| `error response` | 169 B | 102 B | **40%** |
| `agent loop` (30 turns) | 2669 B | 1334 B | **50%** |

## Key Insight: LUMEN compresses STRUCTURE, not content

- **40-80% savings** on structural data (tool schemas, RPC framing, thought metadata, search result metadata)
- **1-7% savings** on content-heavy data (file contents, web page text)
- **The real value** for content-heavy tools is multi-agent (5 agents → 1 server), not wire compression
