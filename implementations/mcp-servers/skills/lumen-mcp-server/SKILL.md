---
name: lumen-mcp-server
description: Build MCP servers with LUMEN binary transport for Hermes Agent. Templates, benchmarking, safety principles, and documentation patterns.
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, mcp, server, template]
---

# Building LUMEN MCP Servers

How to build MCP servers that use LUMEN binary transport and integrate with Hermes Agent.

## User's Standards

- **Superiority bar**: never replicate a Hermes built-in tool unless it's clearly superior (≥30% wire savings, differential features, or multi-agent benefit)
- **Honest benchmarks**: measure real data, correct inaccurate claims
- **Código quirúrgico**: minimal, elegant changes — not bloated
- **Deep analysis first**: Fase 0→1→2 gates before writing code
- **Safety principle**: tools must EXPAND perception, never REPLACE judgment

## Architecture

Two server types:

| Type | File | Protocol | Wire Savings | When to use |
|------|------|----------|-------------|-------------|
| JSON-RPC wrapper | `server.py` | JSON-RPC over LUMEN frames | 32-60% | Any MCP client |
| LUMEN native | `server_native.py` | Pure binary frames | 50-80% | LUMEN-aware clients only |

**Note**: `server_native.py` has Windows pipe issues with `subprocess.Popen`. Use `server.py` for production on Windows. The native version works correctly (validated via inline roundtrip tests).

## Server Template

See `references/server_template.py` for the canonical starting point.

Every server needs:
1. `TOOLS` list — MCP tool schemas (mirror Hermes built-in if replacing one)
2. `HANDLERS` dict — tool implementations
3. `handle_message()` — JSON-RPC message dispatcher
4. `main()` — stdio loop

## Hermes Config

```yaml
mcp_servers:
  lumen_<name>:
    command: "python"
    args: ["path/to/server.py"]
    transport: lumen
    lumen_force_json_rpc: true  # for JSON-RPC wrapper servers
```

## Benchmarking

Compare LUMEN vs Hermes built-in on the same real data:

```python
# Built-in
t0 = time.perf_counter()
with open(path) as f: ...
t_builtin = (time.perf_counter() - t0) * 1000

# LUMEN
t0 = time.perf_counter()
rpc("tools/call", name="tool_name", arguments={...})
t_lumen = (time.perf_counter() - t0) * 1000
```

Always measure: latency, output size, wire savings (via `compress_value`).

## Safety for Cognitive Tools

When building tools that affect agent cognition:
- ✅ **Perception expanders** (Assumption Tracker, Mental Model Builder) — safe
- ❌ **Judgment replacers** (Decision Journal, Confidence Tracker) — risk of bias
- Rule: the tool shows MORE info; the agent/user decides what to do

## Documentation Checklist

Every server needs:
- [ ] `server.py` (JSON-RPC wrapper)
- [ ] `server_native.py` (LUMEN native, optional)
- [ ] `shared_tools.py` (shared tool code, recommended if both server variants exist — see `lumen-mcp-server-pattern` skill)
- [ ] `README.md` (quick start, tools table, Hermes config)
- [ ] `test_suite.py` or inline tests
- [ ] Update `mcp-servers/README.md` with new server

## Existing Servers

| Server | Tools | Location |
|--------|-------|----------|
| Filesystem | 9 | `implementations/mcp-servers/filesystem/` |
| Web | 2 | `implementations/mcp-servers/web/` |
| Thinking | 22 | `implementations/mcp-servers/thinking/` |
