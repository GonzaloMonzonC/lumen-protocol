# LUMEN Filesystem MCP Server

High-performance filesystem operations via MCP + LUMEN binary protocol.

## Quick Start

```bash
# JSON-RPC wrapper (works with any MCP client)
python server.py

# LUMEN native (50-70% wire savings, requires LUMEN-aware client)
python server_native.py
```

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read a file with line numbers and pagination |
| `read_files` | Bulk read — N files in 1 round-trip ✨ |
| `write_file` | Write content to a file |
| `search_files` | Search file contents with regex or find files by glob |
| `search_with_context` | Search with ±N context lines around matches ✨ |
| `list_directory` | List files and directories |
| `patch` | Targeted find-and-replace in files |

*✨ = features Hermes built-in tools don't have*

## Hermes Agent Config

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["server.py"]  # or server_native.py
    transport: lumen
```

## Benchmarks

| Server | Wire Savings | MUX | Streaming |
|--------|-------------|-----|-----------|
| `server.py` (JSON wrapper) | 32-60% | ❌ | ❌ |
| `server_native.py` (LUMEN native) | 50-70% | ✅ | ✅ |

## Test

```bash
# Inline roundtrip test (validates LUMEN native protocol)
python test_roundtrip.py
```

Expected output:
```
🔌 lumen-filesystem-native v2.0.0
📁 7 tools: ['read_file', 'read_files', 'write_file', ...]
  ✅ read_file
  ✅ write_file
  ...
🎯 7/7 PASSED
```
