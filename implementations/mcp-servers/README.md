# LUMEN MCP Servers

**Experimental MCP server demos** using LUMEN binary protocol for transport compression.

⚠️ **Status: Alpha/Demo** — Not production-ready. Sandboxing, session isolation, and
reproducible benchmarks are still being built. These servers demonstrate the concept
of binary transport for MCP, but should be used with caution and explicit configuration.

Each server demonstrates how LUMEN reduces MCP wire overhead through Hyb128 encoding
and dictionary compression. Two transport modes are provided:

- **`server.py`** — Standard JSON-RPC over stdio, with LUMEN wrapping at transport layer.
  Compatible with any MCP client that supports `transport: lumen`.
- **`server_native.py`** — LUMEN binary frames directly (no JSON-RPC wrapping).
  Requires LUMEN-aware client. **Currently experimental — frame parser and handshake still being hardened.**

## Servers

| Server | Tools | Key Features |
|--------|-------|--------------|
| **[Filesystem](filesystem/)** | 9 | `read_files` (bulk), `search_with_context`, `stream_read`, `server_stats` |
| **[Web](web/)** | 2 | `web_search` + `web_extract` combined, zero API keys required |
| **[Thinking](thinking/)** | 22 | Sequential reasoning chains, TF-IDF similarity, contradiction detection, assumptions, project mental model, work tracking |

**33 tools across 3 servers. Standard library only — no external dependencies.**

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

> ⚠️ **Pending** — Reproducible benchmarks are being built.  
> Current numbers in this README are illustrative only.
> Run `python benchmarks/mcp_servers/run.py` when available.
> See [plan-mcp.md](../temp/plan-mcp.md) for scope.

## Architecture

```
Hermes Agent                     MCP Server (this repo)
    │                                    │
    │  LUMEN binary frames               │
    │  ═════════════════════════►         │
    │  Hyb128 + dict compression          │  ──► OS / filesystem / web / AI
    │  Frame types: REQUEST/RESPONSE     │
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
