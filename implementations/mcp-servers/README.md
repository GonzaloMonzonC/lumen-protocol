# LUMEN MCP Servers

Reference implementations of MCP servers using the LUMEN binary protocol.

Each server demonstrates how to build an MCP server that speaks LUMEN.  
Two transport modes available:

- **`server.py`** — JSON-RPC + LUMEN wrapper (32-60% wire savings). Works with any MCP client.
- **`server_native.py`** — LUMEN native binary (50-80% wire savings). Requires LUMEN-aware client.

## Servers

| Server | Tools | Wire Savings | Multi-Agent | Unique Features |
|--------|-------|-------------|-------------|-----------------|
| **[Filesystem](filesystem/)** | 9 | 32-70% | ✅ | `read_files` (bulk), `search_with_context`, `stream_read`, `server_stats` |
| **[Web](web/)** | 2 | 40-50% | ✅ | `web_search` + `web_extract` in 1 call, zero API keys |
| **[Thinking](thinking/)** | 7 | 60-80% | ✅ | Sequential reasoning, TF-IDF similarity, contradiction detection, chain→plan |

**18 tools across 3 servers. Zero external dependencies (stdlib only).**

## Quick Start

```bash
# Any server — just run it
python implementations/mcp-servers/filesystem/server.py
python implementations/mcp-servers/web/server.py
python implementations/mcp-servers/thinking/server.py
```

## Hermes Agent Config

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
    lumen_force_json_rpc: true

  lumen_web:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/web/server.py"]
    transport: lumen
    lumen_force_json_rpc: true

  lumen_thinking:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/thinking/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

## Benchmarks

Benchmarked against Hermes Agent built-in equivalents. Same machine, same operations.

| Tool | Hermes Built-in | LUMEN MCP | Overhead | Wire Savings |
|------|----------------|-----------|----------|-------------|
| `read_file` (100 lines) | 0.16ms | 0.42ms | +0.26ms | 32-50% |
| `search_files` | 13.8ms | 2.2ms | -11.5ms ⚡ | 50% |
| `list_directory` (80 files) | 9.7ms | 12.7ms | +3.0ms | 23% |
| `tools/list` (4 tools) | N/A | 1128→581B | N/A | 48% |
| `sequential_thinking` (30 thoughts) | ❌ | 0.1ms/op | N/A | 60-80% |

> **Average LUMEN overhead: +0.3ms/op** — imperceptible vs 500-5000ms LLM latency.

## Architecture

```
Hermes Agent                     MCP Server (this repo)
    │                                    │
    │  LUMEN binary frames               │
    │  ═════════════════════════►         │
    │  32-80% wire savings               │  ──► OS / filesystem / web / AI
    │  MUX channels (native)             │
    │  STREAM_DATA (native)              │
```

## Creating a New Server

1. Copy `filesystem/server.py` as template
2. Replace `TOOLS` list with your tool schemas
3. Replace `HANDLERS` dict with your implementations
4. Optionally add `server_native.py` for LUMEN binary transport
5. Test: `python test_suite.py` (if provided)

Template code for LUMEN frames is provided by:
- `build_frame()` / `parse_frame()` from `lumen` Python package
- `read_lumen_frame()` / `send_lumen_frame()` in `server_native.py`
