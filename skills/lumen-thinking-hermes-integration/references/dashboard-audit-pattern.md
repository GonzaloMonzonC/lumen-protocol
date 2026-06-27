# Dashboard Audit Pattern

Systematic technique for verifying every dashboard panel against `/metrics` data.

See full pattern in `lumen-cognitive-workflows` skill → `references/dashboard-audit-pattern-2026-06-19.md`

Quick steps:
1. `curl /metrics | python -c "print(sorted(json.load(sys.stdin).keys()))"` → catalog fields
2. Cross-check each dashboard JS `.innerHTML` against `/metrics` field names
3. Look for `totals` counters without corresponding detail arrays
4. Verify served HTML bytes match disk file bytes (stale process detection)
