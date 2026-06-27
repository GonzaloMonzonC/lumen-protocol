# Dashboard HTTP API Reference

All endpoints served on `http://localhost:9876` when running `server.py --dashboard 9876`.

## GET Endpoints

| Endpoint | Returns | Key fields |
|---|---|---|
| `/` | dashboard.html | Full SPA |
| `/health` | "OK" | Server alive check |
| `/metrics` | Full cognitive state JSON | server, version, totals, scores, chains, plans, clusters, works, wiki, model, assumptions, decisions, bridges, preserved, presence, claims, sessions_detail, timeline |
| `/benchmarks` | Phase F scorecard | cognitive_roi, reasoning, pattern_recall, knowledge, work, adoption, comparative_advantage |
| `/chain?chain_id=X` | Single chain detail | thoughts[] with scores, branches, revisions, plan, clusters |
| `/collisions` | File collision report | window_s, collisions[{path, sessions, count}] |

### `/metrics` Response Structure (audit reference)

```json
{
  "server": "lumen-thinking",
  "version": "3.0.0",
  "uptime_seconds": 1234,
  "sessions": 8,
  "totals": {
    "chains": 10, "thoughts": 36, "patterns": 10, "decisions": 5,
    "model_entities": 9, "assumptions": 2, "works": 9, "tool_calls": 146,
    "preserved_contexts": 0, "branches": 0, "revisions": 0
  },
  "scores": {"avg": 9.2, "max": 10.0, "min": 7.7, "total_rated": 3, "unrated": 33},
  "chains": [{chain_id, session, thoughts, score_avg, branches, revisions, plan, clusters, preview}],
  "plans": [{chain_id, session, steps, format, preview}],
  "clusters": [{chain_id, session, theme, label, count}],
  "works": [{id, item, status, category, session, duration_seconds, started_at, done_at}],
  "wiki": [{title, chars, author, updated}],
  "model": [{entity, role, deps, notes}],
  "assumptions": [{id, statement, status, category}],
  "decisions": [{id, decision, category, rationale}],
  "bridges": [{query, chain_id, score, thought_preview}],
  "preserved": [{label, priority, content}],
  "presence": {"session_id": {pid, last_seen, tool_calls}},
  "claims": {"filepath": {owner, expires_in, status, requests}},
  "sessions_detail": {"session_id": {label, chains, patterns, tool_calls}},
  "timeline": [{hour, ts, calls, delta}]
}
```

## POST Endpoints

| Endpoint | Body | Response | Purpose |
|---|---|---|---|
| `/wiki` | `{title, content, author}` | `{created, chars}` | Create/update wiki page |
| `/claim` | `{session_id, path, ttl}` | 200 `{claimed}` or 409 `{conflict}` | File lock for Phase D |
| `/release` | `{session_id, path}` | `{released}` | Release file lock |
| `/clear-chains` | `{session_id}` | `{cleared, session}` | Wipe all chains |
| `/clear-bridges` | none | `{cleared}` | Wipe all bridges |
| `/touch` | `{session_id, path}` | `{touches}` | Register file access for collision detection |
| `/model` | `{entity, role, deps, notes}` | `{action, entity}` | CRUD mental model |

## Dashboard Panel → Metrics Field Mapping

| Panel | JS source | Metrics field |
|---|---|---|
| KPIs | `d.totals.*`, `d.scores.*` | totals, scores |
| Activity Chart | `d.timeline[]` | timeline[{ts, delta}] |
| Work Timeline | `d.works[]` | works[{started_at, done_at, status}] |
| Chains | `d.chains[]` | chains[{chain_id, thoughts, score_avg}] |
| Chain Modal | `fetch('/chain?chain_id='+cid)` | /chain endpoint |
| Plans | `d.plans[]` | plans[{chain_id, steps, preview}] |
| Work Tracker | `d.works[]` | works[{id, item, status, duration_seconds}] |
| Wiki | `d.wiki[]` | wiki[{title, chars, author}] |
| Model | `d.model[]` | model[{entity, role, deps}] |
| Decisions | `d.decisions[]` | decisions[{id, decision, rationale}] |
| Assumptions | `d.assumptions[]` | assumptions[{id, statement, status}] |
| Clusters | `d.clusters[]` | clusters[{label, count}] |
| Heatmap | `d.chains[]` | chains[{session, created_at, thoughts}] |
| Breakdown | `d.totals.*`, `d.scores.*` | totals, scores |
| Memory | `d.totals.thoughts` | totals.thoughts |
| Collisions | `fetch('/collisions')` | /collisions endpoint |
| Claims | `d.claims` | claims{} |
| Bridges | `d.bridges[]` | bridges[{score, query, chain_id}] |
| Preserved | `d.preserved[]` | preserved[{priority, content}] |
| Sessions | `d.sessions_detail` | sessions_detail{} |
| Presence | `d.presence` | presence{} |
| Manage | POST /clear-chains, /clear-bridges | — |
