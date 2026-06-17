"""Hyb128 — Hybrid length encoding with O(1) decode. Optimized with struct + precomputed tables."""

from __future__ import annotations

import struct

# ── Constants ────────────────────────────────────────────────────────────────

MAX_SHORT: int = 0x3F
MAX_ENCODED_LEN: int = 11

_MODE_MASK: int = 0xC0
_SHORT_MASK: int = 0x3F
_MODE_SHORT: int = 0x00
_MODE_LEB128: int = 0x40
_MODE_U16: int = 0x80
_MODE_U32: int = 0xC0

# Pre-computed Hyb128 bytes for 0..63 (mode 00 short values)
_PRECOMPUTED_SHORT: list[bytes] = [bytes([i]) for i in range(64)]

# Pre-computed encoded lengths for 0..65535
_PRECOMPUTED_LEN: bytearray = bytearray(65536)
for i in range(64):
    _PRECOMPUTED_LEN[i] = 1
for i in range(64, 65536):
    _PRECOMPUTED_LEN[i] = 3
for i in range(65536, len(_PRECOMPUTED_LEN)):
    _PRECOMPUTED_LEN[i] = 5

# ── Encode ───────────────────────────────────────────────────────────────────

def encode_hyb128(value: int, buf: bytearray, offset: int = 0) -> int:
    """Encode *value* into *buf* at *offset*. Returns bytes written."""
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"hyb128.encode: value must be non-negative, got {value!r}")

    if value <= MAX_SHORT:
        buf[offset] = _MODE_SHORT | value
        return 1

    if value <= 0xFFFF:
        buf[offset] = _MODE_U16
        struct.pack_into("<H", buf, offset + 1, value)
        return 3

    if value <= 0xFFFFFFFF:
        buf[offset] = _MODE_U32
        struct.pack_into("<I", buf, offset + 1, value)
        return 5

    buf[offset] = _MODE_LEB128
    return 1 + _leb128_encode(value, buf, offset + 1)


def encoded_len(value: int) -> int:
    """Return bytes needed to encode *value* in Hyb128 (pre-computed for ≤65535)."""
    if value <= 0xFFFF:
        return _PRECOMPUTED_LEN[value]
    if value <= 0xFFFFFFFF:
        return 5
    return 1 + _leb128_len(value)


def encode_hyb128_bytes(value: int) -> bytes:
    """One-shot encode returning bytes."""
    if value <= MAX_SHORT:
        return _PRECOMPUTED_SHORT[value]
    buf = bytearray(MAX_ENCODED_LEN)
    n = encode_hyb128(value, buf, 0)
    return bytes(buf[:n])

# ── Decode ───────────────────────────────────────────────────────────────────

def decode_hyb128(data: bytes | bytearray | memoryview, offset: int = 0, strict: bool = False) -> tuple[int, int] | None:
    """Decode Hyb128 value. Returns (value, header_len) or None.

    Args:
        data: Raw bytes containing Hyb128-encoded value at *offset*.
        offset: Byte position to start decoding from.
        strict: If True, reject non-minimal encodings (e.g. value 10 encoded
                as U16 instead of Short). Non-strict mode is more lenient
                for backward compatibility.

    In strict mode, values that could have been encoded in a smaller mode
    are rejected — this prevents canonicalization bypass attacks and ensures
    deterministic wire format for hashing/dedup.
    """
    if offset >= len(data):
        return None

    first = data[offset]
    mode = first & _MODE_MASK

    if mode == _MODE_SHORT:
        return (first & _SHORT_MASK, 1)

    value: int
    header_len: int

    if mode == _MODE_U16:
        if offset + 3 > len(data):
            return None
        value = struct.unpack_from("<H", data, offset + 1)[0]
        header_len = 3
        if strict and value <= MAX_SHORT:
            return None  # should have been Short (1 byte)

    elif mode == _MODE_U32:
        if offset + 5 > len(data):
            return None
        value = struct.unpack_from("<I", data, offset + 1)[0]
        header_len = 5
        if strict and value <= 0xFFFF:
            return None  # should have been U16 or Short

    else:  # LEB128 fallback
        result = _leb128_decode(data, offset + 1)
        if result is None:
            return None
        value, leb_bytes = result
        header_len = 1 + leb_bytes
        if strict and value <= 0xFFFFFFFF:
            return None  # should have been U32 or lower

    return (value, header_len)

# ── LEB128 helpers ───────────────────────────────────────────────────────────

def _leb128_len(value: int) -> int:
    if value == 0:
        return 1
    count = 0
    while value:
        count += 1
        value >>= 7
    return count


def _leb128_encode(value: int, buf: bytearray, offset: int) -> int:
    start = offset
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            byte |= 0x80
        buf[offset] = byte
        offset += 1
        if not value:
            break
    return offset - start


def _leb128_decode(data: bytes | bytearray | memoryview, offset: int) -> tuple[int, int] | None:
    value = 0
    shift = 0
    i = offset
    for _ in range(10):
        if i >= len(data):
            return None
        byte = data[i]
        value |= (byte & 0x7F) << shift
        i += 1
        if not (byte & 0x80):
            return (value, i - offset + 1)  # +1 for the mode byte
        shift += 7
    return None
