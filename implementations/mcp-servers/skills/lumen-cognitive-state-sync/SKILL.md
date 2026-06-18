---
name: lumen-cognitive-state-sync
description: Multi-agent shared mental models via LUMEN MUX channels. Export/import complete cognitive state (chains, models, assumptions, work logs) between agents.
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
Agent A investigates → passes mental model to Agent B that implements → Agent C reviews
with full context.

---

## The Vision: Shared Cognitive Infrastructure

```
Agent A (Researcher)          Agent B (Implementer)        Agent C (Reviewer)
    │                              │                            │
    │  investigate problem         │                            │
    │  build model                 │                            │
    │                              │                            │
    │── COGNITIVE_SYNC ──────────→│                            │
    │   (chains + models +         │                            │
    │    assumptions + context)    │  implement solution        │
    │                              │  query model for context   │
    │                              │                            │
    │                              │── COGNITIVE_SYNC ────────→│
    │                              │   (implementation +        │
    │                              │    models + work_log)      │  review with full
    │                              │                            │  cognitive context
```

---

## Cognitive State Serialization Format

A complete cognitive state snapshot (binary, compressed via LUMEN):

```json
{
  "version": "1.0",
  "timestamp": "2026-06-17T15:30:00Z",
  "source_agent": "hermes-session-abc123",
  "components": {
    "chains": [
      {
        "chainId": "chain_debug_api_timeout",
        "thoughts": [
          {"number": 1, "text": "...", "revisionOf": null, "branchFrom": null},
          {"number": 2, "text": "...", "revisionOf": 1}
        ]
      }
    ],
    "mental_model": {
      "entities": [
        {"id": "k8s_pod", "name": "K8s Pod", "properties": {"network": "shared_ns"},
         "relationships": [{"target": "cni_plugin", "type": "uses"}]}
      ]
    },
    "assumptions": [
      {"id": "assumption_1", "statement": "User growth 20%", "status": "violated",
       "evidence": "Q3 data shows 5%"}
    ],
    "context_snapshots": [
      {"label": "critical_constraints", "content": "Must be offline-first",
       "created_at": "2026-06-17T14:00:00Z"}
    ],
    "work_log": [
      {"task": "Auth Refactor", "blocks": [
        {"id": "extract_jwt", "status": "done"},
        {"id": "extract_rbac", "status": "in_progress"}
      ]}
    ]
  }
}
```

**Wire size**: ~2-5KB for a typical cognitive state (chains: 1KB, models: 500B, assumptions: 200B, context: 300B, work_log: 500B).

---

## MUX Channel: `cognitive-sync` (Channel 0x10)

Dedicated LUMEN MUX channel for cognitive state transfer:

```python
COGNITIVE_SYNC_CHANNEL = 0x10

def export_cognitive_state() -> dict:
    """Export complete cognitive state from all subsystems."""
    return {
        "chains": load_all_chains(),
        "mental_model": export_all_entities(),
        "assumptions": load_all_assumptions(),
        "context_snapshots": load_context_snapshots(),
        "work_log": load_work_log()
    }

def import_cognitive_state(state: dict, merge_strategy: str = "union") -> dict:
    """Import cognitive state from another agent. Merge strategy controls conflicts."""
    stats = {"imported": 0, "merged": 0, "conflicts": 0}

    if merge_strategy == "union":
        # Add all non-duplicate items
        stats = union_merge(state)
    elif merge_strategy == "timestamp_last_wins":
        # Keep most recent version of conflicting items
        stats = timestamp_merge(state)
    elif merge_strategy == "source_priority":
        # Source agent wins on conflicts
        stats = source_merge(state)

    return stats
```

---

## Sync Protocol (via MUX)

```
Agent A                              Agent B
   │                                     │
   │── MUX_OPEN(channel=0x10) ────────→│
   │←── MUX_ACK(channel=0x10) ────────│
   │                                     │
   │── MUX_DATA(channel=0x10,            │
   │     type="cognitive_sync",          │
   │     action="export_request") ─────→│
   │                                     │
   │←── MUX_DATA(channel=0x10,          │
   │     type="cognitive_sync",          │
   │     action="state",                 │
   │     payload=<compressed state>) ──│
   │                                     │
   │── MUX_DATA(channel=0x10,            │
   │     type="cognitive_sync",          │
   │     action="import_ack",            │
   │     stats={imported: 5}) ────────→│
   │                                     │
   │── MUX_CLOSE(channel=0x10) ────────→│
```

---

## Merge Strategies

### Union Merge (default)
Add all non-duplicate items. Entities with same name → skip. Assumptions with same statement → skip. Chains with same chainId → skip.

```python
def union_merge(state: dict) -> dict:
    stats = {"imported": 0, "merged": 0, "conflicts": 0}
    for chain in state["components"]["chains"]:
        if not chain_exists(chain["chainId"]):
            import_chain(chain)
            stats["imported"] += 1
    for entity in state["components"]["mental_model"]["entities"]:
        if not entity_exists(entity["name"]):
            import_entity(entity)
            stats["imported"] += 1
        else:
            stats["merged"] += 1  # silently skip existing
    # ... same for assumptions, context, work_log
    return stats
```

### Timestamp-Last-Wins
On conflict, keep the item with the most recent timestamp.

```python
def timestamp_merge(state: dict) -> dict:
    stats = {"imported": 0, "merged": 0, "conflicts": 0}
    for chain in state["components"]["chains"]:
        existing = get_chain(chain["chainId"])
        if not existing or chain["timestamp"] > existing["timestamp"]:
            import_chain(chain, overwrite=True)
            stats["imported" if not existing else "conflicts"] += 1
    # ... same for entities, assumptions
    return stats
```

### Source Priority
On conflict, the source agent's version wins (useful when Agent B is downstream).

```python
def source_merge(state: dict) -> dict:
    # Always import from source — overwrite local if exists
    stats = {"imported": 0, "merged": 0, "conflicts": 0}
    for chain in state["components"]["chains"]:
        import_chain(chain, overwrite=True)
        stats["imported" if not get_chain(chain["chainId"]) else "conflicts"] += 1
    return stats
```

---

## Security: Macaroon-Based Capability Tokens

Not all cognitive state should be shared. Macaroon tokens control per-subsystem access:

```python
# Macaroon capability for "read chains, write nothing"
macaroon_reader = Macaroon(
    location="cadences-lab",
    identifier="agent-b-reader",
    caveats=[
        "subsystem = chains",
        "operation = read",
        "expires = 2026-06-18T00:00:00Z"
    ]
)

# Macaroon for "read models + add assumptions"
macaroon_contributor = Macaroon(
    location="cadences-lab",
    identifier="agent-c-contributor",
    caveats=[
        "subsystem = mental_model",
        "operation = read",
        "subsystem = assumptions",
        "operation = write"
    ]
)

def verify_sync_capability(macaroon: Macaroon, subsystem: str, operation: str) -> bool:
    """Verify macaroon allows access to a specific cognitive subsystem."""
    return macaroon.verify(subsystem=subsystem, operation=operation)
```

---

## Use Cases

### 1. Research → Implementation Handoff
Agent A researches a bug, builds mental model. Passes complete cognitive state to
Agent B that writes the fix. Agent B has full context without repeating research.

### 2. Multi-Agent Code Review
Agent A writes code (work_log + model of changes). Passes to Agent B (reviewer).
Agent B sees: what was done (work_log), why (assumptions), what patterns were used
(mental_model). Review is informed, not guesswork.

### 3. Expertise Transfer
Senior agent builds mental model of a domain. Passes to junior agent for learning.
Junior queries model, asks questions, adds to it.

### 4. Swarm Problem Solving
N agents explore different hypotheses. Each builds a chain + model + assumptions.
Cognitive state sync → merge all → Agent N+1 synthesizes. Shared cognition without
shared memory threads.

---

## Roadmap

| Phase | Feature | Status |
|-------|---------|--------|
| Phase 0 | Serialization format spec | ✅ Defined |
| Phase 1 | MUX channel `cognitive-sync` | ⏳ Prototype |
| Phase 2 | Union merge implementation | ⏳ Planned |
| Phase 3 | Timestamp-last-wins merge | ⏳ Planned |
| Phase 4 | Macaroon capability tokens | 🔮 Future |
| Phase 5 | Swarm orchestration (N agents) | 🔮 Future |

---

## Pitfalls

- **State explosion**: Merging N agents' models → entities can grow unbounded. Cap entities at 1000 per domain.
- **Conflict resolution**: Timestamp-based merge assumes synchronized clocks. Add server timestamp to all items.
- **Privacy**: Cognitive state contains reasoning, assumptions, plans — sensitive. Macaroon tokens are the gate.
- **Versioning**: State schema version mismatches → partial import. Always version the sync payload.
- **MUX channel limits**: Max 16 concurrent channels. `cognitive-sync` uses 1. Leave room for reasoning, model, work channels.
