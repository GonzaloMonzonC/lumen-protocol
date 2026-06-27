# State File Race Condition — Fix

## Problem

Dashboard server and MCP server share `.thinking_state.json`. The dashboard writes its in-memory `_sessions` dict on each `_save_state()` call. If the MCP server created wiki pages or chains that the dashboard server hasn't reloaded yet, the dashboard overwrites them with its stale copy.

## Root Cause

`_build_metrics()` in the dashboard HTTP handler checks `file_mtime > _last_state_mtime` to decide whether to reload state from disk. But the function lacks `global _last_state_mtime`, so the assignment `_last_state_mtime = file_mtime` creates a LOCAL variable instead of updating the module-level global. The comparison `file_mtime > _last_state_mtime` always reads the original startup value (from `_load_state()`), and since the file mtime hasn't changed since startup, state is NEVER reloaded.

## Fix

Add `global _last_state_mtime` at the top of `_build_metrics()`:

```python
def _build_metrics():
    global _last_state_mtime  # ← THIS LINE IS CRITICAL
    # Reload state from file if it was updated by another process
    if _STATE_FILE.exists():
        try:
            file_mtime = _STATE_FILE.stat().st_mtime
            if file_mtime > _last_state_mtime:
                # ... reload _sessions from file
                _last_state_mtime = file_mtime  # Now actually updates the global
```

Also add to `_load_state()`:
```python
def _load_state():
    global _last_state_mtime  # Already present
    # ... load state ...
    _last_state_mtime = _STATE_FILE.stat().st_mtime if _STATE_FILE.exists() else 0.0
```

## Verification

After the fix:
1. Start dashboard server: `python server.py --dashboard 9876`
2. Create wiki page via MCP: `wiki_create(title="test", content="hello")`
3. Hit `/metrics` — wiki should appear immediately (state reload detects newer mtime)
4. Verify state file is NOT overwritten with empty wiki on server save

## Recovery (when state file already overwritten)

If the dashboard already overwrote MCP-created data (wiki pages, chains with scores), recreate via POST:

```bash
# Recreate wiki pages
curl -X POST http://localhost:9876/wiki \
  -H "Content-Type: application/json" \
  -d '{"title":"LUMEN Architecture","content":"# Architecture\n...","author":"hermes-agent"}'

# Verify persistence
curl http://localhost:9876/metrics | jq '.wiki'
```

## Related Issues

- **Duplicate PIDs on port 9876**: Multiple `sleep 999 | python server.py --dashboard 9876` processes accumulate across Hermes restarts. Use `netstat -ano | grep ':9876 ' | grep LISTENING` + `taskkill //F //PID <pid>` before starting a new one.
- **Works visible but wiki not**: Works persist because they were loaded at startup (before wiki was added). Wiki added later by MCP never appears because state reload is broken by the `global` bug.
