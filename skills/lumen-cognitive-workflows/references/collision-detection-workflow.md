# Cross-Session Collision Detection Workflow

**Implemented**: June 2026  
**Skills used**: lumen-server-development, lumen-cognitive-workflows

## Architecture

```
Plugin (lumen-shm-bridge)          Thinking Server (dashboard)
├── read_file/write_file handler    ├── POST /touch
│   └── calls POST /touch ───────→ │   └── _file_touches.append({session_id, path, ts})
│                                  ├── GET /collisions
│                                  │   └── Group by file path, detect ≥2 sessions in <5min
│                                  ├── .thinking_state.json
│                                  │   └── Shared between dashboard + MCP server processes
│                                  └── Dashboard panel: ⚠️ Collisions
```

## Plugin Integration

```python
# In lumen-shm-bridge plugin handlers:
import urllib.request, json as _json

def _touch_file(session_id: str, filepath: str):
    try:
        req = urllib.request.Request("http://127.0.0.1:9876/touch",
            data=_json.dumps({"session_id": session_id, "path": filepath}).encode(),
            headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=0.5)
    except: pass  # dashboard server might not be running — no-op

# In read_file handler:
def _handle_filesystem_read_file(*args, **kwargs):
    params = args[0] if args else kwargs
    path = params.get("path", "")
    if path: _touch_file("default", path)
    ...
```

## Collision Detection Logic

```python
# GET /collisions — in MetricsHandler.do_GET
now = time.time(); window = 300  # 5 minutes
by_file = defaultdict(list)
for t in _file_touches:
    if now - t["timestamp"] < window:
        by_file[t["path"]].append(t)
collisions = []
for path, touches in by_file.items():
    sessions = set(t["session_id"] for t in touches)
    if len(sessions) > 1:
        collisions.append({"path": path, "sessions": list(sessions), "count": len(touches)})
```

## Pitfalls

- **Dashboard server must be running**: Plugin touches are no-op if dashboard isn't on port 9876
- **GET + POST both needed**: Dashboard fetches via GET, plugin sends via POST. Both endpoints required.
- **Time window is 5 minutes**: Touches older than 5min are ignored for collision detection
- **Max 500 touches**: Oldest entries trimmed to prevent memory bloat
