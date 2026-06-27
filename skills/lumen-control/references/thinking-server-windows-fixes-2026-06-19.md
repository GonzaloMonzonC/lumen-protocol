# 4 Critical Thinking Server Fixes — June 19, 2026

Session spent debugging the LUMEN thinking server on Windows. The server has 29 tools in server.py but only 7 were usable. Root cause was a cascade of Windows-specific bugs.

## Fix 1: UTF-8 stdout (`7ff1d86`)

**Symptom**: Hermes MCP client fails with `'utf-8' codec can't decode byte 0x97`. Server registered 0 tools.

**Root cause**: Thinking server uses rich emoji output (✅📋🔍⚠️🌉🏷️🧠). On Windows, `sys.stdout.encoding` defaults to `cp1252` when connected via pipe (subprocess), which doesn't support emoji. The filesystem server works because its output has no emoji.

**Fix**: Add after imports in `server.py`:
```python
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
```

## Fix 2: Main loop robustness (`e926a6d`)

**Symptom**: Server dies after a single bad tool call. `ClosedResourceError` in Hermes.

**Root cause**: `main()` only catches `json.JSONDecodeError`. Any other exception (KeyError in handler, BrokenPipeError in send) propagates and kills the server process.

**Fix**: Wrap the entire message processing loop in broad exception handling:
```python
except Exception as e:
    try:
        req_id = msg.get("id") if isinstance(msg, dict) else None
        send({"jsonrpc": "2.0", "id": req_id, "error": {...}})
    except Exception:
        pass  # Don't let error responses kill the server
```

## Fix 3: Defensive `thought_bridge` (`4bff185`)

**Symptom**: `thought_bridge` crashes with `KeyError: 'thought'` even though schema says `required: []`.

**Root cause**: Handler uses `args["thought"]` (bracket access) instead of `args.get("thought", "")`.

**Fix**: Change to `.get()` and add fallback error message.

## Fix 4: send() OSError protection (`ff53354`)

**Symptom**: After previous fixes, server still dies occasionally. `ClosedResourceError`.

**Root cause**: `send()` calls `sys.stdout.flush()` which raises `OSError: [Errno 22]` on Windows when the pipe is broken. This exception escapes the handler's try/except.

**Fix**: Wrap send() in try/except:
```python
def send(msg: dict) -> None:
    try:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    except (OSError, BrokenPipeError, ValueError):
        pass
```

## Result

After all 4 fixes: server stable, 7 core tools respond reliably, 0 crashes. Remaining 22 tools are registered in Hermes but not exposed to agent due to prompt caching (separate issue).
