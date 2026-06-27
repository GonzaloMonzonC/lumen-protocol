# MCP Connection Debug — Windows, 2026-06-19

## Symptom
```
MCP: registered 0 tool(s) from 0 server(s) (3 failed)
CancelledError on all 3 servers (lumen_filesystem, lumen_thinking, lumen_web)
```
`hermes mcp list` shows servers as ✓ enabled, but no tools appear.

## Root cause
`transport: lumen` with `lumen_force_json_rpc: true` was causing `CancelledError` on Windows.
The LUMEN `LumenStdioTransport` binary wrapper failed to keep the stdin/stdout pipe open.

## Verification
Server responds correctly via plain stdin JSON-RPC:
```bash
echo '{"jsonrpc":"2.0","id":1,"method":"initialize",...}' | python server.py
# → {"jsonrpc":"2.0","id":1,"result":{...}} ✅
```

## Fix
```bash
hermes config set mcp_servers.lumen_thinking.transport stdio
hermes config set mcp_servers.lumen_filesystem.transport stdio
hermes config set mcp_servers.lumen_web.transport stdio
```
Then restart Hermes.

## Secondary issue: missing MCPLumenTransport alias
After a lumen package refactoring, `MCPLumenTransport` was renamed to `LumenStdioTransport`.
Hermes PR #47740 still references the old name. Fix by adding alias in `lumen/transport.py`:
```python
MCPLumenTransport = LumenStdioTransport
```
And reinstalling in the Hermes venv:
```bash
<hermes-venv>/pip install -e <lumen-protocol>/implementations/python
```

## Log evidence
From `~/AppData/Local/hermes/logs/agent.log`:
```
WARNING tools.mcp_tool: MCP server 'lumen_thinking' initial connection failed (attempt 1/3)
WARNING tools.mcp_tool: Failed to connect to MCP server 'lumen_thinking': CancelledError
INFO tools.mcp_tool: MCP: registered 0 tool(s) from 0 server(s) (3 failed)
```
