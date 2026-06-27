# Dashboard JavaScript Pitfalls — Debugging Guide
## June 20, 2026

### Symptom: All KPIs show 0, console error "renderData is not defined"

**Root cause**: The `refresh()` function HTTP fallback calls `renderData(d)` after
fetching `/metrics`, but `window.renderData` was never defined.

**Fix**: Define `window.renderData` as a function that handles ALL dashboard rendering
(KPIs, chains, plans, works, wiki, clusters, heatmap, pulse, breakdown, memory,
collisions, sessions, model, decisions, assumptions, presence, chart).

**Architecture**:
```
Fetch → renderData(data)  ← called by BOTH HTTP fallback AND WebSocket client
```

### Symptom: "Uncaught SyntaxError: Unexpected end of input"

**Root cause**: JS brace imbalance in inline `<script>` block. Common sources:
1. `async function refresh(){async function refresh(){` — function name duplicated on same line
2. Two `showCluster` functions (old `/chain` API + new `_lastClusters` version) — remove the old one
3. Duplicate `toggleSection` definitions — keep one, remove the other

**Fix**: Run the validator:
```bash
python implementations/mcp-servers/thinking/post-patch-validator.py
```
Target: 0 diff on braces.

### Symptom: "Uncaught ReferenceError: _lumenWs is not defined"

**Root cause**: The `refresh()` function checks `if(_lumenWs&&...)` but `_lumenWs` 
is only defined when the LUMEN WebSocket client script loads successfully.

**Fix**: Add `var _lumenWs=null;` before the `refresh()` function. Dashboard falls 
back to HTTP polling gracefully when WebSocket unavailable.

### Symptom: `/metrics` returns data but dashboard shows all zeros

**Root cause**: NOT a data issue — it's a JS crash from one of the above bugs.
The `refresh()` catch block catches ALL errors, sets "Offline" and empties all fields.

**Diagnostic chain**:
1. `curl http://localhost:9876/metrics` — if data is correct, problem is JS
2. Open browser console — look for SyntaxError or ReferenceError
3. Validator: `python post-patch-validator.py`
4. Check for stale processes: `netstat -ano | grep ":9876 " | grep LISTENING`

### Symptom: Dashboard serves OLD HTML despite code changes

**Root cause**: Multiple stale processes on port 9876. The oldest process wins the port.

**Fix**: Kill ALL processes on 9876, then start ONE:
```bash
netstat -ano | grep ":9876 " | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid 2>/dev/null; done
sleep 999 | python server.py --dashboard 9876
```
Verify: `curl -s http://localhost:9876/ | grep -c "your_new_feature"`

### chr() Calls in JS (Python Escape in JavaScript)

When generating JS via Python `execute_code`, Python's `chr()` function should NOT
be used to embed Unicode characters in JS. The literal text `chr(10003)` will be
emitted into the JS and cause a ReferenceError.

**Correct approach**: Use `\uXXXX` or `\u{XXXXX}` unicode escapes directly in JS,
or use the literal emoji character.

**Before (broken)**: `el.innerHTML = chr(10003) + 'Done'`  
**After (fixed)**: `el.innerHTML = '\u2713' + 'Done'`
