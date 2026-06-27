# Windows Pipe Deadlock — The Full Fix (18/06/2026)

## The Problem

On Windows, `read(N)` on a pipe blocks until N bytes arrive or EOF. LUMEN frames are ~90 bytes. `read(4096)` blocks forever.

This deadlock affected **BOTH sides** of the LUMEN connection:

### Server side (`server_native.py`)
```python
# ❌ read_lumen_frame() — blocked forever
def read_lumen_frame():
    chunk = sys.stdin.buffer.read(4096)  # 💥 Windows: blocks until 4096B or EOF
    ...
```

### Client side (`transport.py`)
```python
# ❌ _wait_for_ack() — blocked forever
chunk = self._process.stdout.read(4096)  # 💥 Windows: blocks until 4096B or EOF

# ❌ _read_lumen() — used readline() for binary frames
chunk = self._process.stdout.readline()  # 💥 Binary frames may not contain newlines
```

## The Fix

**Read 1 byte at a time.** On Windows, `read(1)` returns as soon as 1 byte is available. The `FrameAssembler` accumulates 1-byte chunks and reconstructs frames.

### Server fix (`server_native.py`)
```python
# ✅ read_lumen_frame() — byte-by-byte
def read_lumen_frame():
    buf = bytearray()
    while True:
        b = sys.stdin.buffer.read(1)   # Returns immediately on Windows
        if not b:
            return None
        buf.extend(b)
        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            return result.frame.payload
        elif hasattr(result, 'needed'):
            continue  # Need more bytes
```

### Client fix (`transport.py`)
```python
# ✅ _wait_for_ack() — byte-by-byte
chunk = await loop.run_in_executor(
    None, self._process.stdout.read, 1    # read(1), not read(4096)!
)

# ✅ _read_lumen() — byte-by-byte (same pattern)
chunk = await loop.run_in_executor(
    None, self._process.stdout.read, 1    # read(1), not readline()!
)
```

## Why This Works

- `read(1)` on Windows pipes returns immediately with 1 byte (or blocks briefly until 1 byte arrives)
- `FrameAssembler.push()` accumulates chunks and yields frames via Hyb128 header parsing
- Overhead: ~64 syscalls per frame (~90 bytes). Negligible vs 500-5000ms LLM latency

## Reinstallation Required

After editing `transport.py`, reinstalling the `lumen` package is required for Hermes to pick up the fix:

```bash
cd lumen-protocol
pip install -e implementations/python
```

Then `/reset` in Hermes for the new transport to take effect.

## Config for Native LUMEN

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["server_native.py"]
    transport: lumen
    lumen_force_json_rpc: false  # Native LUMEN binary — no JSON-RPC wrapping
```

## Verification

After reset, check that filesystem tools appear with `lumen_force_json_rpc: false`. If they don't, the probe failed and fell back to JSON-RPC. Check `~/.hermes/logs/mcp-stderr.log` for probe-related errors.
