# LUMEN Native vs Wrapper — Architecture Decision

## Two Server Patterns

### Pattern A: JSON-RPC over LUMEN (`server.py`, `force_json_rpc=True`)

```
Hermes → LUMEN frame → [decompress] → JSON-RPC text → server.py → OS
                  ← LUMEN frame ← [compress]   ← JSON-RPC text ←
```

- Server speaks plain JSON-RPC via stdio (text mode)
- Hermes wraps JSON lines in LUMEN binary frames
- 32-60% wire savings (JSON keys compressed by LUMEN dictionary)
- ✅ Simple to write — any MCP SDK server works
- ✅ Debuggable — JSON is human-readable
- ❌ No MUX channels (single stream)
- ❌ No STREAM_DATA (responses are atomic)

### Pattern B: LUMEN Native (`server_native.py`, `force_json_rpc=False`)

```
Hermes → LUMEN frame → server_native.py → OS
                  ← LUMEN frame ←
```

- Server reads/writes LUMEN binary frames directly
- No JSON-RPC text wrapping at any layer
- 50-70% wire savings (no structural JSON overhead at all)
- ✅ MUX channels ready (multiple concurrent streams)
- ✅ STREAM_DATA ready (large files in chunks)
- ❌ Harder to write — custom frame parsing needed
- ❌ Harder to debug — pure binary frames

## Key Implementation Details (Pattern B)

### Reading frames from stdin

```python
def read_lumen_frame() -> dict | None:
    """Read a LUMEN frame from stdin (binary mode)."""
    from lumen import ParseIncompletePayload
    buf = bytearray()
    while True:
        chunk = sys.stdin.buffer.read(4096)
        if not chunk: return None
        buf.extend(chunk)
        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload  # Already a dict from decompress_value
        elif hasattr(result, 'needed'):
            continue  # Read more bytes
        else:
            return None
```

### Writing frames to stdout

```python
def send_lumen_frame(response: dict) -> None:
    """Build a LUMEN frame and write to stdout (binary mode)."""
    if response is None: return
    payload = compress_value(response)
    header_size = build_size(payload)  # HEADER ONLY!
    total_size = header_size + len(payload)
    buf = bytearray(total_size)
    build_frame(TYPE_RESPONSE, FLAG_COMPRESSED, payload, buf, 0)
    sys.stdout.buffer.write(buf)
    sys.stdout.buffer.flush()
```

### ⚠️ CRITICAL PITFALL: `build_size` returns header, not total

```python
# WRONG — buffer too small, IndexError at runtime
buf = bytearray(build_size(payload))
build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)

# CORRECT — total = header + payload
header_size = build_size(payload)
total_size = header_size + len(payload)
buf = bytearray(total_size)
build_frame(TYPE_REQUEST, FLAG_COMPRESSED, payload, buf, 0)
```

`build_size(payload)` returns the size of the Hyb128-encoded header (size prefix + type byte + flags byte), NOT the total frame size. The frame format is:
```
[Hyb128(payload_len)][TYPE:1B][FLAGS:1B][PAYLOAD:payload_len bytes]
```

This mistake caused `IndexError: bytearray index out of range` during development. The error is silent until the frame is built — no compile-time warning.

### `decompress_value` returns dict, not bytes

```python
# WRONG — decompress_value already returns a dict
payload = decompress_value(frame.payload)
msg = json.loads(payload)  # TypeError!

# CORRECT — decompress_value IS the message
msg = decompress_value(frame.payload)  # Already a dict
```

## When to Choose Each Pattern

| Use Pattern A (JSON-RPC) when... | Use Pattern B (Native) when... |
|---|---|
| Quick prototype or testing | Production deployment |
| Need debuggable output | Multi-agent with MUX channels |
| Server needs to work with non-LUMEN clients | Streaming large data (STREAM_DATA) |
| Using standard MCP SDK (no custom I/O) | Maximum wire savings required |
