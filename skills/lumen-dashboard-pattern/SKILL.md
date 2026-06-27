---
name: lumen-dashboard-pattern
description: '👽 Build interactive LUMEN monitoring dashboards with vanilla JS canvases, KPIs, Gantt charts, chain modals, wiki panels, file claims, and traceability — cadenceslab design system. Zero external dependencies. LUMEN tools prefixed 👽.'
version: 1.1.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, dashboard, visualization, monitoring, alpine]
---

# LUMEN Dashboard Pattern

Proven pattern for building interactive monitoring dashboards that visualize LUMEN thinking server data. Two deployment modes: **local** (vanilla JS, served by thinking server) and **Vercel** (Astro build, static deploy).

## Architecture (June 2026)

```
Thinking Server (--dashboard 9876)
├── /           → dashboard.html (vanilla JS, self-contained)
├── /metrics    → JSON API (totals, chains, plans, clusters, works, wiki, bridges, presence, collisions, timeline)
├── /health       → Plain text OK
├── GET /collisions → Cross-session file conflict detection
├── POST /touch   → Register file access for collision detection
├── POST /collisions → Also available as POST
├── GET /benchmarks → Phase F auto-scorecard from live data (chains, patterns, wiki, works)
├── POST /claim    → File lock for cross-session negotiation (Phase D)
├── POST /release  → Release claim, auto-transfer to next requester
├── POST /wiki     → Create/update wiki pages from dashboard
├── POST /clear-chains → Memory management
└── POST /clear-bridges → Memory management

NEW endpoints (June 19 2026):
├── GET /chain?chain_id=X → Full chain with all thoughts, scores, branches, revisions
├── GET /benchmarks → Phase F auto-scorecard (cognitive ROI, pattern recall, work tracking)
└── GET /collisions → Cross-session file conflicts (5-min window)

Dashboard panels (all vanilla JS, zero dependencies):
  KPIs (4 cards) → 48h Activity Chart (bars + cumulative line) → Work Timeline (Gantt)
  → Chains (click→rich modal with full thought list) → Plans → Work Tracker
  → Wiki (click→modal) → Clusters → Breakdown → Memory
  → Collisions → File Claims → Bridges → Preserved → Sessions → Manage (clear buttons)
```

## Dashboard.html Pattern (Vanilla JS — June 2026)

**CRITICAL: Use vanilla JS, not Alpine.js.** Alpine had unresolved timing issues across 4 attempted fixes:
- `Alpine.data()` → registration ran after x-data evaluation → "ReferenceError"
- Inline `x-data` + `x-init` → async functions not callable → "init is not defined"
- `Alpine.store()` + `$store.dash` → `_x_dataStack` undefined on access  
- Event-based (alpine:init, window.load) → inconsistent across refreshes

**Solution**: Vanilla JS. `fetch('/metrics')` + `innerHTML` + Canvas. Zero deps, zero timing issues.

```html
<!-- Minimal template -->
<div id="kpi-chains">0</div>
<div id="chains-list">No chains</div>
<canvas id="chart"></canvas>

<script>
const $=id=>document.getElementById(id);
async function refresh(){
  const d=await fetch('/metrics').then(r=>r.json());
  $('kpi-chains').textContent=d.totals.chains;
  $('chains-list').innerHTML=d.chains.map(c=>
    `<div class="card" onclick="showChain('${c.chain_id}')">
      ${c.chain_id} · ${c.thoughts}t · ${c.score_avg}★
    </div>`
  ).join('');
}
refresh();setInterval(refresh,3000);
</script>
```

## Chart Pattern (Canvas, adaptive 48h, retina-ready)

```javascript
function drawChart(timeline){
  const ctx=canvas.getContext('2d');
  const dpr = devicePixelRatio || 1;
  // Retina: scale canvas by devicePixelRatio for sharp rendering
  canvas.width = W * dpr; canvas.height = H * dpr;
  canvas.style.width = W + 'px'; canvas.style.height = H + 'px';
  ctx.scale(dpr, dpr);
  
  // Adaptive: show only hours with data, cap at 48
  const bars=Math.min(48,Math.max(6,Math.ceil(maxH*1.2)));
  // Bar chart with gradient fill + purple cumulative line overlay
  // X-axis: "2h ago", "1d ago" labels
  // Rounded bars via roundRect() helper
  // Stats row: total calls, peak time, window size
}

// Rounded rectangle helper for canvas bars
function roundRect(ctx, x, y, w, h, r){
  ctx.beginPath();
  ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.arcTo(x+w,y,x+w,y+r,r);
  ctx.lineTo(x+w,y+h-r); ctx.arcTo(x+w,y+h,x+w-r,y+h,r);
  ctx.lineTo(x+r,y+h); ctx.arcTo(x,y+h,x,y+h-r,r);
  ctx.lineTo(x,y+r); ctx.arcTo(x,y,x+r,y,r); ctx.closePath();
}
```

## Metrics API Shape

```json
{
  "totals": {chains, thoughts, patterns, decisions, model_entities, assumptions, works, tool_calls, branches, revisions},
  "scores": {avg, max, min, total_rated, unrated},
  "chains": [{chain_id, thoughts, score_avg, score_max, branches, revisions, plan, clusters, preview}],
  "plans": [{chain_id, steps, format, preview}],
  "clusters": [{chain_id, label, count}],
  "works": [{id, item, status, duration_seconds}],
  "wiki": [{title, chars, author, updated}],
  "bridges": [{query, chain_id, score}],
  "preserved": [{label, priority, content}],
  "sessions_detail": {session_id: {chains, patterns, decisions, tool_calls}},
  "presence": {session_id: {pid, last_seen, tool_calls}},
  "timeline": [{hour, ts, calls, delta}]
}
```

## Panel Checklist (ordered by value)

| # | Panel | Data source | Priority |
|---|-------|------------|----------|
| 1 | KPIs (4 cards) | totals + scores | 🔴 Must |
| 2 | 48h Activity Chart | timeline (adaptive bars) | 🔴 Must |
| 3 | Chains (click→modal) | chains[] | 🔴 Must |
| 4 | Plans | plans[] | 🟡 High |
| 5 | Work Tracker (durations) | works[] | 🟡 High |
| 6 | Clusters | clusters[] | 🟡 High |
| 7 | Wiki | wiki[] | 🟡 High |
| 8 | Thought Breakdown | totals + scores | 🟢 Medium |
| 9 | Memory | totals (thoughts/200 bar) | 🟢 Medium |
| 10 | Bridges | bridges[] | 🟢 Medium |
| 10 | ⚠️ Collisions | GET /collisions | 🟢 Medium |
| 11 | 🔒 File Claims | claims (from /metrics) | 🟢 Medium |
| 12 | Preserved Contexts | preserved[] | ⚪ Low |
| 13 | Sessions | sessions_detail | ⚪ Low |
| 14 | Active Presence | presence | ⚪ Low |
| 15 | Manage (clear buttons) | POST endpoints | ⚪ Low |
| 16 | 🔒 File Claims | claims (from /metrics) | 🟢 Medium |

## Work Gantt Chart Pattern (DEPRECATED — use System Pulse)

The Gantt chart approach has a fundamental scale problem: 52-second tasks are invisible on a 48-hour canvas. Replaced by **System Pulse** (see below). Use Gantt ONLY when all work items have durations > 1 hour AND the number of items < 10.

## System Pulse Panel Pattern (June 2026)

Three-zone panel replacing the Work Timeline Gantt. Always visible, no scale issues:

```html
<div class="chart-wrap">
  <h3>System Pulse</h3>
  <div class="grid3">
    <div><!-- ▶ NOW: active works, cyan, show duration --><div id="pulse-now"></div></div>
    <div><!-- ● RECENT: last 5 done, green, show time ago --><div id="pulse-recent"></div></div>
    <div><!-- ■ BLOCKED: blocked works, red --><div id="pulse-blocked"></div></div>
  </div>
</div>
```

```javascript
function pulseUpdate(works){
  const now=Date.now()/1000;
  const fmtAgo=ts=>{const s=Math.round(now-ts);return s<60?s+'s':s<3600?Math.floor(s/60)+'m':Math.floor(s/3600)+'h'};
  const fmtDur=d=>d<60?d+'s':(d/60).toFixed(0)+'m';
  const active=works.filter(w=>w.status!=='done'&&w.status!=='blocked').slice(0,4);
  const done=works.filter(w=>w.status==='done').sort((a,b)=>(b.done_at||0)-(a.done_at||0)).slice(0,5);
  const blocked=works.filter(w=>w.status==='blocked').slice(0,3);
  $('pulse-now').innerHTML=active.map(w=>`▶ ${w.item?.slice(0,28)} <span>${fmtDur(w.duration_seconds)}</span>`).join('');
  $('pulse-recent').innerHTML=done.map(w=>`● ${w.item?.slice(0,28)} <span>${fmtAgo(w.done_at)}</span>`).join('');
  $('pulse-blocked').innerHTML=blocked.map(w=>`■ ${w.item?.slice(0,28)}</span>`).join('');
}
```

## Cluster Clickable Modal Pattern (June 2026)

Clusters from `thought_summarize` must be clickable with rich modals. Use IN-MEMORY data, not `/chain` API — clusters live per-session, not per-chain:

```javascript
window._lastClusters = d.clusters || [];
$('clusters-list').innerHTML = clusters.map(c => `<div class="card" style="cursor:pointer" onclick="showCluster('${c.chain_id}')">...</div>`).join('');

function showCluster(cid){
  const clusters = (window._lastClusters||[]).filter(c=>c.chain_id===cid);
  // Render modal with full theme breakdown: label, count, preview
}
```

## Collapsible Sections UX Pattern (June 2026)

Group panels into collapsible sections with summary counters (e.g. "10c · 4p · 5cl"). Click header to toggle, smooth CSS transition. Use `toggleSection(id)` with `.collapsible.collapsed` class.

## Skynet-Quality CSS (June 2026)

Key improvements from skynet original (commit 590442f):
- `backdrop-filter: blur(20px)` on `.glass` for real glass morphism
- `radial-gradient` background for depth (cyan + blue ellipses)
- Google Fonts: Inter (weights 400-800) + JetBrains Mono (400-600)
- Custom scrollbar: 5px, slate-700 thumb
- Hover transitions on panels, cards, KPIs
- Color palette: `--bg:#0a0a0f` `--acc:#22d3ee` `--purp:#a855f7` `--text:#d1d5db` `--dim:#9ca3af` `--slate800:#1a1a24`

// Rounded rectangle helper for canvas
function roundRect(ctx, x, y, w, h, r){
  ctx.beginPath();
  ctx.moveTo(x+r,y); ctx.lineTo(x+w-r,y); ctx.arcTo(x+w,y,x+w,y+r,r);
  ctx.lineTo(x+w,y+h-r); ctx.arcTo(x+w,y+h,x+w-r,y+h,r);
  ctx.lineTo(x+r,y+h); ctx.arcTo(x,y+h,x,y+h-r,r);
  ctx.lineTo(x,y+r); ctx.arcTo(x,y,x+r,y,r); ctx.closePath();
}
```

## Chart Stats Row

Add a stats summary below the activity chart for quick insights:

```javascript
$('chart-stats').innerHTML = `
  <span>🟢 ${totalCalls} calls</span>
  <span>📈 Peak: ${maxV} at ${bars-1-peakH}h ago</span>
  <span>📊 ${bars}h window</span>`;
```

This provides at-a-glance numbers without cluttering the chart.

```javascript
// Plugin auto-calls after file operations:
fetch('http://127.0.0.1:9876/touch', {
  method:'POST', body:JSON.stringify({session_id:'default', path:'/repo/file.py'})
});

// Dashboard fetches collisions:
fetch('/collisions').then(r=>r.json()).then(d=>{
  // d.collisions: [{path, sessions:[], count}]
  // Show ⚠️ for files touched by ≥2 sessions in <5min
});
```

## Pitfalls

### Critical Dashboard Bugs — June 22 Session (8+ fixed)

All verified in production dashboard at `localhost:9876`. These bugs caused panels to show zeros, empty data, or stale content.

**1. ID Mismatch — Breakdown always zero**
- **Symptom**: Breakdown section shows Total=0, Chains=0 despite server having data
- **Root cause**: JS used `document.getElementById('brk-total')` but HTML has `id="tb-total"`
- **Fix**: Match JS element IDs to HTML: `brk-*` → `tb-*`
- **Also affected**: Memory panel — JS used `mem-total` but HTML has `mem-t`

**2. Double Theme Label — Clusters duplicated**
- **Symptom**: Cluster items show "Theme 1: Theme 1: save, tool..."
- **Root cause**: Label format included BOTH `'Theme X:'` prefix AND `cl.label` which already contains "Theme X:"
- **Fix**: Show only `cl.label`, don't add redundant prefix

**3. Bridges without chain context**
- **Symptom**: Bridge items show just float scores (e.g. "0.37") with no chain info
- **Root cause**: Only `b.score` was rendered, missing `b.chain_id`
- **Fix**: Add `b.chain_id` to bridge rendering

**4. Hardcoded slice() limits hide data**
- **Symptom**: Only 5 decisions shown when 12 exist; only 5 assumptions when 8 exist; only 15 model entities when 20 exist
- **Root cause**: Multiple `slice(0,5)` and `slice(0,15)` calls in JS rendering
- **Fix**: Change to `slice(0,20)` and `slice(0,25)` for all panels
- **Verification**: `document.querySelectorAll('#<panel> .chain-row').length` vs API count

**5. /decisions endpoint in wrong HTTP method**
- **Symptom**: Decisions panel shows "Error loading", `/decisions` returns 404
- **Root cause**: The `elif self.path == "/decisions"` block was added inside `do_POST` instead of `do_GET`
- **Diagnosis**: `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9876/decisions` returns 404
- **Fix**: Move the handler to `do_GET` BEFORE the final `else: self.send_response(404)`. NEVER insert code after `else` in an if/elif chain — Python syntax error

**6. Kanban dropdown not populated**
- **Symptom**: Kanban shows "Select a niche to show the board" but dropdown has no options
- **Root cause**: `loadKanban()` fetched niches but never created `<option>` elements
- **Fix**: After `_kanbanNiches = d.niches`, create option elements: `sel.innerHTML = '<option>...'` then `niches.forEach(n => { const opt = document.createElement('option'); ... })`
- **Archived niche display**: Show with 📦 prefix, filter archived from active list

**7. work_start param name mismatch**
- **Symptom**: `work_start(title="...")` returns no output, work items never created, System Pulse always empty
- **Root cause**: Handler expects `args["item"]` but Hermes tool sends `title`
- **Fix**: `args.get("item") or args.get("title", "")` — accept both param names

**8. PDB Snapshot for state recovery**
- **Symptom**: Thinking server state lost when process killed (taskkill, power loss)
- **Fix**: Add `_pdb_snapshot()` function that writes chains, decisions, assumptions, works, patterns, wiki, model to PDB SQLite. Runs in daemon thread every 5 saves. `_load_state()` falls back to PDB when JSON missing/corrupt. Zero LLM tokens — entirely in-process.

### Post-edit verification checklist

After ANY edit to `dashboard.html` or `server.py`:
1. `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9876/` — must return 200
2. Kill old server: `netstat -ano | grep ":9876 " | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid; done`
3. Clear cache: `rm -f __pycache__/server.cpython-311.pyc`
4. Restart via Hermes tool call or plugin restart
5. Verify each panel in browser console: `document.querySelectorAll('#<panel> .chain-row').length`

### Chart tooltip pattern (June 2026)

Add hover tooltip to canvas activity chart:
```javascript
c.onmousemove = function(e) {
  const rect = c.getBoundingClientRect();
  const mx = e.clientX - rect.left - padX;
  const idx = Math.round(mx / barWidth);
  if (idx < 0 || idx >= bars || !buckets[idx]) { tooltip.style.display = 'none'; return }
  tooltip.textContent = buckets[idx] + ' calls — ' + hoursAgo + ' ago';
  tooltip.style.display = 'block';
}
c.onmouseleave = function() { tooltip.style.display = 'none'; }
```
- **Dashboard HTML as Python string**: Always serve from `dashboard.html` file, never inline `r"""..."""`.
- **Chart flat line**: Timeline stores cumulative totals. Show DELTA values per hour for visible activity bars.
- **Work Gantt micro-durations**: 52-second tasks are invisible on a 48h timeline (0.03% of chart width). Don't use Gantt for sub-minute tasks — use a compact list with colored time indicators instead (● item · duration · time ago). Completed works: green bars with duration label. Active/blocked: small indicators at right edge.
- **State file race condition (CRITICAL)**: Dashboard server and MCP server share `.thinking_state.json`. Dashboard writes stale state on save, overwriting MCP-created data (wiki, chains). Two-part fix: (a) add `global _last_state_mtime` in `_build_metrics()` so the state reload checker actually updates the global variable instead of shadowing it locally, (b) ensure `_save_state()` in dashboard POST handlers writes the FULL session dict including wiki, bridges, etc. — not a partial update.
- **Wiki vs Model panel collision**: `loadWiki()` fetches `/model` and overwrites `wiki-list` innerHTML with mental model entities, replacing the real wiki pages from `/metrics`. Fix: remove `loadWiki()` call from `refresh()`. Keep wiki rendering as inline code using `/metrics` wiki data, not a separate function.
- **Duplicate process detection**: `netstat -ano | grep ':9876 ' | grep LISTENING` to find stale PIDs, then `taskkill //F //PID <pid>` to clean up before restart. Background `sleep 999 | python server.py` processes accumulate across Hermes restarts. Kill ALL before starting a new one.
- **Phase D — Auto-negotiation (claim/release)**: POST `/claim` with `{session_id, path, ttl}` returns 200 (claimed) or 409 (conflict). POST `/release` with `{session_id, path}` frees claim. If pending requesters exist, ownership auto-transfers. Claims auto-expire after TTL seconds. Plugin auto-claims files before read/write operations. Dashboard shows active locks in 🔒 File Claims panel.
- **Phase F — Benchmarks scorecard**: GET `/benchmarks` returns auto-computed metrics from live data: pattern recall rate, knowledge accumulation, work tracking, tool efficiency. Serves as proof that LUMEN cognitive exoskeleton adds measurable value. Verdict: READY when chains > 0.
- **Cross-process state**: Dashboard server and MCP server are separate processes. Reload from `.thinking_state.json` on each `/metrics` request (check mtime).

## Chain Modal Pattern (GET /chain)

Server endpoint in `do_GET`:
```python
elif self.path.startswith("/chain"):
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(self.path).query)
    cid = qs.get("chain_id", [None])[0]
    # Returns: {chain_id, session, total_thoughts, thoughts: [{number, thought, score, is_revision, has_branch}]}
```

Client JS: `fetch('/chain?chain_id=X').then(r=>r.json()).then(c=>{...})`

## Benchmarks Endpoint Pattern

GET `/benchmarks` auto-computes from live data: pattern recall rate, knowledge accumulation, work tracking completion %, tool efficiency. Verdict: READY when chains > 0.

- **Cross-process state**: Dashboard server and MCP server are separate processes. Reload from `.thinking_state.json` on each `/metrics` request (check mtime).
- **Modal pattern**: Click handler does `fetch('/metrics')` to get full chain data, renders modal HTML. Close on overlay click or × button.
- **CORS**: Set `Access-Control-Allow-Origin: *` for Vercel-deployed dashboards.
- **Adaptive chart**: Don't always show 48 empty hours. Count non-zero hours and scale bars accordingly. Minimum 6 bars.
- **POST /wiki endpoint**: Must be added to `do_POST` method in `MetricsHandler`, NOT `do_GET`. Takes `{title, content, author}`, creates/updates `session.wiki[title]`, calls `_save_state()`.
- **State reload needs `global` in nested function**: `_build_metrics()` is defined inside `_start_dashboard()`. Both `_last_state_mtime` AND `_sessions` need `global` declarations for the state reload to work. Without `global _last_state_mtime`, the assignment creates a local variable and the state never reloads from disk (the mtime check always reads the startup value).
- **Dashboard HTML as Python raw string fails**: Embedding HTML in `r"""..."""` causes `SyntaxError` on em dashes (`—`) and `</script>` tags. Always serve dashboard HTML from a separate file (`dashboard.html`) loaded at startup.
- **CORS for cross-origin dashboards**: Set `Access-Control-Allow-Origin: *` on `/metrics` so the Vercel-deployed dashboard can fetch from localhost.

## Real Example

Deployed at `http://localhost:9876/` (local). Source in `lumen-protocol/implementations/mcp-servers/thinking/dashboard.html`.
Skynet mirror: `https://skynet-zeta.vercel.app/lumen-dash/dist/`. Source in `skynet/lumen-dash/`.
