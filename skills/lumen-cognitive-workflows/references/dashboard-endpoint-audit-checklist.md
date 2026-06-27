# Dashboard Endpoint Audit Checklist

Run this checklist after every dashboard or server change to verify all endpoints
are functional and the dashboard is serving the correct HTML.

## Prerequisites
- Kill ALL stale processes on port first:
  ```bash
  netstat -ano | grep ":9879\|:9876" | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid 2>/dev/null; done
  ```
- Use port 9879 to avoid conflict with bridge's auto-spawned server on 9876
- Start fresh server (Python pipe keeps stdin alive):
  ```bash
  cd <repo>/implementations/mcp-servers/thinking && python -c "import time; time.sleep(999)" | python -u server_shm.py --dashboard 9879
  ```

## Endpoint Tests

```bash
# GET endpoints
for ep in "/" "/metrics" "/kanban" "/kanban/stats" "/chain?chain_id=<existing_id>"; do
  printf "%-30s " "$ep"
  python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1',9879)); s.sendall(b'GET $ep HTTP/1.0\r\nHost:127.0.0.1\r\n\r\n'); d=s.recv(100); print(d.split(b'\\r\\n')[0]); s.close()"
done
```

## Dashboard HTML Integrity

```bash
# Fetch via raw socket (HTTP/1.0 — avoids HTTP library quirks)
python -c "
import socket
s = socket.socket(); s.settimeout(5)
s.connect(('127.0.0.1', 9879))
s.sendall(b'GET / HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
data = b''
while True:
    chunk = s.recv(4096)
    if not chunk: break
    data += chunk
print(f'Served: {len(data)} bytes')
# Check key panels exist
panels = [b'Agent Loop', b'Kanban', b'Reasoning', b'System Pulse', b'Activity']
for p in panels:
    print(f'  {\"✓\" if p in data else \"✗\"} {p.decode()}')
"
```

## Metrics Data Check

```bash
python -c "
import socket, json
s = socket.socket(); s.settimeout(5)
s.connect(('127.0.0.1', 9879))
s.sendall(b'GET /metrics HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n')
data = b''
while True:
    chunk = s.recv(4096)
    if not chunk: break
    data += chunk
header, _, body = data.partition(b'\r\n\r\n')
d = json.loads(body)
print('Keys:', sorted(d.keys()))
print('Totals:', json.dumps(d.get('totals',{}), indent=2))
if 'objectives' in d:
    print(f'Objectives: {len(d[\"objectives\"])}')
    for o in d['objectives']:
        print(f'  {o[\"id\"]}: {o[\"title\"][:30]} — {o[\"phase\"]}/{o[\"score\"]}')
"
```

## Dashboard Panel Verification

```javascript
// In browser console:
const panels = ['objectives-list','kanban-board','chains-list','works-list','wiki-list'];
panels.forEach(id => {
  const el = document.getElementById(id);
  console.log(id + ': ' + (el ? '✓ exists, ' + el.children.length + ' children' : '✗ MISSING'));
});
```

## Common Failures

### 1. Cross-process state file corruption 🔥
**Symptom**: Kanban shows 0 niches/0 tasks even though `niche_list` returns real data.
**Root cause**: TWO server processes compete for `.thinking_state.json`:
  - Bridge thinking server (auto-spawned on port 9876 by plugin) — handles MCP tool calls
  - Dashboard HTTP server (manually started with `--dashboard`) — serves web UI
  When dashboard's `/kanban` handler calls `_save_state()`, it OVERWRITES the bridge's state
  with its own in-memory data (which may be empty/stale).
**Fix**: Kanban GET handler must NEVER call `_save_state()`. Only reload from file:
  ```python
  # BAD: self._save_state() before reload → overwrites bridge state
  # GOOD: just reload from file
  with open(_STATE_FILE) as f:
      state = json.load(f)
  ```

### 2. mtime comparison bug
**Symptom**: Kanban changes not reflected after page refresh.
**Root cause**: `if _fm > _g.get('_last_state_mtime', 0.0)` — `_build_metrics()` sets
  `_last_state_mtime` to the file's mtime, so the next kanban read sees `_fm == _last_state_mtime`
  and skips the reload (because `>` not `>=`).
**Fix**: Always reload from file unconditionally for kanban reads. Remove mtime check entirely.

### 3. New panels need both HTML div AND JS render code
**Symptom**: Panel not visible despite having JS rendering code.
**Root cause**: Dashboard JS calls `document.getElementById('panel-id')` but the HTML
  doesn't have the corresponding `<div id="panel-id">`. No error thrown — just silent.
**Fix**: Always verify: `document.getElementById('expected-panel-id') !== null` in browser console.

### 4. New /metrics fields crash _build_metrics()
**Symptom**: `GET /metrics` returns empty (connection closes without response),
  while `GET /` serves dashboard HTML fine.
**Root cause**: New field references a variable not in scope (e.g. `_objectives` is
  in `objective_loop.py`, not `server.py`). Import inside `_build_metrics()`:
  ```python
  def _build_metrics():
      try:
          from objective_loop import _objectives
      except ImportError:
          _objectives = {}
  ```

### 5. HTTP/1.0 vs HTTP/1.1 library quirks
**Symptom**: `http.client` or `urllib` get `RemoteDisconnected` but raw socket works.
**Root cause**: Python's HTTP client library uses HTTP/1.1 with connection keep-alive.
  The dashboard's `BaseHTTPRequestHandler` handles HTTP/1.0 differently.
**Fix**: Use raw socket with `HTTP/1.0` for testing, or set `Connection: close` header.

### 6. Port conflict with bridge server
**Symptom**: Dashboard server starts and immediately exits. Port shows LISTENING but
  HTTP requests get empty response.
**Root cause**: Bridge plugin auto-spawns thinking server on port 9876 WITHOUT dashboard.
  Manual dashboard server on same port can't bind or conflicts.
**Fix**: Use port 9879 for dashboard server. Kill all processes on the port first.
