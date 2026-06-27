# LUMEN MCP Servers

**Production-ready MCP servers** using LUMEN binary protocol with Level 2 zero-copy shared memory transport.

✅ **Status: Production** — 88 tools across 4 servers. SHM transport benchmarked at 9× faster than Hermes built-ins.
Sandboxing, session isolation, Windows parity, and reproducible benchmarks complete.

Three transport modes per server:

- **`server.py`** — Standard JSON-RPC over stdio, LUMEN wrapper at transport layer (32-60% wire savings).
- **`server_native.py`** — LUMEN binary frames, PROBE/ACK handshake, no JSON-RPC wrapping (55-80% savings).
  ⚠️ Requires binary pipes (Hermes plugin bridge, not MCP config).
- **`server_shm.py`** 🔥 — **Level 2 zero-copy** via mmap ring buffers. 55-80% wire savings + zero kernel copies.
  **Plugin `lumen-shm-bridge` provides transparent Hermes integration.**

## Servers

| Server | Tools | Key Features |
|--------|-------|--------------|
| **[Filesystem](filesystem/)** 🔥 | **13** | Bulk reads (`read_files`), context search (`search_with_context`), streaming (`stream_read`), Windows-parity tools (`file_info`, `disk_usage`, `search_filename`, `find_duplicates`) |
| **[Web](web/)** | 2 | `web_search` + `web_extract` combined, zero API keys required |
| **[PDB](pdb/)** 🔥 | **17** | MUMPS-compatible process database with SQLite backend. CRUD, FTS5, **RAG (semantic embeddings via fastembed)**, M-Light expressions. `pdb_embed`, `pdb_embed_search` |
| **[Thinking](thinking/)** 🔥 | **48** | Reasoning chains (branching, bridges, TF-IDF, contradiction detection), Agent Loop (5 tools), wiki CRUD, kanban, Q&A, assumption tracker, mental model, work tracking, pattern memory, session isolation |

| **Total** | **86** | 4 servers, 0 external dependencies, Level 2 SHM zero-copy |

**86 tools across 4 servers. Standard library only — no external dependencies.**

## Benchmark Results (June 2026)

| Metric | LUMEN SHM | Hermes Built-in | Improvement |
|--------|-----------|-----------------|-------------|
| FS avg latency | **4.1ms** | 33ms (terminal) | **9× faster** |
| Think avg latency | **0.35ms** | N/A | Sub-ms |
| Think throughput | **3,662 calls/sec** | N/A | Cognitive burst |
| FS throughput | **525 calls/sec** | N/A | Mixed burst |
| Wire savings | **10-59%** (avg 19%) | 0% | Per response |
| Kernel copies | **0** (mmap) | 2 per call (pipes) | Zero-copy |
| Errors (440 calls) | **0** | Variable (shell fragility) | Rock-solid |

> Full benchmarks: `pdb/bench-results/INFORME_GLOBAL.md` (3 versions, 8 models)

## Cognitive Workflow Skills

Ready-to-use composition patterns, integration guides, and safety guardrails
for Lumen Thinking's 29 cognitive tools:

| Skill | Description | Status |
|-------|-------------|--------|
| **[Lumen Control](skills/lumen-control/SKILL.md)** | Dashboard, benchmarks (filesystem/thinking/transport), superiority bar, troubleshooting | ✅ |
| **[Cognitive Workflows](skills/lumen-cognitive-workflows/SKILL.md)** | 6 proven workflow patterns (Problem→Plan→Execute, Decision→Validation→Learning, Scientific Debugging, Structured Learning, Multi-Session Task) | ✅ |
| **[Hermes Integration](skills/lumen-thinking-hermes-integration/SKILL.md)** | Deep Hermes Agent integration: auto-context hooks, plan bridge plugin, subagent usage, disabled_toolsets config | ✅ |
| **[Cognitive Safety](skills/lumen-cognitive-safety/SKILL.md)** | SAFE vs UNSAFE tool taxonomy, 7-gate audit checklist, implementation rule, regression tests | ✅ |
| **[Native Server Dev](skills/lumen-thinking-server-dev/SKILL.md)** | Build LUMEN-native thinking servers: STREAM_DATA token streaming, MUX parallel channels, Windows-safe frame I/O | ✅ |
| **[Cognitive State Sync](skills/lumen-cognitive-state-sync/SKILL.md)** | Multi-agent shared mental models via MUX `cognitive-sync` channel 🚀 | 🔮 Experimental |
| **[MCP Server](skills/lumen-mcp-server/SKILL.md)** | Server templates, architecture (Pattern A/B/C), benchmarking, safety principles | ✅ |
| **[MCP Server Pattern](skills/lumen-mcp-server-pattern/SKILL.md)** | Proven patterns: shared_tools, session isolation, eval framework, security hardening | ✅ |
| **[Server Development](skills/lumen-server-development/SKILL.md)** | Canonical guide: 3 server patterns, PROBE handshake, SHM transport, pitfall checklist | ✅ |

## 🆕 Cross-Session Cognition — LUMEN Cognitive OS

The thinking server now supports **multi-agent coordination** with 3 new tools (32 total):

| Tool | Description |
|------|-------------|
| `agent_message` | Send messages between Hermes sessions. Enables agent-to-agent coordination. |
| `agent_inbox` | Read messages from other sessions. Supports unread-only filtering. |
| `collision_check` | Detect files touched by multiple sessions in the last 5 minutes. |

### Cross-Session Features

- **Global Pattern Store**: `pattern_record` saves to shared `_global_patterns`. `pattern_match` searches local + global.
- **Session Collision Warnings**: `session_list` shows ⚠️ when multiple sessions touch the same file.
- **Wiki CRUD via HTTP**: `GET/POST /model` endpoints for dashboard-based knowledge editing.
- **Persistent Messages**: `_agent_messages` survive Hermes restarts (saved to `.thinking_state.json`).

See [`docs/COGNITIVE_OS.md`](../../docs/COGNITIVE_OS.md) for full architecture and benchmarks.

## Quick Start

```bash
# JSON-RPC mode (any MCP client)
python implementations/mcp-servers/filesystem/server.py
python implementations/mcp-servers/web/server.py
python implementations/mcp-servers/thinking/server.py

# SHM (Level 2 zero-copy) — via Hermes plugin or direct test
python implementations/mcp-servers/filesystem/server_shm.py
python implementations/mcp-servers/web/server_shm.py
python implementations/mcp-servers/thinking/server_shm.py
```

## Hermes Agent Integration

### Via Plugin (Recommended — all 86 tools, zero-copy SHM)

```yaml
plugins:
  enabled:
    - lumen-shm-bridge
```

The plugin auto-spawns SHM servers on first use. Tools appear as `read_file`, `search_files`, etc.
(overrides Hermes built-ins). All 44 tools available with zero-copy mmap transport.

See `~/.hermes/plugins/lumen-shm-bridge/plugin.yaml` for manifest.

### Via MCP Config (Legacy — L1 only, no SHM)

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["path/to/lumen-protocol/implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
    lumen_force_json_rpc: true  # REQUIRED for readline()-based servers
```

⚠️ MCP config uses Hermes' text pipes → binary native servers can't connect via this path.
Use the plugin for SHM (Level 2) or native binary transport.

## Transport Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Level 2 (SHM) 🔥                                            │
│  Hermes ←→ Plugin ←→ mmap Ring Buffer ←→ LUMEN Server      │
│  Zero kernel copies, sub-ms latency, 44 tools               │
├─────────────────────────────────────────────────────────────┤
│  Level 1 (Binary)                                           │
│  Hermes ←→ LUMEN frames (stdio) ←→ server_native.py        │
│  55-80% wire savings, requires binary pipes                 │
├─────────────────────────────────────────────────────────────┤
│  Level 1 (Wrapper)                                          │
│  Hermes ←→ LUMEN-wrapped JSON-RPC ←→ server.py             │
│  32-60% wire savings, force_json_rpc: true                  │
└─────────────────────────────────────────────────────────────┘
```

## Creating a New Server

1. Copy `filesystem/server.py` as template
2. Replace `TOOLS` list with your tool schemas
3. Replace `HANDLERS` dict with your implementations
4. Optionally add `server_native.py` for LUMEN binary transport
5. Optionally add `server_shm.py` for Level 2 zero-copy (extend `ShmNativeServer`)
6. Test: `python test_suite.py` (if provided)

Template code for LUMEN frames is provided by:
- `build_frame()` / `parse_frame()` from `lumen` Python package
- `read_lumen_frame()` / `send_lumen_frame()` in `server_native.py`
- `ShmNativeServer` base class in `shm_native_server.py` for Level 2