# MCP Server Retry Exhaustion — Recovery Technique

**Bug observed**: June 2026, Windows 10, Hermes Agent with LUMEN MCP servers.

## Symptom

MCP server tools return `ClosedResourceError` or `unreachable after N consecutive failures`.
The server works perfectly when tested directly via subprocess, but Hermes refuses
to reconnect.

In the MCP stderr log (`~/AppData/Local/hermes/logs/mcp-stderr.log`), the server
shows rapid restarts:
```
===== [2026-06-19 02:18:54] starting MCP server 'lumen_web' =====
===== [2026-06-19 02:18:56] starting MCP server 'lumen_web' =====
===== [2026-06-19 02:18:58] starting MCP server 'lumen_web' =====
===== [2026-06-19 02:19:02] starting MCP server 'lumen_web' =====
```

After 4 failures in 8 seconds, Hermes stops trying permanently. A subsequent
`/reset` does NOT restart the server.

## Root Cause

Hermes's MCP client has a failure counter per server. After N consecutive
failures (N=4 observed), it marks the server as permanently failed and won't
retry on `/reset`.

The actual failure was a `charmap` encoding crash in the server (Unicode
character in `json.dumps(ensure_ascii=False)` output on Windows stdout pipe).

## Recovery Procedure

```bash
# Toggle the server off then on to reset the failure counter
hermes config set mcp_servers.<server_name>.enabled false
hermes config set mcp_servers.<server_name>.enabled true
```

Then `/reset` in the chat. The server will be reconnected.

## Prevention

- Add `sys.stdout.reconfigure(encoding="utf-8")` to all MCP servers (see
  `references/windows-encoding-fix.md`)
- Replace Unicode emoji/box-drawing characters in tool output with ASCII
- Test servers with Unicode-heavy queries before deploying

## Related

- `lumen-control` skill — Troubleshooting section
- `references/windows-encoding-fix.md` — The root cause fix
- `lumen-server-development` skill — Pitfall checklist
