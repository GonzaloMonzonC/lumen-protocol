# Dashboard Audit Findings — 2026-06-19

Exhaustive audit of the LUMEN dashboard using the full cognitive stack
(sequential_thinking chain #11, work tracking #11, pattern_record #12).

## Methodology

1. `work_start("Auditoría exhaustiva", category="audit")`
2. `sequential_thinking` chain #11 — 6 thoughts analyzing every panel
3. `thought_evaluate` on each step — score 7.7 (needed more actionability)
4. `thought_to_plan` — extracted 6 actionable steps
5. `pattern_record` for each bug found
6. Cross-check: curl /metrics vs dashboard JS rendering vs actual DOM

## Bugs Found and Fixed

### Bug #1: Metrics missing detail arrays (PATTERN #11)
**Symptom**: `model_entities: 9`, `assumptions: 2`, `decisions: 5` in totals but
no corresponding arrays in /metrics. Dashboard had no panels for these data sources.
**Fix**: Added `model[]`, `assumptions[]`, `decisions[]` arrays to /metrics JSON.
Added 3 dashboard panels with color-coded status badges.

### Bug #2: HTML divs not inserted for new panels (PATTERN #12)
**Symptom**: JS rendering code for model/decisions/assumptions existed but the
HTML `<div id="model-list">` etc. were never added to dashboard.html.
`$('model-list')` returned null silently — no error, no rendering.
**Fix**: Added 3 `<div>` containers with proper IDs to the HTML.

### Bug #3: Stale server processes on port 9876
**Symptom**: Dashboard showed old panels ("📬 Inbox", "📋 Activity" duplicates)
even though the committed file didn't have them. curl showed different content
than what was on disk. Up to 3 Python processes competing on :9876.
**Fix**: `netstat -ano | grep :9876 | awk '{print $5}' | while read pid; do taskkill //F //PID $pid; done`
then start ONE process with `sleep 999 | python -u server.py --dashboard 9876`.

## Token Optimization

Changed `sequential_thinking` output from verbose (5 thoughts history, ~400 chars)
to compact (last thought only, ~100 chars). Saves ~300 tokens per call.
Added `verbose=true` parameter for full history when needed.

## Model Tracking Infrastructure

Added `Session.model_name` field. Plugin auto-detects model via `HERMES_MODEL`
env var or `config.yaml`. Server records on first tool call per session.
/metrics exposes model in sessions_detail and presence. /benchmarks has
model_usage breakdown for future per-model analytics.

## Final Dashboard State

18 active panels: KPIs (clickable), Activity chart (48h canvas), Work Timeline
(Gantt), Chains (modal with full thoughts), Plans (click-to-expand), Work Tracker
(duration-colored), Wiki (500-char modal), Clusters, Heatmap (session×month),
Breakdown, Memory, Collisions, File Claims, Bridges, Preserved, Model,
Decisions, Assumptions, Sessions, Details, Manage (clear buttons).
