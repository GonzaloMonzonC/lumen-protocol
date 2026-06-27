# Dashboard Server Standalone Mode Fix

> **Issue (June 2026)**: `server.py --dashboard 9876` exits immediately when launched via `terminal(background=true)` because stdin closes.

## Root Cause

```python
while True:
    line = sys.stdin.readline()  # ← blocks waiting for MCP messages
    if not line:                 # ← stdin EOF → None → BREAK
        break                    # ← exits main → daemon threads die
```

The HTTP dashboard runs as a `threading.Thread(daemon=True)`. When the main loop exits, daemon threads are terminated immediately.

## Fix Applied

Added `--standalone` flag detection and auto-detection when `--dashboard` is passed without a TTY:

```python
standalone = "--standalone" in sys.argv or (
    "--dashboard" in sys.argv and not sys.stdin.isatty()
)
while True:
    try:
        line = sys.stdin.readline() if not standalone else None
    except Exception:
        break
    if not line and not standalone:
        break
    if standalone:
        try:
            time.sleep(1)
            continue
        except KeyboardInterrupt:
            break
    # ... MCP message handling ...
```

## Usage

```bash
# Background mode (auto-enters standalone):
terminal(background=true, command="python server.py --dashboard 9876")

# Explicit standalone (same result):
terminal(background=true, command="python server.py --dashboard 9876 --standalone")
```

## Verification

```bash
curl -s http://127.0.0.1:9876/metrics | head -20
# → Should return JSON with server version, uptime, sessions
```

Exit code 7 (Failed to connect to host) = server not running. Check `process(action='poll')` — if status is "exited" immediately, the fix wasn't applied.
