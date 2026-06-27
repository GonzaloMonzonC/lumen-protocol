# Dashboard Metrics Wiring Pattern

## Adding a new data module to the LUMEN dashboard

Three parallel changes needed when adding a new state module to `/metrics` + `dashboard.html`:

### 1. `server.py` — `_build_metrics()` return dict

Add the data key inside the return dict. The module's state variable must be imported inside the function (not at module level) using `try/except ImportError`:

```python
def _build_metrics():
    try:
        from objective_loop import _objectives     # ← import inside function
    except ImportError:
        _objectives = {}                           # ← fallback to empty
    return {
        ...
        "objectives": [{                           # ← new key
            "id": o["id"],
            "title": o["title"][:60],
            "phase": o["phase"],
            "score": o.get("score", 0),
            "tasks_done": sum(1 for t in o.get("tasks",[]) if t.get("status")=="done"),
            "tasks_total": len(o.get("tasks",[])),
            "criteria": len(o.get("criteria",[])),
            "created_at": o.get("created_at", 0),
        } for o in _objectives.values()],
    }
```

**Pitfall**: Putting the `try/except` block directly inside the dict literal causes `SyntaxError`. Always import at the top of `_build_metrics()`.

### 2. `dashboard.html` — HTML section

Add a collapsible section with the correct `id` for JS targeting:

```html
<div class="glass">
  <h3 class="section-toggle" onclick="toggleSection('objectives-content')">
    <span class="arrow">▼</span> 🎯 Agent Loop
    <span class="summ" id="summary-objectives"></span>
  </h3>
  <div class="collapsible" id="objectives-content" style="max-height:3000px">
    <div id="objectives-list">
      <div class="dim">No data yet</div>
    </div>
  </div>
</div>
```

### 3. `dashboard.html` — JS `renderData()` function

Add rendering code inside `renderData()`:

```javascript
const objectives = d.objectives||[];
const ol = document.getElementById('objectives-list');
if(ol) {
  document.getElementById('summary-objectives').textContent =
    objectives.filter(o=>o.phase==='done').length + '/' + objectives.length + ' done';
  ol.innerHTML = objectives.map(o => {
    const phaseIcon = {builder:'🔵',building:'⚙️',testing:'🧪',done:'✅'}[o.phase]||'❓';
    return '<div class="card">' +
      '<div><span>' + phaseIcon + ' <strong>' + o.title + '</strong></span>' +
      '<span style="float:right;color:' + (o.score>=8?'var(--green)':o.score>=5?'var(--yellow)':'var(--red)') + '">' + o.score + '/10</span></div>' +
      '<div style="font-size:10px;color:var(--dim)">' + o.phase.toUpperCase() + '</div>' +
      '</div>';
  }).join('');
}
```

## Testing the dashboard on Windows

`curl`, `http.client`, and `urllib` can all fail with connection errors even when the server is running. Use raw sockets with `HTTP/1.0`:

```python
import socket, json
s = socket.socket()
s.settimeout(5)
s.connect(("127.0.0.1", 9879))
s.sendall(b"GET /metrics HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
data = b""
while True:
    chunk = s.recv(4096)
    if not chunk: break
    data += chunk
header, _, body = data.partition(b"\r\n\r\n")
d = json.loads(body)
```
