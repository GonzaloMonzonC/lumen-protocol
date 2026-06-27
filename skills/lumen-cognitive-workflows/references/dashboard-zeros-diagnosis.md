# Dashboard "All Zeros" Diagnosis & Fix
## June 20, 2026

### Symptoms
- `/metrics` returns correct data (32 thoughts, 278 calls, etc.)
- Dashboard shows all KPIs as 0, "Offline", "Error: renderData is not defined"
- Console shows `Uncaught ReferenceError: renderData is not defined`
- Chart works (shows activity bars) but KPIs don't

### Root Cause Chain
1. **Zombie processes**: Multiple stale Python processes on `:9876`. Oldest wins port, serves stale HTML.
2. **Missing renderData**: The `refresh()` function calls `window.renderData(d)` but the function was never defined.
3. **KPI class/ID mismatch**: `renderData` queried `.kpi-label`/`.kpi-value` classes but HTML uses IDs directly (`kpi-thoughts`, `kpi-score`).
4. **JS brace imbalance**: 153/152 braces (one extra `{`) from duplicate function definitions caused `Uncaught SyntaxError: Unexpected end of input`.

### Diagnostic Steps (in order)

```bash
# 1. Check /metrics directly
curl -s http://localhost:9876/metrics | python -c "import sys,json; d=json.load(sys.stdin); print(d['totals'])"

# 2. Count processes on port
netstat -ano | grep ":9876 " | grep LISTENING
# If 2+ processes → zombie problem

# 3. Check JS errors in browser console
# Open DevTools → Console tab

# 4. Check JS brace balance
curl -s http://localhost:9876/ | grep -o '<script>.*</script>' | python -c "
import sys; js=sys.stdin.read()
print('Braces:', js.count('{'), '/', js.count('}'))
"

# 5. Check renderData exists
curl -s http://localhost:9876/ | grep -c "function renderData"

# 6. Check KPI rendering
curl -s http://localhost:9876/ | grep -oP 'id="kpi-\w+"' | sort -u
```

### Fixes Applied

| Bug | Fix | Commit |
|---|---|---|
| Zombie processes | Kill all, start ONE: `sleep 999 \| python server.py --dashboard 9876` | Manual |
| JS brace imbalance | Remove duplicate functions: refresh(), showCluster(), toggleSection() | `087607d` |
| renderData missing | Define `window.renderData()` with full DOM rendering | `dedab28` |
| KPI class/ID mismatch | Update KPIs by element ID instead of `.kpi-label` class | `484a560` |
| _lumenWs ReferenceError | Add `var _lumenWs=null` declaration | `f9aeffa` |
| Auto-trigger silent crash | Fix variable name `new_thought` → `thought_obj` | `bcada40` |

### Prevention

**Always run the validator after any dashboard change:**
```bash
python implementations/mcp-servers/thinking/post-patch-validator.py
```

**Checklist before calling dashboard "fixed":**
1. `state_snapshot()` returns expected values
2. `/metrics` returns data (curl)
3. Only ONE process on `:9876`
4. JS brace balance: diff=0
5. No `ReferenceError` in browser console
6. KPIs show actual numbers, not 0
