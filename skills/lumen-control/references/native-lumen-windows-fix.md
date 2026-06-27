# LUMEN Native Binary on Windows — Deadlock Fix

**Date**: June 18, 2026  
**Status**: ✅ Fixed and deployed

## Problem

Native LUMEN binary transport (lumen_force_json_rpc: false) failed on Windows.
The PROBE handshake timed out because both client and server used `read(N)` or
`readline()` on Windows pipes, which block until N bytes or EOF.

## Root Causes (3 bugs)

### Bug 1: Server `read_lumen_frame()` — already fixed
`server_native.py` line 460: already used `read(1)` byte-at-a-time.
This was correct. No fix needed here.

### Bug 2: Client `_wait_for_ack()` — transport.py
`transport.py` line 335: `self._process.stdout.read(4096)` blocked on Windows
pipes because PROBE_ACK frames are ~100 bytes, never reaching 4096.

**Fix**: `read(4096)` → `read(1)` byte-at-a-time.
The `FrameAssembler` accumulates 1-byte chunks and parses complete frames.

### Bug 3: Client `_read_lumen()` — transport.py
`transport.py` line 242: `self._process.stdout.readline()` blocked on Windows
because binary LUMEN frames don't contain newlines.

**Fix**: `readline()` → `read(1)` byte-at-a-time.

## Server-Side Fix

### Bug 4: No PROBE handler
`server_native.py` `process_message()` only handled JSON-RPC methods.
No handler for LUMEN PROBE frames.

**Fix**: Added PROBE detection and PROBE_ACK response:
```python
if "protocol" in msg and msg.get("protocol") == "LUMEN":
    ack = {
        "protocol": "LUMEN",
        "server_name": "lumen-filesystem-native",
        "accepted_version": "1.0",
    }
    return {"__lumen_ack__": True, "ack": ack}
```

And updated `send_lumen_frame()` to handle `__lumen_ack__` marker with
`TYPE_PROBE_ACK` frame type.

## Verification

After fixes, Hermes Agent successfully connects to the filesystem server
via native LUMEN binary transport on Windows 10.

```
Config: lumen_force_json_rpc: false
Result: filesystem ● ONLINE (native LUMEN) 9 tools
```
