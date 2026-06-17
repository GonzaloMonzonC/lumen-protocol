# LUMEN Inside Hermes — Deep Integration Proposal

## Vision

Hermes Agent's **built-in tools** (file operations, web, terminal, search)
routed through **LUMEN binary transport** — same tool names, same LLM
experience, but all communication compressed 40-60%, with streaming,
multiplexing, and Macaroon security.

## Current State

```
Hermes Agent
  │
  ├── read_file ──► Python handler ──► OS open/read    (no LUMEN)
  ├── write_file ─► Python handler ──► OS write         (no LUMEN)
  ├── search_files ► Python handler ─► ripgrep           (no LUMEN)
  ├── patch ──────► Python handler ──► fuzzy replace     (no LUMEN)
  │
  └── mcp_* ──────► MCP server ──► LUMEN transport     ✅ LUMEN
                     (external servers)
```

Only **external** MCP servers benefit from LUMEN. Built-in tools go directly
to the OS through Python function calls — no protocol, no LUMEN.

## Target Architecture

```
Hermes Agent
  │
  ├── read_file ──► Plugin shim ──► LUMEN frame ──► filesystem MCP server ──► OS
  ├── write_file ─► Plugin shim ──► LUMEN frame ──► filesystem MCP server ──► OS
  ├── search_files ► Plugin shim ─► LUMEN frame ──► filesystem MCP server ──► OS
  ├── patch ──────► Plugin shim ──► LUMEN frame ──► filesystem MCP server ──► OS
  │
  └── mcp_* ──────► MCP server ──► LUMEN transport     ✅ (existing)
```

Key design principle: **same tool names, same schemas, same LLM prompts**.
The LLM doesn't know (or care) that `read_file` is now proxied through LUMEN.

## How It Works

### Layer 1: LUMEN Filesystem MCP Server

A small Python MCP server (~200 lines) that implements Hermes's file tool
interface:

```
Tools exposed:
  - read_file(path, offset, limit) → content with line numbers
  - write_file(path, content)      → success/error
  - search_files(pattern, target, path, file_glob, limit) → matches
  - patch(path, old_string, new_string, replace_all) → unified diff

Transport: LUMEN stdio (binary frames, compressed payload)
Auth: Macaroon caveats (tool-level, path-prefix-level)
```

The server mirrors Hermes's exact tool schemas and result formats — the LLM
sees zero difference.

### Layer 2: Hermes Plugin (`hermes-lumen-native`)

A Hermes plugin (~100 lines) that:

1. **Spawns the LUMEN filesystem server** as a subprocess on startup
2. **Registers tool overrides** via `registry.register(name, override=True)`:
   ```python
   registry.register(
       name="read_file",
       toolset="lumen-native",
       schema=same_as_builtin,
       handler=lumen_read_file_handler,  # calls MCP server via LUMEN
       override=True,  # ← replaces built-in read_file
   )
   ```
3. **Handles lifecycle**: starts/stops the subprocess, reconnects on crash
4. **Deregisters** on unload, restoring built-in tools

### Layer 3: Hermes Config

```yaml
# ~/.hermes/config.yaml
plugins:
  hermes-lumen-native:
    enabled: true
    toolsets: [file]            # which built-in toolsets to override

lumen_native:
  mode: local_stdio             # or "remote_http" for networked servers
  lumen_probe_timeout_ms: 500
  toolsets:
    - file                      # replace read_file, write_file, patch, search_files
    # - web                     # future: replace web_search, web_extract
    # - terminal                # future: replace terminal
```

## Benefits

### 1. Multi-Agent Efficiency

```
Without LUMEN:         With LUMEN:
  5 agents               5 agents
  ├── read_file (OS)     │
  ├── read_file (OS)     ├── LUMEN ──► 1 filesystem server
  ├── read_file (OS)     │   (single process, MUX channels)
  ├── read_file (OS)     │
  └── read_file (OS)
  5 processes, no LUMEN  1 process, LUMEN MUX
```

N agents share one filesystem server. For `kanban` workers or `delegate_task`
sub-agents, this reduces process count and memory footprint.

### 2. Large File Streaming

Today `read_file` reads the entire file into memory before returning. With
LUMEN's `STREAM_DATA` frames, the server streams content token-by-token.
The agent can start processing before the full file is loaded.

### 3. Remote Filesystem

The filesystem server doesn't have to be local. With `mode: remote_http` +
`url: https://fileserver.internal`, Hermes can read/write files on a remote
machine with LUMEN binary compression over the network.

### 4. Security Isolation

- The filesystem server runs as a separate process with limited permissions
- Macaroon caveats restrict which tools and paths each agent can access
- Sub-agents get attenuated tokens (e.g., read-only, specific directories)

### 5. Zero LLM Context Change

Because tool names and schemas are identical, the LLM's cached system prompt
doesn't change. This is critical — Hermes's design principle: "per-conversation
prompt caching is sacred."

## File Tool → LUMEN MCP Server Mapping

| Built-in Tool | MCP Tool | Transport | Compression |
|---------------|----------|-----------|-------------|
| `read_file` | Same name, LUMEN-backed handler | stdio binary | ~50-70% |
| `write_file` | Same name, LUMEN-backed handler | stdio binary | ~40-60% |
| `patch` | Same name, LUMEN-backed handler | stdio binary | ~40-50% |
| `search_files` | Same name, LUMEN-backed handler | stdio binary | ~50-70% |

For large files (10K+ lines), the compression is significant. LUMEN's
dictionary already has keys like `path`, `content`, `result`, `total_lines`,
`matches` — so structural overhead almost disappears.

## Roadmap

### Phase 1: Filesystem LUMEN Server + Plugin (weekend project)

- [ ] `lumen_filesystem_server.py` — MCP server that wraps OS file ops
- [ ] `hermes-lumen-native` plugin — registers overrides, manages subprocess
- [ ] Config schema: enable per toolset, probe timeout, remote URL

### Phase 2: More Toolsets

- [ ] Web tools (`web_search`, `web_extract`) via LUMEN web MCP server
- [ ] Terminal (`terminal`) via LUMEN shell MCP server
- [ ] Search (`search_files` already covered by filesystem)

### Phase 3: Multi-Agent

- [ ] MUX channels — N agents over 1 server connection
- [ ] Macaroon caveats — agent-level, tool-level, path-level
- [ ] Remote HTTP — LUMEN over HTTP for distributed deployments

### Phase 4: Upstream

- [ ] Plugin published to Hermes plugins registry
- [ ] `hermes skills install hermes-lumen-native`
- [ ] Optional: propose as core Hermes feature

## Comparison: Approaches

| Approach | Tool Names | LLM Context | LUMEN Benefits | Effort |
|----------|-----------|-------------|----------------|--------|
| Disable file toolset + use MCP server | `mcp_filesystem_read_file` | Different from default | ✅ Full | ~50 lines config |
| Plugin with `override=True` | `read_file` (same!) | Unchanged | ✅ Full | ~200 lines |
| Modify core Hermes tool dispatch | `read_file` | Unchanged | ✅ Full | ~500 lines, upstream PR |
| Proxy all tools through MCP | Mixed | Varies | ✅ Full | ~1000 lines |

**Recommendation: start with the Plugin approach** — minimal invasion,
maximum benefit, safe to experiment without touching core Hermes code.

## Architecture Diagram

```
┌───────────────────────────────────────────────────────────┐
│                    Hermes Agent Process                    │
│                                                           │
│  ┌─────────────┐     ┌──────────────────┐                 │
│  │  LLM Context │     │  Tool Registry   │                 │
│  │  (unchanged) │     │                  │                 │
│  └─────────────┘     │  read_file ◄──── │ overridden      │
│                       │  write_file ◄─── │ by plugin       │
│                       │  search_files ◄─ │                 │
│                       │  patch ◄──────── │                 │
│                       └────────┬─────────┘                 │
│                                │                           │
│                    ┌───────────▼──────────┐                │
│                    │  LUMEN Native Plugin │                │
│                    │  (hermes-lumen)      │                │
│                    │                      │                │
│                    │  Starts child proc   │                │
│                    │  Routes tool calls   │                │
│                    │  override=True       │                │
│                    └───────────┬──────────┘                │
│                                │                           │
│                          LUMEN stdio                       │
│                     (binary frames)                        │
└────────────────────────────────┬──────────────────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │   LUMEN Filesystem MVC   │
                    │   Server (subprocess)    │
                    │                          │
                    │   Tools:                 │
                    │   - read_file            │
                    │   - write_file           │
                    │   - search_files         │
                    │   - patch                │
                    │                          │
                    │   Transport: LUMEN binary│
                    │   Security: Macaroons    │
                    │   Streaming: STREAM_DATA │
                    └────────────┬─────────────┘
                                 │
                            OS filesystem
                            (read/write/search)
```

## Test Plan

1. Install plugin: `hermes plugins install hermes-lumen-native`
2. Enable in config: `plugins.hermes-lumen-native.enabled: true`
3. Start Hermes, verify: `read_file ~/test.txt` returns content via LUMEN
4. Check wire savings: log frame sizes vs JSON equivalents
5. Multi-agent test: `delegate_task` with 3 sub-agents, all reading files
6. Streaming test: 10MB file read arrives in STREAM_DATA chunks
