---
name: lumen-thinking-server-dev
description: Build Lumen-native thinking servers with STREAM_DATA frames, MUX channels, and real-time token streaming. Windows-safe frame parsing.
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
| Token streaming | No (atoms of full messages) | **Yes (STREAM_DATA frames)** |
| MUX channels | No (single stream) | **Yes (parallel reasoning/assumptions/models)** |
| Client compatibility | Any MCP client | Lumen-aware clients only |
| Complexity | ~400 lines | ~500 lines |
| Windows | ✅ Works | ⚠️ `read(1)` pattern required |

---

## Architecture: Native Thinking Server

```
Client (Hermes)                    Server (server_native.py)
    │                                        │
    │── PROBE frame ──────────────────────→│
    │←── PROBE_ACK ───────────────────────│   negotiation
    │                                        │
    │── TYPE_REQUEST (compress(init)) ────→│
    │←── TYPE_RESPONSE (compress(result)) ─│   JSON-like but binary
    │                                        │
    │── TYPE_REQUEST (tools/call) ────────→│   "sequential_thinking"
    │←── STREAM_DATA chunk 1 ─────────────│   thought token 1
    │←── STREAM_DATA chunk 2 ─────────────│   thought token 2
    │←── STREAM_DATA chunk N ─────────────│   thought token N
    │←── TYPE_RESPONSE (final result) ────│   chain state
    │                                        │
    │    ┌─ MUX channel: reasoning          │
    │    ├─ MUX channel: assumptions        │
    │    ├─ MUX channel: model              │
    │    └─ MUX channel: work_tracking      │
    │                                        │
```

---

## Windows-Safe Frame Reading

Windows pipes: `sys.stdin.buffer.read(N)` blocks until N bytes **or EOF**.
Must read 1 byte at a time and accumulate.

```python
# ✅ Windows-safe LUMEN frame reader
from lumen import parse_frame, ParseComplete, decompress_value, FLAG_COMPRESSED

def read_lumen_frame() -> dict | None:
    """Read one LUMEN frame from stdin. Windows-safe (read 1 byte at a time)."""
    buf = bytearray()
    while True:
        b = sys.stdin.buffer.read(1)   # 1 byte — never blocks on Windows
        if not b:
            return None                 # EOF
        buf.extend(b)
        result = parse_frame(buf, 0)
        if isinstance(result, ParseComplete):
            frame = result.frame
            payload = frame.payload
            if frame.flags & FLAG_COMPRESSED:
                payload = decompress_value(payload)
            return payload              # Already a dict, NOT bytes
        # Continue accumulating...

# ✅ Sending a LUMEN frame
from lumen import build_frame, build_size, compress_value, TYPE_RESPONSE, FLAG_COMPRESSED

def send_lumen_frame(response: dict, frame_type: int = TYPE_RESPONSE) -> None:
    """Compress and send a LUMEN binary frame to stdout."""
    payload = compress_value(response)
    header = build_size(payload)        # ⚠️ Returns HEADER size, not total!
    buf = bytearray(header + len(payload))
    build_frame(frame_type, FLAG_COMPRESSED, payload, buf, 0)
    sys.stdout.buffer.write(buf)
    sys.stdout.buffer.flush()
```

---

## STREAM_DATA: Real-Time Thought Streaming

When the LLM generates a long thought, stream it token-by-token via STREAM_DATA frames:

```python
from lumen import TYPE_STREAM_DATA

def stream_thought(chain_id: str, thought: str, chunk_size: int = 50) -> None:
    """Stream a thought in chunks via STREAM_DATA frames."""
    tokens = thought.split()  # or character-level
    for i in range(0, len(tokens), chunk_size):
        chunk = " ".join(tokens[i:i+chunk_size])
        data = {
            "chainId": chain_id,
            "chunk": i // chunk_size,
            "text": chunk,
            "is_last": i + chunk_size >= len(tokens)
        }
        send_lumen_frame(data, TYPE_STREAM_DATA)
```

Client-side handler (in Hermes `_LumenSession`):
```python
async def _on_stream_data(self, data: dict) -> None:
    """Accumulate STREAM_DATA chunks into the chain display."""
    chain_id = data["chainId"]
    self._stream_buffers[chain_id] = self._stream_buffers.get(chain_id, "") + data["text"]
    if data.get("is_last"):
        # Thought complete — finalize
        final = self._stream_buffers.pop(chain_id)
        self.onmessage?.(final)
```

---

## MUX Channels: Parallel Cognitive Subsystems

LUMEN's MUX frames enable parallel logical channels:

```python
from lumen import TYPE_MUX, MUX_OPEN, MUX_DATA, MUX_CLOSE

MUX_CHANNELS = {
    0x01: "reasoning",
    0x02: "assumptions",
    0x03: "mental_model",
    0x04: "work_tracking",
}

def open_mux_channel(channel_id: int) -> None:
    """Open a MUX channel for parallel cognitive subsystem communication."""
    data = {
        "channel": channel_id,
        "name": MUX_CHANNELS.get(channel_id, "unknown"),
        "action": "open"
    }
    send_lumen_frame(data, MUX_OPEN)

def send_on_channel(channel_id: int, payload: dict) -> None:
    """Send data on a specific MUX channel."""
    payload["_channel"] = channel_id
    send_lumen_frame(payload, MUX_DATA)

def close_mux_channel(channel_id: int) -> None:
    data = {"channel": channel_id, "action": "close"}
    send_lumen_frame(data, MUX_CLOSE)
```

---

## PROBE/ACK Handshake (Native Server)

Native LUMEN servers MUST handle the PROBE/ACK handshake. Hermes sends a PROBE frame
first. The server must detect it and respond with PROBE_ACK BEFORE processing any
JSON-RPC messages.

```python
from lumen import TYPE_PROBE_ACK, build_probe, parse_ack, compress_value

def handle_probe_handshake() -> bool:
    """Handle LUMEN PROBE/ACK handshake. Returns True if LUMEN negotiated."""
    first_frame = read_lumen_frame()
    if first_frame is None:
        return False

    # PROBE frame has "protocol": "LUMEN" key
    if "protocol" in first_frame and first_frame.get("protocol") == "LUMEN":
        client_versions = first_frame.get("supported_versions", ["1.0"])
        accepted = "1.0" if "1.0" in client_versions else client_versions[0]

        ack_payload = compress_value({
            "protocol": "LUMEN",
            "server_name": "lumen-thinking-native",
            "accepted_version": accepted,
            "capabilities": ["compress", "stream", "mux"]
        })

        header = build_size(ack_payload)
        buf = bytearray(header + len(ack_payload))
        build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, ack_payload, buf, 0)
        sys.stdout.buffer.write(buf)
        sys.stdout.buffer.flush()
        return True

    # Not a PROBE frame — fallback to JSON-RPC or error
    if "method" in first_frame:
        # JSON-RPC message received — handle as normal
        handle_message(first_frame)
    return False
```

---

## Full Native Server Template

See `templates/server_native_thinking.py` for the complete reference implementation.

Key sections:
1. `read_lumen_frame()` — Windows-safe frame parser
2. `send_lumen_frame()` — Frame builder + compressor
3. `stream_thought()` — STREAM_DATA token streaming
4. `handle_probe_handshake()` — PROBE/ACK negotiation
5. `setup_mux_channels()` — MUX channel initialization
6. `main_loop()` — Read → dispatch → respond

---

## Benchmarking Framework

```python
import time, json
from lumen import compress_value

def benchmark_wire(server_path: str, test_file_path: str) -> dict:
    """Compare JSON-RPC vs LUMEN native wire savings on real data."""
    import subprocess

    # 1. Build JSON-RPC response
    with open(test_file_path) as f:
        content = f.read()
    json_resp = {
        "jsonrpc": "2.0", "id": 1,
        "result": {"content": [{"type": "text", "text": content}]}
    }
    json_bytes = len(json.dumps(json_resp).encode())

    # 2. Compress with LUMEN
    lumen_payload = compress_value(json_resp)
    header = build_size(lumen_payload)
    lumen_bytes = header + len(lumen_payload)

    # 3. Measure latency
    t0 = time.perf_counter()
    # ... built-in op ...
    t_builtin = (time.perf_counter() - t0) * 1000

    t0 = time.perf_counter()
    # ... LUMEN op (with subprocess overhead) ...
    t_lumen = (time.perf_counter() - t0) * 1000

    return {
        "json_bytes": json_bytes,
        "lumen_bytes": lumen_bytes,
        "wire_savings": (1 - lumen_bytes / json_bytes) * 100,
        "latency_builtin_ms": t_builtin,
        "latency_lumen_ms": t_lumen,
    }
```

**Honest assessment rule**: If LUMEN isn't clearly superior, say so. Don't push weak claims.

---

## Pitfalls

- `build_size()` returns HEADER size. Buffer = `build_size(payload) + len(payload)`
- `decompress_value()` returns dict, not bytes. Don't `json.loads()` it.
- Windows pipes: `read(1)` mandatory. `read(N)` blocks until N bytes or EOF.
- `stdin.flush()` may raise `OSError` on Windows — wrap in `try/except OSError`.
- STREAM_DATA frames: don't exceed MTU (~4096 bytes payload). Keep chunks sensible.
- MUX channels: limit to 16 concurrent channels (4 per subsystem, 4 subsystems).
- PROBE/ACK timeout: server must respond within 500ms (configurable via `probe_timeout_ms`).
- `server_native.py` duplicates 95% of `server.py`. Extract shared code to a common module.
