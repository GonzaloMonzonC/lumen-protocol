# LUMEN Cognitive Kanban — Implementation Reference

> Implemented June 2026 | 7 tools + HTTP endpoints + Dashboard panel

## Architecture

```
Hermes Agent → Plugin (lumen-shm-bridge) → SHM transport → Thinking Server (server.py)
                                                                     ↓
                                                              HTTP Dashboard (:9876)
                                                                     ↓
                                                              kanban.html panel
```

## Server-Side: Adding a Kanban Tool (Pattern)

Every kanban tool follows this pattern:

### 1. Handler function (server.py)

```python
def tool_<name>(args: dict) -> dict:
    global _niches, _tasks  # global state
    # Validate params with args.get()
    param = args.get("param", default)
    # Perform operation on global state
    _save_state()  # persist
    return {"content": [{"type": "text", "text": result}]}
```

### 2. HANDLERS dict (server.py)

```python
HANDLERS = {
    ...
    "<tool_name>": tool_<name>,
}
```

### 3. Plugin registration (lumen-shm-bridge/__init__.py)

```python
ctx.register_tool(
    name="<tool_name>", toolset="lumen-shm",
    schema={"name": "<tool_name>", "description": "...", "parameters": {...}},
    handler=_make_thinking_handler("<tool_name>"),
)
```

## HTTP Endpoints (server.py do_GET/do_POST)

### GET /kanban

Returns all niches and tasks (optionally filtered by niche_id):

```python
elif self.path == "/kanban" or self.path.startswith("/kanban?"):
    from urllib.parse import urlparse, parse_qs
    qs = parse_qs(urlparse(self.path).query)
    niche_id = qs.get("niche_id", [None])[0]
    niches_list = [...]
    tasks_list = [
        # include references (chains, patterns, decisions) for 🔗 badges
    ]
    data = {"niches": niches_list, "tasks": tasks_list}
    body = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")
    # send response with CORS headers
```

### POST /kanban/move

Move a task between columns OR create a new task (when `to_column="_create"`):

```python
elif self.path == "/kanban/move":
    params = json.loads(raw)
    task_id = params.get("task_id", "").strip()
    to_column = params.get("to_column", "").strip()
    if to_column == "_create":
        # Create new task (for dashboard "New Task" button)
        new_id = f"task_{_next_task_id}"
        _next_task_id += 1
        _tasks[new_id] = {...}
        _save_state()
    else:
        # Move existing task
        task = _tasks[task_id]
        task["status"] = to_column
        task["updated_at"] = time.time()
        _save_state()
```

## Dashboard Panel (dashboard.html)

### HTML Structure

```html
<div class="glass"><h3 class="section-toggle" onclick="toggleSection('kanban-content')">
  <span class="arrow">▼</span> 📋 Kanban <span class="summ" id="summary-kanban"></span>
</h3>
<div class="collapsible" id="kanban-content" style="max-height:3000px">
  <div style="display:flex;gap:8px;margin-bottom:12px;align-items:center;flex-wrap:wrap">
    <span style="font-size:11px;font-weight:600">Niche:</span>
    <select id="kanban-niche" onchange="loadKanban()">...</select>
    <button class="btn btn-acc" onclick="showNewTaskForm()">+ New Task</button>
  </div>
  <div id="kanban-board" style="display:flex;gap:8px;overflow-x:auto;min-height:200px">
    <!-- Column rendering via JS -->
  </div>
</div></div>
```

### JS Rendering (loadKanban function)

```javascript
function loadKanban() {
  const sel = document.getElementById('kanban-niche');
  const url = sel.value ? '/kanban?niche_id='+encodeURIComponent(sel.value) : '/kanban';
  fetch(url).then(r=>r.json()).then(d=>{
    _kanbanNiches = d.niches || [];
    _kanbanTasks = d.tasks || [];
    renderKanban();
  });
}
```

### Drag-and-Drop

```javascript
// Cards: <div draggable="true" data-task-id="task_1" data-column="Backlog"
//        ondragstart="kanbanDrag(event)">

function kanbanDrag(e) {
  e.dataTransfer.setData('text/plain', e.target.getAttribute('data-task-id') + '|' + e.target.getAttribute('data-column'));
}
function kanbanDrop(e) {
  const data = e.dataTransfer.getData('text/plain').split('|');
  fetch('/kanban/move', {
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({task_id: data[0], to_column: targetColumn})
  }).then(r=>r.json()).then(res=>{ if(res.status==='ok') loadKanban(); });
}
```

## Data Model

### Niche (global, stored in `_niches` dict)

```python
niche = {
    "id": "niche_1",
    "name": "lumen-protocol",
    "desc": "LUMEN Protocol development",
    "color": "#22d3ee",
    "columns": ["Backlog", "In Progress", "Review", "Done", "Blocked"],
    "archived": False,  # niche_update can set to True
    "created_at": 1234567890.0,
    "updated_at": 1234567890.0
}
```

### Task (global, stored in `_tasks` dict)

```python
task = {
    "id": "task_1",
    "niche_id": "niche_1",
    "title": "Fase C Auto-negotiation",
    "desc": "Implement /negotiate endpoint",
    "status": "Backlog",  # must be one of niche["columns"]
    "priority": "high",   # low / medium / high / critical
    "tags": ["core", "api"],
    "assignee": None,     # or session_id string
    "references": {
        "chains": ["chain_11_..."],
        "patterns": [],
        "decisions": [],
        "wikis": []
    },
    "blockers": [],
    "blocks": [],
    "created_at": ..., "updated_at": ..., "done_at": None
}
```

## Tools List Summary (7 tools)

| Tool | Parameters | Required |
|------|-----------|----------|
| niche_create | name, desc, color, columns | name |
| niche_list | (none) | - |
| niche_update | niche_id, name, desc, color, archived | niche_id |
| task_create | niche_id, title, desc, priority, tags, assignee | niche_id, title |
| task_move | task_id, to_column, title, desc, priority, tags, assignee | task_id |
| task_link | task_id, chain_id, pattern_id, decision_id, wiki_id | task_id |
| task_list | niche_id, status, tag, search, limit | (none) |

## Pitfalls

- **Port conflicts**: Stale zombie processes on port 9876 cause "Not found" responses even when the server is running. Use `netstat -ano | grep <port>` to check. Use alternative ports like 54321.
- **Permission errors on Windows**: Some ports are firewalled. Use high ports (50000+) for reliability.
- **Global state persistence**: New global variables (_niches, _tasks) MUST be added to BOTH _save_state() AND _load_state() with `global` declarations. Missing either causes data to disappear on restart.
- **Plugin must be restarted**: Changing the plugin __init__.py requires Hermes restart or session reload for new tools to appear.
- **Self-match in thought_contradiction**: The similarity algorithm includes self-match. When linking a task to a chain, the chain's own thoughts may trigger false positives.
