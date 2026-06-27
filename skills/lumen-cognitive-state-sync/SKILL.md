---
name: lumen-cognitive-state-sync
description: '👽 Multi-agent shared mental models via LUMEN MUX channels. Export/import complete cognitive state between agents. LUMEN tools are marked 👽 in Hermes chat.'
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, multi-agent, sync, mux, swarm]
---

# Lumen Cognitive State Sync

> **Experimental**: First step towards multi-agent shared cognition.

Export/import complete cognitive state between Lumen-enabled agents via MUX channels.

---

## The Vision: Shared Cognitive Infrastructure

```
Agent A (Researcher) → COGNITIVE_SYNC → Agent B (Implementer) → COGNITIVE_SYNC → Agent C (Reviewer)
```

---

## Cognitive State Serialization Format

```json
{
  "version": "1.0",
  "timestamp": "2026-06-17T15:30:00Z",
  "source_agent": "hermes-session-abc123",
  "components": {
    "chains": [{ "chainId": "...", "thoughts": [...] }],
    "mental_model": { "entities": [...] },
    "assumptions": [...],
    "context_snapshots": [...],
    "work_log": [...]
  }
}
```

**Wire size**: ~2-5KB for typical cognitive state (chains 1KB, models 500B, assumptions 200B, context 300B, work_log 500B).

---

## MUX Channel: `cognitive-sync` (0x10)

```python
COGNITIVE_SYNC_CHANNEL = 0x10

# Protocol flow:
# MUX_OPEN(channel=0x10) → MUX_ACK
# MUX_DATA(export_request) → MUX_DATA(state) → MUX_DATA(import_ack)
# MUX_CLOSE(channel=0x10)
```

---

## Merge Strategies

- **Union** (default): Add non-duplicate items. Same name → skip.
- **Timestamp-Last-Wins**: Keep most recent version on conflict.
- **Source Priority**: Source agent wins on conflicts.

---

## Security: Macaroon-Based Capability Tokens

```python
macaroon_reader = Macaroon(
    location="cadences-lab", identifier="agent-b-reader",
    caveats=["subsystem = chains", "operation = read", "expires = ..."]
)
```

---

## Use Cases

1. **Research → Implementation**: Agent A investigates → passes full mental model to Agent B
2. **Multi-Agent Code Review**: Reviewer sees what, why, and what patterns were used
3. **Expertise Transfer**: Senior builds model → junior queries/learns
4. **Swarm Problem Solving**: N agents explore, merge models, synthesize

---

## Roadmap

| Phase | Feature | Status |
|-------|---------|--------|
| 0 | Serialization spec | ✅ Defined |
| D | Auto-negotiation (claim/release) | ✅ Implemented |
| E | Cross-machine MUX channels | ⏸️ Deferred |
| F | Benchmarks scorecard | ✅ Implemented |

## Phase D: Auto-Negotiation (File Claims Protocol + /negotiate HTTP Endpoint)

When multiple Hermes sessions touch the same files, the claim/release protocol resolves conflicts without human intervention:
- `POST /claim` with `{session_id, path, ttl}` → 200 (claimed) or 409 (conflict, auto-yields)
- `POST /release` with `{session_id, path}` → auto-transfers ownership to next waiting requester
- Stale claims expire after TTL (default 60s)
- Plugin auto-claims files before read/write operations via `_claim_file()`

### /negotiate Endpoint (Cross-Session Cognitive Sync)

An HTTP-level alternative to MUX channel sync. `POST /negotiate` on the dashboard server (port 9876) with:

```json
{
  "source_session": "default",
  "target_session": "default",
  "type": "all"
}
```

**Params:**
- `source_session` — session to export from (default: "default")
- `target_session` — session to import into (optional; omit for read-only export)
- `type` — resource filter: `"patterns"` | `"chains"` | `"decisions"` | `"all"` (default)

**When target_session is provided:**
- Creates target session if missing
- Imports patterns/chains/decisions with deduplication (by pattern_name, chain_id, decision_id)
- Saves state after import

**When target_session is omitted:**
- Returns export bundle with metadata (version, timestamp, source, bundle_size)

**Note:** This is lighter than MUX channel sync — no binary frames, no Macaroon tokens. Use for quick cross-session data sharing. Use MUX channels for multi-agent live synchronization.
| 1 | MUX channel prototype | ⏳ |
| 2 | Union merge | ⏳ |
| 3 | Timestamp merge | 🔮 |
| 4 | Macaroon tokens | 🔮 |
| 5 | Swarm orchestration | 🔮 |

---

## Pitfalls

- State explosion: cap entities at 1000 per domain
- Conflict resolution: timestamp-based needs synchronized clocks
- Privacy: cognitive state is sensitive — Macaroon tokens are the gate
- Versioning: schema mismatches → partial import
- MUX channel limits: max 16 concurrent channels; `cognitive-sync` uses 1