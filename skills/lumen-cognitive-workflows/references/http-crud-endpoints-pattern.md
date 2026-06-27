# Extending LUMEN Thinking Server with HTTP CRUD Endpoints

**Pattern from June 19, 2026 session**: Wiki Mental phase — added model CRUD
endpoints to the existing MetricsHandler HTTP server in `server.py`.

## Architecture

The thinking server already has a lightweight HTTP server (`MetricsHandler`
extending `http.server.BaseHTTPRequestHandler`) running on a daemon thread
(port 9876 by default). Extending it with new endpoints follows this pattern:

```python
class MetricsHandler(_http.BaseHTTPRequestHandler):
    def do_GET(self):
        # ... existing routes ...
        elif self.path.startswith("/model"):
            # GET /model or GET /model?entity=X
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            entity_name = qs.get("entity", [None])[0]
            session = _sessions.get(session_id, _sessions.get(_DEFAULT_SESSION))
            # ... return JSON ...

    def do_POST(self):
        if self.path.startswith("/model"):
            content_len = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_len) if content_len else b'{}'
            params = json.loads(body)
            action = params.get("_action", "upsert")  # upsert or delete
            # ... modify session.model ...

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
```

## Key Pitfalls

1. **CORS**: Dashboard makes cross-origin requests → MUST add
   `Access-Control-Allow-Origin: *` header AND a `do_OPTIONS` handler for
   preflight. Without OPTIONS, browsers block POST requests from dashboard HTML.

2. **Session isolation**: HTTP endpoints use `_sessions.get(session_id)` with
   fallback to `_DEFAULT_SESSION`. Pass `session_id` in query params if you want
   per-session model isolation.

3. **State persistence**: Call `_save_state()` after mutating model state so the
   dashboard and agent see the same data. The auto-save (every 10 tool calls)
   won't trigger from HTTP endpoints alone.

4. **Path handling**: Normalize entity paths with `entity.replace("\\", "/")`
   for cross-platform consistency — the mental model stores paths with forward
   slashes.

5. **DELETE via POST**: `http.server` doesn't have `do_DELETE` by default.
   Use `_action: "delete"` in the POST body as a workaround.

## Endpoints Added

| Method | Path | Body | Returns |
|--------|------|------|---------|
| GET | `/model` | — | All entities as `{entity: {role, deps, dependents, notes, properties}}` |
| GET | `/model?entity=X` | — | Single entity JSON or 404 |
| POST | `/model` | `{entity, role?, deps?, notes?, properties?, _action?}` | `{action: "created"/"updated"/"deleted", entity}` |
| OPTIONS | `/model` | — | CORS headers |

## Extending `model_add` with `properties`

```python
# In tool_model_add() — add to session.model[entity] dict:
"properties": dict(params.get("properties", {})) if isinstance(params.get("properties"), dict) else {},
```

And update the plugin schema in `lumen-shm-bridge/__init__.py`:
```python
"properties": {"type": "object", "description": "arbitrary key-value properties"},
```

This allows storing arbitrary metadata on entities: `{"owner": "team-A", "sla": "99.9", "lang": "rust"}`.
