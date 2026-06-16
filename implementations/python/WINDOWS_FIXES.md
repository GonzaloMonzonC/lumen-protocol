# Windows Compatibility Fixes

Applied during integration testing with Hermes Agent on Windows 10, Python 3.11.

## Fix 1: `stdin.flush()` → `_flush_stdin()` helper
**Symptom:** `OSError: [Errno 22] Invalid argument` on `self._process.stdin.flush()`  
**Root cause:** Windows does not support flushing a pipe's stdin stream.  
**Fix:** `_flush_stdin(process)` wraps `process.stdin.flush()` in try/except OSError.  
**Files:** `src/lumen/transport.py`

## Fix 2: `close()` deadlock
**Symptom:** `close()` hangs forever, script times out at 300s.  
**Root cause:** `close()` cancelled reader tasks and awaited them BEFORE closing stdin.
Reader tasks were blocked on `stdout.readline()` waiting for the child process
to exit. The child process was blocked on `stdin.readline()` waiting for input.
Classic deadlock.  
**Fix:** Close `stdin` FIRST so the child exits, then cancel/await reader tasks.  
**Files:** `src/lumen/transport.py` (`LumenStdioTransport.close()`)

## Fix 3: `env` construction with `sys.executable`
**Symptom:** Would crash on startup when `env` parameter is passed.  
**Root cause:** `{**sys.executable, **self._env}` treats `sys.executable` (a string
like `C:\Python311\python.exe`) as a dict — this would raise `TypeError` at
runtime.  
**Fix:** `{**os.environ, **self._env}` — merge with the actual OS environment dict.  
**Files:** `src/lumen/transport.py` (`LumenStdioTransport.start()`)

## Fix 4: `stdout.read(N)` → `stdout.readline()`
**Symptom:** Reader task blocks indefinitely, never receives JSON-RPC responses.  
**Root cause:** On Windows pipes, `read(N)` blocks until N bytes are available
or EOF. JSON-RPC responses are typically smaller than the buffer size (65536),
and EOF never arrives because the server stays alive for more requests.  
**Fix:** Use `readline()` which returns at each newline — matching the
line-delimited JSON-RPC protocol. Applied to both `_read_jsonrpc` (stdout) and
`_log_stderr` (stderr).  
**Files:** `src/lumen/transport.py`

---

All fixes are backward-compatible with Linux/macOS.
