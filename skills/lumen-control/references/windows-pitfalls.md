# Windows-Specific Pitfalls for LUMEN Transport

Discovered during Hermes Agent integration testing on Windows 10, Python 3.11.

## 1. `stdin.flush()` — Cross-Platform Pipe Flush

**Symptom:** `OSError: [Errno 22] Invalid argument` on `self._process.stdin.flush()`

**Root cause:** Windows does not support flushing a pipe's stdin stream.

**Fix:** Wrap in try/except:
```python
def _flush_stdin(process):
    try:
        process.stdin.flush()
    except OSError:
        pass  # Windows: flushing stdin pipe may fail
```

**Affected files:** `lumen/transport.py` — 3 locations: `_send_jsonrpc()`,
`_send_lumen()`, `start()` probe.

## 2. `close()` Deadlock — Stdin Before Reader Cancel

**Symptom:** `close()` hangs forever (script times out at 300s).

**Root cause:** `close()` cancelled reader tasks and awaited them BEFORE
closing stdin. Reader tasks were blocked on `stdout.readline()` waiting
for the child process to exit. The child was blocked on `stdin.readline()`
waiting for input. Classic deadlock.

**Fix:** Close stdin FIRST, then cancel/await reader tasks:
```python
async def close(self):
    # Close stdin FIRST so the child process exits
    if self._process and self._process.stdin:
        self._process.stdin.close()
    # NOW cancel reader tasks
    if self._reader_task:
        self._reader_task.cancel()
```

## 3. `{**sys.executable, ...}` — String as Dict

**Symptom:** Would crash at runtime when `env` parameter is passed.

**Root cause:** `{**sys.executable, **self._env}` treats `sys.executable`
(a string like `C:\Python311\python.exe`) as a dict.

**Fix:** `{**os.environ, **self._env}` — merge with the actual OS environment.

## 4. `stdout.read(N)` — Blocks Until EOF on Windows Pipes

**Symptom:** Reader task blocks indefinitely, never receives JSON-RPC responses.

**Root cause:** On Windows pipes, `read(N)` blocks until N bytes are available
or EOF. JSON-RPC responses are typically smaller than N, and EOF never arrives
because the server stays alive for more requests.

**Fix:** Use `readline()` which returns at each newline — matching the
line-delimited JSON-RPC protocol:
```python
# BEFORE (broken on Windows):
chunk = await loop.run_in_executor(None, self._process.stdout.read, 65536)

# AFTER (correct):
chunk = await loop.run_in_executor(None, self._process.stdout.readline)
```

Applies to both `_read_jsonrpc` (stdout) and `_log_stderr` (stderr).

## 5. MCP Stdio Is NOT Thread-Safe

Multiple threads writing to the same subprocess stdin will interleave
JSON-RPC lines. MCP stdio is a single pipe — concurrent writes from
different threads produce garbage.

**Pattern:** Use sequential RPC calls, or implement a write lock per transport.

## 6. Cloudflare Workers Block Python `urllib`

**Symptom:** `HTTP 403: error code 1010` when testing the Worker from Python scripts.

**Root cause:** Cloudflare's Browser Integrity Check blocks non-browser user agents.
The Worker is fine — it responds correctly from browsers, curl, and Hermes.

**Workaround:** Test from a browser, `curl`, or the Hermes provider itself.
Python sandbox requests are blocked by the CDN, not our code.

## 7. LUMEN Native Binary Pipe — `read(4096)` Deadlock

**Symptom:** LUMEN native server hangs on startup — `read_lumen_frame()` blocks
forever, never reads the init frame. `test_native.py` also hangs.

**Root cause:** `sys.stdin.buffer.read(4096)` blocks until 4096 bytes OR EOF.
LUMEN frames are typically 50-200 bytes, and the pipe stays open. The `read()`
blocks indefinitely waiting for bytes that never arrive.

**Fix:** Read 1 byte at a time in the server's frame reader:
```python
# BEFORE (deadlocks on Windows):
chunk = sys.stdin.buffer.read(4096)

# AFTER (correct, Windows-safe):
b = sys.stdin.buffer.read(1)
```

For efficiency, this only applies to pipe (stdio) I/O. Socket I/O with
non-blocking modes doesn't have this issue.

**Affected files:** `server_native.py` — `read_lumen_frame()` function.
