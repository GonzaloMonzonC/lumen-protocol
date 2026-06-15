# LUMEN — Python binding

Production-quality Python implementation of the **LUMEN binary protocol** for MCP (Model Context Protocol). Drop-in transports with automatic LUMEN negotiation and transparent JSON-RPC fallback.

## Architecture

Mirrors the TypeScript `@lumen/mcp-transport` package exactly:

| Module | File | Purpose |
|---|---|---|
| **Hyb128** | `hyb128.py` | Hybrid length codec (4 modes: 00 / 01 / 10 / 11) |
| **Dict** | `dict.py` | 128-entry static + 127 session dictionary, O(1) lookup |
| **Compress** | `compress.py` | Compact binary payload codec (8 value tags) |
| **Frame** | `frame.py` | Frame builder/parser (12 frame types, 4 flags) |
| **Frame Assembler** | `frame_assembler.py` | Zero-allocation streaming reassembler |
| **Negotiation** | `negotiation.py` | LUMEN probe/ack handshake |
| **Transport** | `transport.py` | Stdio + WebSocket drop-in MCP transports |
| **Cadencia** | `cadencia.py` | Rust sidecar bridge client |
| **Public API** | `__init__.py` | Single import surface |

## Status

| Component | Status |
|---|---|
| Hyb128 codec | 🟢 Done |
| Static dictionary | 🟢 Done — 128 static + 127 session |
| Binary compressor | 🟢 Done |
| Frame builder/parser | 🟢 Done |
| Frame assembler | 🟢 Done |
| Negotiation handshake | 🟢 Done |
| Stdio transport | 🟢 Done |
| WebSocket transport | 🟢 Done |
| Cadencia bridge | 🟢 Done |
| Test suite | ✅ 94/94 passing |

## Quick start

```python
from lumen import LumenStdioTransport, compress_value, decompress_value

# Standalone compress/decompress
payload = {"tool": "search", "arguments": {"query": "hello"}}
compressed = compress_value(payload)   # 47-55% smaller than JSON
restored = decompress_value(compressed)
assert restored == payload

# Use as MCP transport (drop-in replacement)
transport = LumenStdioTransport(command="python", args=["server.py"])
await transport.start()  # negotiates LUMEN, falls back to JSON-RPC
```

## Installation

```bash
cd implementations/python
pip install -e .            # core only
pip install -e ".[test]"    # with pytest + pytest-asyncio
pip install -e ".[websocket,test]"  # full install
```

## Running tests

```bash
cd implementations/python
python -m pytest tests/ -v
```

## Package structure

```
implementations/python/
├── pyproject.toml
├── README.md
├── src/
│   └── lumen/
│       ├── __init__.py          # Public API surface
│       ├── hyb128.py            # Hyb128 length codec
│       ├── dict.py              # 128-entry static dictionary
│       ├── compress.py          # Binary payload compressor
│       ├── frame.py             # Frame builder & parser
│       ├── frame_assembler.py   # Streaming reassembler
│       ├── negotiation.py       # Probe/ack handshake
│       ├── transport.py         # Stdio + WebSocket transports
│       └── cadencia.py          # Rust sidecar bridge
└── tests/
    ├── __init__.py
    └── test_lumen.py            # Comprehensive test suite
```

## Protocol

LUMEN v0.1.0. See `../../RFC_LUMEN.md` for the formal RFC or `../../SPEC_DEV.md` for the developer specification.

## License

MIT
