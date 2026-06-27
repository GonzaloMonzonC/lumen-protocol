# LUMEN Transport Diagnostic (Hermes venv)

Quick check to verify the LUMEN transport classes are importable from Hermes's venv Python.

**Run this when ALL LUMEN tools disappear after a Hermes restart.**

## Quick test

```bash
# Use the Hermes venv Python (Windows path):
C:/Users/gonzalo/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -c "
from lumen.transport import LumenStdioTransport
print('✅ LumenStdioTransport OK')
"
```

If you see `ImportError: cannot import name 'MCPLumenTransport'`, the Hermes integration code is referencing a renamed class. Update it to use `LumenStdioTransport`.

## What to check

1. **Transport class name**: `LumenStdioTransport` (current) vs `MCPLumenTransport` (deprecated)
2. **Package location**: `lumen.transport` in the Hermes venv's site-packages
3. **Hermes MCP integration file**: Search for `MCPLumenTransport` in Hermes codebase

## Full venv diagnostic

```bash
C:/Users/gonzalo/AppData/Local/hermes/hermes-agent/venv/Scripts/python.exe -c "
import lumen.transport as t
names = [n for n in dir(t) if not n.startswith('_')]
print('Available in lumen.transport:')
for n in sorted(names):
    print(f'  {n}')
"
```

Expected output should include `LumenStdioTransport`. If only `LumenWebSocketTransport` appears, the stdio transport may be missing from the installed version.
