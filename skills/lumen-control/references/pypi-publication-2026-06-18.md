# PyPI Publication — lumen-mcp 0.1.0

**Date**: June 17, 2026  
**Status**: ✅ Published  
**Package**: https://pypi.org/project/lumen-mcp/

## Package Details

- **Name**: `lumen-mcp`
- **Version**: `0.1.0`
- **Python**: ≥ 3.10
- **License**: MIT
- **Author**: Gonzalo Monzón (gonzalo@cadenceslab.com)

## What's Included

All LUMEN protocol modules:
- `hyb128.py` — Hybrid length codec
- `dict.py` — 128-entry static dictionary + 127 session dictionary
- `compress.py` — Binary payload compressor
- `frame.py` — Frame builder/parser (12 frame types)
- `frame_assembler.py` — Zero-allocation streaming reassembler
- `negotiation.py` — PROBE/ACK handshake
- `transport.py` — Stdio + WebSocket transports
- `cadencia.py` — Rust sidecar bridge

## Installation

```bash
pip install lumen-mcp
```

## Windows Fixes Included

The published package includes the Windows pipe deadlock fixes:
- `transport.py`: `read(1)` instead of `read(4096)` / `readline()`
- Works on Windows, Mac, Linux

## Build Command

```bash
cd implementations/python
python -m build       # creates dist/lumen_mcp-0.1.0-py3-none-any.whl
twine upload dist/*   # uploads to PyPI
```
