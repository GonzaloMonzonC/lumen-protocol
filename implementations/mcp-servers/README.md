# LUMEN MCP Servers

Reference implementations of MCP servers using the LUMEN binary protocol.

Each server demonstrates how to build an MCP server that speaks LUMEN natively
(via `server_native.py`) or with the LUMEN transport wrapper (`server.py`).

## Available Servers

| Server | Tools | Transport | Wire Savings |
|--------|-------|-----------|-------------|
| [filesystem](./filesystem/) | read_file, write_file, search_files, search_with_context, patch, list_directory, read_files | LUMEN native + JSON-RPC wrapper | 32-70% |

## Using with Hermes Agent

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
```

## Architecture

```
Hermes Agent                    MCP Server (this repo)
    │                                    │
    │  LUMEN binary frames               │
    │  ═════════════════════════►         │
    │  40-70% wire savings               │  ──► OS / filesystem / web
    │  MUX channels (native)             │
    │  STREAM_DATA (native)              │
```

## Creating a New Server

1. Copy `filesystem/server_native.py` as a template
2. Replace the tool schemas and handlers
3. The LUMEN transport layer is already handled by `read_lumen_frame()` / `send_lumen_frame()`
4. Add a `server.py` wrapper for JSON-RPC fallback support
