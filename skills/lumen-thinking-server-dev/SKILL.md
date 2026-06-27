---
name: lumen-thinking-server-dev
description: '👽 Build Lumen-native thinking servers with STREAM_DATA frames, MUX channels, and real-time token streaming. Windows-safe frame parsing. LUMEN tools marked 👽 in chat.'
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, thinking, server, native, streaming, mux]
---

# Lumen Thinking Server — Native Development

Building `server_native.py` for the thinking server. Lumen binary frames directly
(no JSON-RPC wrapping), enabling STREAM_DATA token streaming and MUX channel
multiplexing.

**Target**: 50-80% wire savings, real-time thought streaming, parallel reasoning channels.

---

## Why Native? JSON-RPC Wrapper vs Lumen Native

| | JSON-RPC Wrapper (`server.py`) | Lumen Native (`server_native.py`) |
|---|---|---|
| Wire savings | 32-60% | **50-80%** |
| Token streaming | No | **Yes (STREAM_DATA)** |
| MUX channels | No | **Yes (parallel channels)** |
| Client compatibility | Any MCP client | Lumen-aware clients only |
| Complexity | ~400 lines | ~500 lines |

---

## Windows-Safe Frame Reading

```python
def read_lumen_frame() -> dict | None:
    buf = bytearray()
    while True:
        b = sys.stdin.buffer.read(1)   # 1 byte — never blocks on Windows
        if not b: return None
        buf.extend(b)
        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload
```

## STREAM_DATA: Real-Time Thought Streaming

```python
def stream_thought(chain_id: str, thought: str, chunk_size: int = 50) -> None:
    tokens = thought.split()
    for i in range(0, len(tokens), chunk_size):
        chunk = " ".join(tokens[i:i+chunk_size])
        data = {"chainId": chain_id, "chunk": i // chunk_size,
                "text": chunk, "is_last": i + chunk_size >= len(tokens)}
        send_lumen_frame(data, TYPE_STREAM_DATA)
```

## MUX Channels: Parallel Cognitive Subsystems

```python
MUX_CHANNELS = {
    0x01: "reasoning", 0x02: "assumptions",
    0x03: "mental_model", 0x04: "work_tracking",
}
```

## PROBE/ACK Handshake

Native LUMEN servers MUST handle PROBE/ACK before any JSON-RPC messages.

```python
def handle_probe_handshake() -> bool:
    first_frame = read_lumen_frame()
    if first_frame and first_frame.get("protocol") == "LUMEN":
        # Respond with PROBE_ACK
        ack_payload = compress_value({
            "protocol": "LUMEN", "server_name": "lumen-thinking-native",
            "accepted_version": "1.0", "capabilities": ["compress", "stream", "mux"]
        })
        header = build_size(ack_payload)
        buf = bytearray(header + len(ack_payload))
        build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, ack_payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()
        return True
    return False
```

## Pitfalls

- `build_size()` returns HEADER size. Buffer = `build_size(payload) + len(payload)`
- `decompress_value()` returns dict, not bytes. Don't `json.loads()` it.
- Windows pipes: `read(1)` mandatory. `read(N)` blocks until N bytes or EOF.
- PROBE/ACK timeout: server must respond within 500ms.
- `server_native.py` duplicates 95% of `server.py` — extract shared code.
- **Main loop exits on stdin close**: The MCP server's main loop reads `sys.stdin.readline()`. When no stdin is connected (e.g., running standalone or as a background process), `readline()` returns None and the loop exits, killing the dashboard daemon thread. Fix: add a `--standalone` flag that replaces `break` with `time.sleep(1); continue` when stdin is not a TTY or `--standalone` is passed. Add the check at the top of the main loop: `standalone = "--standalone" in sys.argv or ("--dashboard" in sys.argv and not sys.stdin.isatty())`.