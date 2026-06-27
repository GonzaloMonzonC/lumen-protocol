# Windows charmap Encoding Fix for LUMEN MCP Servers

**Discovered**: June 2026, Windows 10, Python 3.11

## Problem

MCP servers crash silently on Windows when tool output contains any Unicode
character beyond ASCII (U+007F). The crash manifests as:

```
'charmap' codec can't encode character '\U0001f4ca' in position 78
```

This happens because:
1. Python on Windows defaults stdout to `charmap` (Windows-1252) encoding
2. MCP servers use `json.dumps(msg, ensure_ascii=False)` to write to stdout
3. When tool output contains emoji (`📊`, `✅`, `🔧`), box-drawing (`═`, `─`, `█`),
   or web content with accented characters (ñ, café, naïve), the encode fails
4. The `send()` function crashes → server dies → Hermes gets `ClosedResourceError`

## Affected Servers

All 3 LUMEN MCP servers were affected:
- **filesystem**: `list_directory` (📁📄), `server_stats` (📊█), `read_files` (═══), `search_with_context` (───)
- **web**: `web_search` results with accented web content
- **thinking**: Already had the fix from initial version (line 40: `sys.stdout.reconfigure(encoding="utf-8")`)

## Fix (applied June 2026)

### Primary fix: UTF-8 stdout

```python
# At the top of server.py, BEFORE any output:
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
```

Applied to:
- `implementations/mcp-servers/filesystem/server.py`
- `implementations/mcp-servers/web/server.py`

### Secondary fix: ASCII-safe output

Even with UTF-8 configured, some terminals and pipe readers don't handle
emoji/box-drawing characters. Replace them in tool output:

| Unicode | Replacement | Used in |
|---------|-------------|---------|
| `📁` `📄` | `[DIR]` `[FILE]` | `list_directory` |
| `📖` | `FILE:` | `stream_read` |
| `📊` | (removed) | `server_stats` |
| `🏁` | `[FINAL CHUNK]` | `stream_read` |
| `█` | `#` | `server_stats` bar chart |
| `═══` | `===` | `read_files` header |
| `───` | `---` | `search_with_context` block |

Applied to `implementations/mcp-servers/filesystem/shared_tools.py`.

## Verification

```python
# Test with Unicode query
server.stdin.write(json.dumps({
    'jsonrpc':'2.0','id':1,'method':'tools/call',
    'params':{'name':'server_stats','arguments':{}}
}) + '\n')
# Should return without 'charmap' error
```

## Pitfall

The thinking server had this fix from day one (line 39-41 of server.py).
New servers must include it from the start, not as a retroactive fix.

## Related

- `lumen-server-development` skill — Windows Unicode section in Pitfall Checklist
- `references/mcp-retry-recovery.md` — Recovering after 4 consecutive failures
