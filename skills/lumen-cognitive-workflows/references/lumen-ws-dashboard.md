# LUMEN WebSocket Transport — Dashboard Protocol Extension

Date: 2026-06-20

## How It Works

The HTTP dashboard server (:9876) also starts a LUMEN WebSocket server on port+1 (:9877). Every `/metrics` request triggers a broadcast to all connected WebSocket clients, using the LUMEN wire format:

```
[LUM\x01:4B] [flags:1B] [length:4B LE] [zlib_payload:length]
```

## Measured Performance

- Payload: 33KB JSON → 6.8KB LUMEN frame
- Compression ratio: 80%
- Transport: WebSocket (real-time push, no polling)
- Server: lumen_transport.py (~200 lines, standalone module)
- Client: Vanilla JS WebSocket + DecompressionStream for zlib

## Architecture

```
Browser ← LUMEN WebSocket (compressed, push) → server.py :9877
       ← HTTP/JSON (fallback, polling)         → server.py :9876
```

## Dashboard Panels (18 total, June 2026)

| Section | Panels | Collapsible |
|---------|--------|-------------|
| KPIs | Thoughts, Score, Contradictions, Tool Calls | Always visible |
| Charts | Activity (bezier area line), System Pulse (NOW/RECENT/BLOCKED) | Always visible |
| Reasoning | Chains, Plans, Clusters, Heatmap | ✅ Collapsible |
| Knowledge | Wiki, Model, Decisions, Assumptions | ✅ Collapsible |
| Operations | Work Tracker, Sessions, Presence, Infra (Collisions/Claims/Bridges/Preserved), Manage | ✅ Collapsible |

## Pitfalls

- **Stale processes**: Server starts dashboard on daemon thread. Killing the main process kills the dashboard. Always use `sleep 999 | python server.py --dashboard 9876` or the plugin auto-spawn with `--dashboard`.
- **Duplicate JS from inline**: Keep LUMEN client code in separate file or IIFE. Inline template literals with `${}` can collide with Python/PHP template syntax.
- **Browser remote testing**: From Browserbase or remote browsers, `ws://127.0.0.1:9877` resolves to the remote machine, not localhost. Test on local machine only.
