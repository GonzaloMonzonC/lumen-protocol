# LUMEN Universal Protocol Strategy

Date: 2026-06-20

## Strategic Decision

LUMEN wire format (magic bytes LUM\x01 + u32 length + zlib compression) is being extended beyond MCP transport to become a universal protocol for all Cadences Lab tooling. This positions LUMEN as "gRPC for AI tooling" — a binary, typed, compressed protocol designed for cognitive workloads.

## Current Domains Using LUMEN Wire Format

1. **MCP transport**: SHM binary pipes between plugin and servers (Level 2 zero-copy, 3407 calls/sec @ 0.29ms)
2. **Dashboard transport**: WebSocket + LUMEN frames on :9877 (Phase 1 deployed June 20, 2026)
3. **Agent-to-agent messaging**: agent_message via MCP (production)
4. **State file format**: .thinking_state.json with zlib persistence

## Competitive Advantage

- Compression: 55-80% vs JSON → lower bandwidth, lower cloud costs
- Binary framing: faster parse than JSON, no string conversion
- Streaming support: TYPE_STREAM_DATA for partial updates (only changed data, not full payload)
- Type safety: native int/float/bool types, no string conversion roundtrip
- Single protocol across entire stack → consistency, less code, easier debugging
- Positions LUMEN as infrastructure, not just a tool

## Implementation

- Server: lumen_transport.py (~200 lines, standalone module)
- Client: Vanilla JS WebSocket client + DecompressionStream for zlib
- Fallback: HTTP/JSON on :9876 when WebSocket unavailable
- Auto-start: _start_dashboard() starts LumenWS on port+1

## Next Phases

- Phase 2: LUMEN request/response (query specific data, not just metrics push)
- Phase 3: Document as open standard, publish JS + Python libraries
- Phase E: Distributed mesh across machines via LUMEN-over-WebSocket
