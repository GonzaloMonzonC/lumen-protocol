# LUMEN Cognitive OS — Condensed Reference

Full doc: `docs/COGNITIVE_OS.md` in lumen-protocol repo.

## Architecture
- **47 tools** across 3 servers: 32 thinking + 13 filesystem + 2 web
- **Transport**: LUMEN Level 2 SHM — mmap ring buffers, zero-copy, 0 kernel copies
- **Plugin**: `lumen-shm-bridge` for Hermes Agent (recommended over MCP config)

## Cross-Session Tools (Phase C)
| Tool | Purpose |
|------|---------|
| `agent_message` | Send message to another session. Enables agent coordination. |
| `agent_inbox` | Read messages. Supports unread-only filtering. |
| `collision_check` | Detect files touched by multiple sessions (5-min window). |

## Key Benchmarks
- Thinking throughput: 3,407 calls/sec
- Thinking latency: 0.29ms avg
- FS vs Hermes: 9× faster (4.1ms vs 33ms)
- Wire savings: 5-59% (avg 29%)
- Errors: 0 in 530+ calls

## Global Features
- `_global_patterns`: patterns shared across all sessions (persisted to disk)
- `session_list`: shows ⚠️ collision warnings when 2+ sessions touch same file
- Wiki CRUD: `GET/POST /model` HTTP endpoints for dashboard editing
- Persistent messages: `_agent_messages` survive Hermes restarts
