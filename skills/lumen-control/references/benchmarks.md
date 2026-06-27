# LUMEN Ecosystem — Tools & Benchmarks
## Team Reference Card

### Servers Overview

| Server | Tools | Pattern | Wire Savings | Status |
|--------|-------|---------|-------------|--------|
| filesystem | 9 | JSON-RPC + Native | 32-70% | ✅ Production |
| web | 2 | JSON-RPC | 40-50% | ✅ Production |
| thinking | 23 | JSON-RPC | 60-80% | ✅ Production |
| **TOTAL** | **34** | | **32-80%** | |

### Filesystem Benchmarks vs Hermes Built-in

| Tool | Hermes | LUMEN | Delta | Wire Savings |
|------|--------|-------|-------|-------------|
| read_file | 0.2ms | 0.4ms | +0.3ms | 32-50% |
| read_files | ❌ | 0.9ms | N/A | 40-60% 🔥 |
| write_file | <1ms | 0.8ms | ~0ms | 36% |
| search_files | 13.8ms | 2.2ms | -11.5ms | 50% 🔥 |
| search_with_context | ❌ | 1.4ms | N/A | 50-60% 🔥 |
| list_directory | ❌ | 0.9ms | N/A | 23% 🔥 |
| patch | 0.5ms | 9.5ms | +9.0ms | 29% |

🔥 = Hermes doesn't have this tool

### Transport Wire Savings

| Operation | JSON-RPC | LUMEN | Savings |
|-----------|----------|-------|---------|
| tools/list (4 tools) | 1128B | 581B | 48% |
| tool call (echo) | 118B | 61B | 48% |
| error response | 169B | 102B | 40% |
| agent loop (30 turns) | 2669B | 1334B | 50% |

### Key Metrics

- Latency overhead: +0.3ms/op (imperceptible vs 500-5000ms LLM)
- Multi-agent: N agents → 1 server process
- Zero-cost web: DuckDuckGo + stdlib, no API key
### Native LUMEN Binary (NEW — 18/06/2026)

The native binary server (`server_native.py`) is now working on Windows after two fixes:

| Component | Issue | Fix |
|-----------|-------|-----|
| `transport.py:_wait_for_ack` | `read(4096)` blocks until EOF on Windows pipes | `read(1)` byte-at-a-time |
| `transport.py:_read_lumen` | `readline()` blocks on binary pipes | `read(1)` byte-at-a-time |
| `server_native.py` | No PROBE handler | Detect PROBE → respond with PROBE_ACK |

Wire savings: **50-80%** (no JSON wrapper, pure binary frames).
Configure: `lumen_force_json_rpc: false` (Hermes auto-negotiates via PROBE/ACK).

### Hermes Config

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: [".../lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
  lumen_web:
    command: "python"
    args: [".../lumen-protocol/implementations/mcp-servers/web/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
  lumen_thinking:
    command: "python"
    args: [".../lumen-protocol/implementations/mcp-servers/thinking/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

### Repos

- LUMEN protocol + servers: `GonzaloMonzonC/lumen-protocol`
- Cadencia apps: `GonzaloMonzonC/cadencIA`
- Hermes PR: `NousResearch/hermes-agent#47740`
