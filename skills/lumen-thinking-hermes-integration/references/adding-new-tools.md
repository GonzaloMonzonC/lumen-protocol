# Adding New Tools to the Thinking Server

How to add a new cognitive tool and have it appear in the Hermes agent.

## The 5-Step Workflow

Every new tool needs **5 changes** across 2 files:

### 1. Tool Schema → `server.py` → `TOOLS[]`

Insert the tool schema dict **before** `] + OBJECTIVE_SCHEMAS`:

```python
# In TOOLS = [ ... ] + OBJECTIVE_SCHEMAS
TOOLS = [
    # ... existing tools ...
    {
        "name": "my_tool",
        "description": "What it does.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "param": {"type": "string", "description": "..."}
            },
            "required": ["param"]
        }
    },
] + OBJECTIVE_SCHEMAS
```

### 2. Handler Function → `server.py`

Insert a standalone function **before** `HANDLERS = {`:

```python
def tool_my_tool(args: dict) -> dict:
    \"\"\"Docstring.\"\"\"
    session = _get_session(args.get("session_id"))
    # ... logic ...
    _auto_save()
    return {"content": [{"type": "text", "text": "Result"}]}
```

### 3. Handler Mapping → `server.py` → `HANDLERS{}`

```python
HANDLERS = {
    # ... existing ...
    "my_tool": tool_my_tool,
}
```

### 4. Session Fields (if needed) → `server.py` → `class Session`

If the tool stores per-session state:

```python
# In __init__:
self.my_field = None

# In to_dict():
"my_field": self.my_field,

# In from_dict():
s.my_field = d.get("my_field", None)
```

### 5. Bridge Registration → `__init__.py` → `register()`

Add to the bridge plugin at `~/AppData/Local/hermes/plugins/lumen-shm-bridge/__init__.py`:

```python
ctx.register_tool(
    name="my_tool", toolset="lumen-shm",
    schema={"name":"my_tool","description":"...","parameters":{...}},
    handler=_make_thinking_handler("my_tool"),
)
```

### 6. Restart Hermes

A Hermes restart is required — `/reset` or MCP server reload does NOT refresh the bridge's tool list.

## Critical Pitfalls

| Pitfall | Why | Fix |
|---------|-----|-----|
| **Missing comma before `]`** | If the last tool before `] + OBJECTIVE_SCHEMAS` lacks a trailing comma, Python raises `SyntaxError: invalid syntax. Perhaps you forgot a comma?` | Add `,` after the previous tool's closing `}` |
| **SHM timeout on new tools** | After adding bridge registration but before restart, the bridge still has old tools. Calls to the new tool hang/timeout. | Restart Hermes |
| **Handler inside HANDLERS dict** | If the `def tool_...()` is placed between `HANDLERS = {` and `}`, Python raises `SyntaxError: invalid syntax`. | Place the def BEFORE `HANDLERS = {` |
| **`_auto_save()` takes no args** | `_auto_save()` is counter-based, not per-session. It does NOT accept a session argument. | Use `_auto_save()` not `_auto_save(session)` |
| **`_save_state()` references renamed variable `_PDB_SNAPSHOT_INTERVAL`** | After PDB-first migration (June 2026), `_PDB_SNAPSHOT_INTERVAL` was renamed to `_JSON_SNAPSHOT_INTERVAL`. Tools that call `_save_state()` directly (not via `_auto_save()`) fail with `NameError` if the old name lingers. | `grep _PDB_SNAPSHOT_INTERVAL server.py` and replace with `_JSON_SNAPSHOT_INTERVAL` |
| **`patch` tool silent failure** | On Windows, the LUMEN SHM-backed `patch` tool may silently fail to replace strings with special characters (emoji, unicode escapes) or absolute paths. | Use Python script with `str.replace()` or direct line editing via terminal |
