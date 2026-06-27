# Dashboard Audit Pattern (2026-06-19)

## When
Systematic review of a LUMEN dashboard — verify every panel shows correct data from `/metrics`.

## Workflow (using LUMEN cognitive tools)

```text
1. work_start("Dashboard audit", category="audit")
2. sequential_thinking(methodology — enumerate all panels, plan cross-check)
3. thought_evaluate on audit steps — ensure actionable
4. thought_to_plan → JSON plan
5. curl /metrics → catalog all top-level keys and their types
6. Cross-check each dashboard panel's JS render code against /metrics field
7. pattern_record for each bug found
8. wiki_create for audit findings
9. work_done with results
```

## Metrics Cross-Check Technique

```bash
# 1. Get all /metrics fields
curl -s http://localhost:9876/metrics | python -c "
import sys,json
d=json.load(sys.stdin)
print('top-level keys:', sorted(d.keys()))
print('totals:', json.dumps(d.get('totals',{}), indent=2))
"

# 2. Check each panel's data source in dashboard.html
# grep for innerHTML assignments to see which /metrics field each panel uses
grep -n "innerHTML.*d\." dashboard.html

# 3. Verify served HTML matches disk file
curl -s http://localhost:9876/ | wc -c
wc -c < dashboard.html
# Must match exactly
```

## Common Bugs Found

1. **Data stored but not exposed**: `model_entities`, `assumptions`, `decisions` are counters in `totals` but have no detail arrays in `/metrics`. Dashboard can't show them. Fix: add `model[]`, `assumptions[]`, `decisions[]` to metrics response.

2. **Features not exercised**: `branches`, `revisions` = 0 because `sequential_thinking` callers don't use `branchId`/`isRevision`. Not a bug — just unused features.

3. **Empty panels**: `preserved`, `bridges` empty because `context_preserve`/`thought_bridge` haven't been called. Dashboard correctly shows "No data".

## Stale Process Detection

Multiple `server.py --dashboard 9876` processes accumulate. The oldest handles requests and serves stale HTML.

```bash
# Detect
netstat -ano | grep ":9876 " | grep LISTENING

# Fix — kill all, restart one
netstat -ano | grep ":9876 " | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid 2>/dev/null; done
sleep 999 | python -u server.py --dashboard 9876 &

# Verify
curl -s http://localhost:9876/ | wc -c  # must match wc -c < dashboard.html
```

## Audit Results (2026-06-19)

- 13 panels audited, 0/13 failed
- 3 bugs found and fixed: model[], assumptions[], decisions[] added to /metrics
- 3 new dashboard panels: 🧠 Model, 📋 Decisions, ⏳ Assumptions
- Pattern #11 recorded: `metrics-missing-detail-arrays`
- Work #10 tracked: "Auditoría exhaustiva punto por punto del dashboard usando tools LUMEN"
- Chain #11: 6 thoughts analyzing every panel
