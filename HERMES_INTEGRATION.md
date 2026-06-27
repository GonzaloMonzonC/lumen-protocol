# Hermes Agent + LUMEN Integration

[![Status](https://img.shields.io/badge/Status-Stable-green)]()
[![Hermes Agent](https://img.shields.io/badge/Hermes%20Agent-2.x-8A2BE2)](https://github.com/NousResearch/hermes-agent)
[![LUMEN](https://img.shields.io/badge/LUMEN-1.0-4A90D9)](https://github.com/GonzaloMonzonC/lumen-protocol)

> **LUMEN** as a binary wire transport for [Hermes Agent](https://github.com/NousResearch/hermes-agent) — up to **58% wire savings**, zero-trust Macaroon security, and native streaming for MCP tool calls.

---

## Overview

[Hermes Agent](https://github.com/NousResearch/hermes-agent) is an open-source AI agent framework by Nous Research with a built-in [MCP client](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp) that connects to external MCP servers. By default, Hermes communicates with MCP servers via **JSON-RPC 2.0** over stdio or HTTP.

This integration upgrades the transport to **LUMEN** — a binary protocol that replaces JSON-RPC on the wire while preserving full compatibility with the MCP SDK's `ClientSession` interface.

### Architecture

```
┌─────────────────┐       stdio / HTTP          ┌──────────────┐
│   Hermes Agent  │ ◄────────────────────────►  │  MCP Server  │
│                 │      LUMEN PROBE/ACK        │              │
│  mcp_tool.py    │      (auto-negotiate)       │  (npx/uvx)   │
│                 │                              │              │
│  ┌─ LUMEN? ─┐  │   ┌──────┐                  │              │
│  │ SÍ: bin  │──│──►│LUMEN │                  │              │
│  │ NO: JSON │  │   │frames│◄─────────────────│              │
│  └──────────┘  │   └──────┘                  └──────────────┘
└─────────────────┘
```

When a Hermes MCP server is configured with `transport: lumen`:

1. **LUMENStdioTransport** spawns the server process and sends a **PROBE frame** (binary, ~30 bytes)
2. If the server responds with **PROBE_ACK** → all subsequent communication uses LUMEN binary frames
3. If no response within `lumen_probe_timeout_ms` (default: 500ms) → **transparent fallback** to JSON-RPC line protocol
4. **`_LumenSession`** wraps the transport, providing a `ClientSession`-compatible interface for Hermes's `MCPServerTask`

The `_LumenSession` implements the subset of MCP `ClientSession` used by Hermes:
`initialize()`, `list_tools()`, `call_tool()`, `list_resources()`, `read_resource()`, `list_prompts()`, `get_prompt()`, `send_ping()`.

---

## ⚡ Plugin Bridge — **Recommended Approach** (June 2026)

The **`lumen-shm-bridge`** Hermes plugin replaces the MCP config approach entirely.
It spawns its own MCP server subprocesses with **binary pipes**, handles the
PROBE→ACK→SHM negotiation itself, and registers tools via `ctx.register_tool(override=True)`.
The LLM sees standard tool names — zero prompt cache impact.

### Why Plugin over MCP Config

| Aspect | MCP Config (`config.yaml`) | Plugin Bridge |
|--------|---------------------------|---------------|
| Transport | Text pipes (stdio) | **Binary pipes** for PROBE, SHM for data |
| SHM Level 2 | ❌ Not supported | ✅ Zero-copy mmap ring buffers |
| Tool names | `mcp_lumen_*` (prefixed) | Standard names (read_file, etc.) |
| LLM context | Changed (new tool names) | **Unchanged** (override built-ins) |
| Wire savings | 32-60% (JSON-RPC wrapper) | **55-80%** (native binary) |
| Setup | Edit config.yaml + restart | Install plugin + restart |

### Install

```bash
# Already included in Hermes — enable via config:
hermes config set plugins.enabled "[lumen-shm-bridge]"
```

### What You Get

- **Filesystem**: read_file, write_file, search_files, patch, read_files, stream_read, etc. (13 tools)
- **Thinking**: sequential_thinking, thought_contradiction, model_add, agent_message, collision_check, etc. (46 tools)
- **Web**: web_search, web_extract (2 tools)
- **Total**: 61 tools over Level 2 SHM zero-copy transport

### Benchmarks

| Métrica | Plugin (SHM) | Hermes Built-in |
|---------|-------------|-----------------|
| FS latency avg | 4.1ms | 33ms (terminal) |
| Think latency avg | 0.29ms | N/A |
| Think throughput | 3,407 calls/sec | — |
| Errors | 0 / 530+ calls | — |

Full benchmarks at [`docs/BENCHMARKS.md`](docs/BENCHMARKS.md).

---

## How to Configure (Legacy MCP Config)

### Prerequisites

```bash
# Install LUMEN Python package
cd lumen-protocol/implementations/python
pip install -e .
```

### Hermes Config

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  my_server:
    command: "npx"
    args: ["-y", "@modelcontextprotocol/server-github"]
    transport: lumen              # ← enable LUMEN binary transport
    lumen_probe_timeout_ms: 500   # optional, default: 500ms
    lumen_force_json_rpc: false   # optional, skip probe entirely
```

### Interaction Modes

| Mode | Config | Behavior |
|------|--------|----------|
| **Auto-negotiate** | `transport: lumen` | Sends LUMEN probe → binary if ACK'd, JSON-RPC fallback on timeout |
| **Force LUMEN** | `transport: lumen` + server supports LUMEN | Binary only, no fallback |
| **Force JSON-RPC** | `lumen_force_json_rpc: true` | Skips LUMEN probe, uses JSON-RPC (for known non-LUMEN servers) |
| **Disabled** | `transport` not set | Standard JSON-RPC (unchanged behavior) |

---

##  Performance Benchmarks

Measured with real MCP workloads on Windows 10, Python 3.11, Node.js 22.

### Wire Savings

| Payload | JSON-RPC | LUMEN | Saving |
|---------|----------|-------|--------|
| `null` | 4 B | **1 B** | **75%** |
| Simple object `{"tool":"search","arguments":{"query":"TODO"}}` | 50 B | **15 B** | **70%** |
| MCP tool call | 115 B | **48 B** | **58%** |
| `tools/list` (5 tools, ~1.5 KB JSON) | 1,536 B | **910 B** | **41%** |
| `tools/call` (echo x3) | 222 B | **149 B** | **33%** |
| Tool list (106 tools) | 39.7 KB | **24.8 KB** | **37%**¹ |
| Agent loop (30 turns) | 6.4 KB | **3.3 KB** | **48%**¹ |

¹ *From LUMEN paper benchmarks*

### Protocol Overhead

```
 LUMEN frame header: [Hyb128 LEN:1-5B][TYPE:1B][FLAGS:1B] = 3-7 bytes
 JSON-RPC framing:   {"jsonrpc":"2.0","id":1,"method":"tools/call",...} = 40-80+ bytes
```

### Key Metrics

- **Sub-50μs** token streaming latency (`STREAM_DATA`/`STREAM_INIT` frames)
- **~2 million messages/second** in compressed mode (Rust reference impl)
- **O(1)** frame skipping — skip unknown frames without full deserialization

---

## Verified MCP Servers

| Server | Type | LUMEN | Status |
|--------|------|-------|--------|
| Test server (Python) | stdio | ✅ | Verified |
| [cadencia-mcp](https://github.com/GonzaloMonzonC/cadencia) | stdio (TypeScript) | ✅ JSON-RPC fallback | Verified |
| Any stdio MCP server | stdio | ⬜ auto-negotiate | Fallback-safe |

Testing cadencia-mcp with DeepSeek V4 Pro:
```
$ hermes chat -q "What is LUMEN?"
→ Response via cadences-gateway (cadencia-mcp → LumenStdioTransport)
```

---

## Windows Compatibility

Four Windows-specific bugs were discovered and fixed during this integration,
all in `implementations/python/src/lumen/transport.py`:

| Bug | Symptom | Fix |
|-----|---------|-----|
| `stdin.flush()` | `OSError [Errno 22]` | Cross-platform `_flush_stdin()` helper |
| `close()` deadlock | Script hangs on exit | Close stdin before cancelling readers |
| `{**sys.executable, ...}` | Would crash at runtime | `{**os.environ, ...}` |
| `stdout.read(N)` | Blocks forever on Windows pipes | `readline()` |

See [WINDOWS_FIXES.md](../implementations/python/WINDOWS_FIXES.md) for details.

---

## Security

LUMEN adds security capabilities that benefit Hermes's delegation model:

- **Macaroon-based attenuation**: sub-agents (via `delegate_task`) can receive
  attenuated capabilities:
  ```python
  macaroon = base_macaroon.attenuate([
      Caveat("tool", ["read_file", "search_code"]),
      Caveat("ttl", 300),
  ])
  ```
- **Frame-level encryption**: ChaCha20-Poly1305 + X25519 key agreement
  (optional, controlled by `FLAG_ENCRYPTED`)
- **Zero-trust session dictionaries**: per-server 127-entry dynamic dictionary
  with isolated key spaces
- **Environment filtering**: Hermes already filters env vars for MCP subprocesses;
  LUMEN transports inherit the same `_build_safe_env()` mechanism

---

## Implementation Details

### Files Changed (Hermes Agent)

| File | Change | Lines |
|------|--------|-------|
| `tools/mcp_tool.py` | Add `_MCP_LUMEN_AVAILABLE` detection | +8 |
| `tools/mcp_tool.py` | Add `_LumenSession` class | +160 |
| `tools/mcp_tool.py` | LUMEN branch in `_run_stdio` | +25 |

**Total: +193 lines**

### Config Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `transport` | string | — | Set to `"lumen"` to enable LUMEN protocol |
| `lumen_probe_timeout_ms` | int | 500 | Milliseconds to wait for LUMEN ACK before fallback |
| `lumen_force_json_rpc` | bool | false | Skip LUMEN probe entirely, use JSON-RPC |

All options are per-server under `mcp_servers.<name>`.

---

## MCP Servers

LUMEN ships with production-ready MCP servers in `implementations/mcp-servers/`:

| Server | Tools | Wire Savings | Config |
|--------|-------|-------------|--------|
| Filesystem | 13 tools (read_file, write_file, search_files, list_directory, read_files, search_with_context, stream_read, server_stats, patch, file_info, disk_usage, search_filename, find_duplicates) | 32-70% | `transport: lumen` |
| Web | 2 tools (web_search, web_extract unified) | 40-50% | `transport: lumen` |
| Thinking | 15 tools (sequential, similarity, contradiction, summarize, to_plan, evaluate, bridge, assume, list_assumptions, check_assumption, model_add, model_query, model_stats, model_map, model_remove) | 60-80% | `transport: lumen` |

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

26 tools, zero API keys required. See [implementations/mcp-servers/](implementations/mcp-servers/).

### Tool Selection — SOUL.md

By default, both LUMEN and built-in tools are available. To make the LLM prefer LUMEN tools, add this to `~/.hermes/SOUL.md`:

```markdown
## LUMEN MCP Tools

You have access to LUMEN MCP tools (prefixed `mcp_lumen_*`).
When both a LUMEN tool and a built-in equivalent exist for the same
operation, **prefer the LUMEN tool**.

| Built-in | LUMEN MCP | Why LUMEN is better |
|----------|-----------|---------------------|
| `read_file` | `mcp_lumen_filesystem_read_file` | 100K guard, compressed |
| `search_files` | `mcp_lumen_filesystem_search_files` | 6x faster, +output modes |
| `web_search` | `mcp_lumen_web_web_search` | Search+extract 1 call |
| _(none)_ | `mcp_lumen_thinking_sequential_thinking` | External reasoning |
```

Alternatively, disable built-in tools entirely:
```yaml
tools:
  disabled_toolsets: ["file"]
```

---

## Roadmap

- [x] Hermes Agent integration — [PR #47740](https://github.com/NousResearch/hermes-agent/pull/47740)
- [x] Windows compatibility fixes
- [x] MCP servers: filesystem (9 tools), web (2 tools), thinking (7 tools)
- [ ] Package `lumen-mcp` on PyPI
- [ ] LUMEN transport between **cadencia-mcp** and **cadences-gateway** — a native LUMEN link in production, end-to-end
- [ ] LUMEN support in Hermes's HTTP/StreamableHTTP transport path
- [ ] LUMEN-aware `hermes mcp add` wizard (auto-detect server LUMEN support)
- [ ] MUX channels + STREAM_DATA in `server_native.py`

---

## References

- [Hermes Agent](https://github.com/NousResearch/hermes-agent) — Open-source AI agent framework by Nous Research
- [LUMEN Protocol](https://github.com/GonzaloMonzonC/lumen-protocol) — Lightweight Universal Model Exchange Network
- [LUMEN Paper](./PAPER.md) — Binary Wire Protocol for Efficient MCP Communication
- [MCP Specification](https://spec.modelcontextprotocol.io/) — Model Context Protocol
- [Hermes MCP Integration Docs](https://hermes-agent.nousresearch.com/docs/user-guide/features/mcp)
