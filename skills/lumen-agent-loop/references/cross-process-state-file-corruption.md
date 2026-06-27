# Cross-Process State File Corruption

## The Problem

The LUMEN thinking server runs in TWO processes:
1. **Bridge thinking server** — SHM-native process spawned by `lumen-shm-bridge` plugin. Handles tool calls from Hermes.
2. **Dashboard HTTP server** — spawned separately with `--dashboard` flag (e.g. `server_shm.py --dashboard 9879`). Serves `/metrics`, `/kanban`, `/model` HTTP endpoints.

Both processes share `.thinking_state.json` as the serialization file for state (niches, tasks, objectives, chains, etc.).

## The Bug (June 2026)

The `GET /kanban` handler in `server.py` (MetricsHandler.do_GET) had this code:

```python
# Old buggy code:
_save_state()  # ☠️ Saves THIS process's in-memory state to file
# then reload from file...
```

When the dashboard process called `_save_state()` before reading the kanban data, it **overwrote the state file** with its own in-memory `_niches` and `_tasks` dicts. Since the dashboard process had no tool calls modifying kanban data, its dicts were often **empty or stale** — destroying changes made by the bridge process.

## The Fix

```python
# Fixed: no _save_state() before read-only GET
# Just reload from file unconditionally:
if _STATE_FILE.exists():
    with open(_STATE_FILE) as f:
        st = json.load(f)
    _niches = st.get("niches", {})
    _tasks = st.get("tasks", {})
```

**Rule**: Read-only HTTP endpoints must NEVER call `_save_state()`. Only POST handlers that modify state (like `/kanban/move`) should save.

## mtime Bug

The original code also used a conditional reload:

```python
if _fm > _g.get('_last_state_mtime', 0.0):
    # reload...
```

This skipped reload when `_fm == _last_state_mtime`, which happened frequently because `_build_metrics()` (called by `GET /metrics`) updated `_last_state_mtime` to the file's current mtime. Since the file hadn't changed between the two reads, `_fm == _last_state_mtime` and the kanban handler got stale data.

**Fix**: Always reload from file unconditionally in the kanban handler.

## Symptoms

- Dashboard shows "0 niches, 0 tasks" even though `niche_list` shows real data
- Task moves via drag-and-drop appear to succeed but don't persist on page refresh
- `_save_state()` from the bridge process works (verified by tool calls) but dashboard shows nothing

## Verification

1. Create a niche via tool: `niche_create(name="test")`
2. Wait for auto-save (10 tool calls) or call any tool to trigger `_get_session()`
3. Check `/kanban` endpoint — should show 1 niche. If 0, the GET handler is corrupting state.
4. After fix: `/kanban` always shows current state from file.
