# LUMEN + Hermes Agent — Installation Guide

> **Status**: ✅ Production-ready — 29 tools across 3 MCP servers.  
> **PR**: [NousResearch/hermes-agent#47740](https://github.com/NousResearch/hermes-agent/pull/47740)  
> **Native LUMEN binary**: ✅ Working on Windows, Mac, Linux

---

## Quick Install (2 minutes)

### 1. Clone the repo
```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol
```

### 2. Install LUMEN Python package
```bash
pip install -e implementations/python
```

### 3. Add MCP servers to Hermes config

Edit `~/.hermes/config.yaml` (Windows: `%APPDATA%/hermes/config.yaml`):

```yaml
mcp_lumen:
  enabled: true

mcp_servers:
  lumen_filesystem:
    command: "python"
    args:
      - "path/to/lumen-protocol/implementations/mcp-servers/filesystem/server.py"
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true

  lumen_web:
    command: "python"
    args:
      - "path/to/lumen-protocol/implementations/mcp-servers/web/server.py"
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true

  lumen_thinking:
    command: "python"
    args:
      - "path/to/lumen-protocol/implementations/mcp-servers/thinking/server.py"
    transport: lumen
    lumen_force_json_rpc: true
    enabled: true
```

### 4. Restart Hermes
```
/reset
```

### 5. Verify

After reset, the agent will show:
```
⚡ LUMEN tools active: filesystem (9), web (2), thinking (18) — 29 total
```

---

## What You Get

| Server | Tools | Wire Savings | Key Features |
|--------|-------|-------------|-------------|
| **Filesystem** | 9 | 32-70% | Bulk reads, context search, streaming, health metrics |
| **Web** | 2 | 40-50% | Search + extract in 1 call, no API key |
| **Thinking** | 18 | 60-80% | External reasoning, assumption tracker, mental model, context preservation |

---

## Native LUMEN Binary (50-80% wire savings)

For even more compression, use the native binary server:

```yaml
mcp_servers:
  lumen_filesystem:
    args:
      - "path/to/lumen-protocol/implementations/mcp-servers/filesystem/server_native.py"
    transport: lumen
    lumen_force_json_rpc: false  # Native binary mode
```

---

## Troubleshooting

### "MCP server failed to connect"
```bash
# Check logs
cat ~/AppData/Local/hermes/logs/mcp-stderr.log | tail -20

# Test server manually
python implementations/mcp-servers/filesystem/server.py
```

### "LUMEN SDK not available"
```bash
pip install -e implementations/python
```

### Windows: server not responding
Make sure `lumen_force_json_rpc: true` is set if using `server.py` (JSON-RPC wrapper).
Use `server_native.py` with `lumen_force_json_rpc: false` for native binary.

---

## See Also

- [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) — Full integration guide
- [TOOLS_GUIDE.md](implementations/mcp-servers/TOOLS_GUIDE.md) — When to use each tool
- [RETROSPECTIVE.md](implementations/mcp-servers/RETROSPECTIVE.md) — Before/after comparison
