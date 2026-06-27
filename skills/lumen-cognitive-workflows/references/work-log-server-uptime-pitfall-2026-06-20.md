# Work Log Server Uptime Pitfall (2026-06-20)

## Problem
Work items persist as `in_progress` even after calling `work_done`. The work log shows:
- 8 items `in_progress`
- But `work_done(work_id=X)` returns success

## Root Cause
The thinking server was **not running**. The `lumen-shm-bridge` plugin spawns the thinking server as a subprocess, but:
1. Server processes don't survive Hermes restart
2. No auto-restart mechanism
3. When server is down, tool calls succeed but can't persist to `_sessions` state

## Diagnosis
Check server uptime BEFORE using work tools:
```
state_snapshot()  # Shows "10c · 32t · 10.0★ · 23p · 16w · 302 calls"
                  # If uptime is 0s, server is down
```

Or check HTTP endpoint:
```
curl http://127.0.0.1:9876/metrics | grep uptime
# Shows "uptime_seconds": 0 when server is down
```

## Fix
Start the thinking server before work operations:
```bash
cd /path/to/lumen-protocol/implementations/mcp-servers/thinking
python server.py --dashboard 9876
# Verify: curl http://127.0.0.1:9876/metrics shows non-zero uptime
```

## Verification
After starting server, call `work_done` again:
```python
_handle_thinking_tool("work_done", {"work_id": 4, "result": "Done"})
work_log()  # Should now show updated status
```

## Key Learnings
1. **Work log persistence requires live server** - intentional design for cross-session collaboration
2. **SHM transport works even with dead server** - calls route through plugin but state can't persist
3. **Always verify server before cleanup** - especially after context compaction or system restart
4. **The HTTP endpoint state is authoritative** - `curl` shows real persistence state vs cached tool output