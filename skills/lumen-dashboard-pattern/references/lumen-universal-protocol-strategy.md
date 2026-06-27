# LUMEN Universal Protocol Strategy

**Date**: June 20, 2026  
**Chain**: `chain_11_1781912850` (4 thoughts)  
**Decision**: Extend LUMEN wire format from MCP-only to universal protocol

## Current State

```
Browser ←HTTP+JSON polling→ server.py :9876 ←SHM binary→ plugin (Hermes)
Dashboard      50KB/metrics        MCP server       mmap ring buffers
```

JSON over HTTP every 10s for the dashboard. MCP uses LUMEN binary (magic `LUM\x01` + u32 length + optional zlib). Two different protocols for the same system.

## Target State (Phase 1)

```
Browser ←WebSocket+LUMEN frames→ server.py :9876 ←SHM→ plugin
         push, 55-80% compression    single process, two interfaces
```

## LUMEN Wire Format (from `frame.py`)

```
[LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]
```

For dashboard metrics push, use TYPE_STREAM_DATA (0x04). For simplicity in Phase 1, use magic `LUM\x01` + u32 LE length + payload (same as SHM transport).

## Implementation Plan

### Phase 1 (2h): LUMEN-over-WebSocket MVP
- Add `/ws` WebSocket upgrade endpoint in server.py
- LUMEN frame encoder: `struct.pack("<I", len) + payload`
- Dashboard: `new WebSocket('ws://localhost:9876/ws')` with fallback to HTTP/JSON
- Encode `/metrics` JSON as LUMEN frame, push every 10s

### Phase 2 (3h): Request/Response
- Dashboard can send queries over WebSocket (GET /chain, POST /wiki)
- Full duplex LUMEN protocol

### Phase 3: Open Standard
- Document wire format as public spec
- Publish JS + Python decoder/encoder libraries
- Deprecate JSON for internal communication

## Advantages
- 55-80% compression vs JSON (50KB → 10-15KB)
- Push instead of polling (real-time)
- Type safety (native ints, not string coercion)
- Single protocol for entire stack (MCP, dashboard, agent-to-agent)
- Protocol positioning: LUMEN as universal AI tooling protocol

## Disadvantages
- WebSocket required (HTTP not binary)
- Encoder Python (~30 lines) + decoder JS (~50 lines) needed
- Debugging harder (no `curl` for binary)
- Adoption curve for third parties

## Verdict
Implement Phase 1 now. Low risk (fallback to HTTP/JSON), high strategic value (positions LUMEN as protocol, not tool).
