# Work Log Persistence Requirements

## Key Insight

The `work_block`, `work_done`, and `work_log` tools **require the thinking server to be running**. These tools delegate to `_handle_thinking_tool()` which connects to the thinking MCP server via SHM.

## Behavior When Server is Down

- `work_log` reads from persisted state (works even when server is down - shows cached state)
- `work_block` and `work_done` **fail silently** when the thinking server is not running (SHM connection fails)
- Tasks remain in `in_progress` status forever until the server processes the tool call

## Diagnostic

If `work_log` shows tasks stuck in `in_progress` after calling `work_done`:

```bash
# Check if server is running
curl http://localhost:9876/metrics

# If server not running, start it:
python implementations/mcp-servers/thinking/server.py --dashboard 9876
```

## Verified Behavior (June 20 2025)

1. `server_stats` returns "Uptime: 0h 0m 0s, Requests: 0" when no server active
2. `work_done` with block_id returns no error but cannot persist
3. `work_log` still returns cached/loaded state from previous sessions

## Related Patterns

- `stale-dashboard-processes.md` — Kill zombies on port 9876
- `state-file-locking.md` — When HTTP dashboard and MCP server share state via same file
- `work-tracking-troubleshooting.md` — Multi-session work flow debugging