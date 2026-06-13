"""
Hyb128 — Hybrid length encoding with O(1) decode.

Encoding scheme
---------------
Byte 0: ``[MODE:2bits][PAYLOAD:6bits]``

=====  =====  ====================================  ===========
Mode   Bits   Meaning                               Total bytes
=====  =====  ====================================  ===========
``00`` ``00`` Payload is the 6 lower bits (0..63)   1
``01`` ``01`` Next bytes are LEB128 continuation     2–11
``10`` ``10`` Next 2 bytes are u16 little-endian     3
``11`` ``11`` Next 4 bytes are u32 little-endian     5
=====  =====  ====================================  ===========

Ported from TypeScript ``src/hyb128.ts`` and Rust ``src/hyb128.rs``.
"""

from __future__ import annotations

# ═══ Constants ═══════════════════════════════════════════════════════════════

MAX_SHORT: int = 0x3F  # 63 — maximum value encodable in mode 00
MAX_ENCODED_LEN: int = 11  # 1 mode byte + up to 10 LEB128 bytes

_MODE_MASK: int = 0xC0
_SHORT_MASK: int = 0x3F
_MODE_SHORT: int = 0x00  # 00______
_MODE_LEB128: int = 0x40  # 01______
_MODE_U16: int = 0x80  # 10______
_MODE_U32: int = 0xC0  # 11______


# ═══ Encode ══════════════════════════════════════════════════════════════════

def encode_hyb128(value: int, buf: bytearray, offset: int = 0) -> int:
    """Encode *value* into *buf* at *offset*.

    Returns the number of bytes written (1, 3, 5, or variable for LEB128).
    Raises :exc:`ValueError` if *value* is negative or the buffer is too small.

    >>> buf = bytearray(11)
    >>> encode_hyb128(42, buf)
    1
    >>> buf[0]
    42
    >>> encode_hyb128(1000, buf)
    3
    """
    if not isinstance(value, int) or value < 0:
        raise ValueError(
            f"hyb128.encode: value must be a non-negative integer, got {value!r}"
        )

    # Mode 00: 6-bit short (0–63)
    if value <= MAX_SHORT:
        buf[offset] = _MODE_SHORT | (value & _SHORT_MASK)
        return 1

    # Mode 10: u16 little-endian (64 – 65535)
    if value <= 0xFFFF:
        buf[offset] = _MODE_U16
        buf[offset + 1] = value & 0xFF
        buf[offset + 2] = (value >> 8) & 0xFF
        return 3

    # Mode 11: u32 little-endian (65536 – 4294967295)
    if value <= 0xFFFFFFFF:
        buf[offset] = _MODE_U32
        buf[offset + 1] = value & 0xFF
        buf[offset + 2] = (value >> 8) & 0xFF
        buf[offset + 3] = (value >> 16) & 0xFF
        buf[offset + 4] = (value >> 24) & 0xFF
        return 5

    # Mode 01: LEB128 fallback (extremely rare — values > 4 GiB)
    buf[offset] = _MODE_LEB128
    return 1 + _leb128_encode(value, buf, offset + 1)


def encoded_len(value: int) -> int:
    """Return the number of bytes needed to encode *value* in Hyb128.

    >>> encoded_len(0)
    1
    >>> encoded_len(1000)
    3
    >>> encoded_len(1000000)
    5
    """
    if value <= MAX_SHORT:
        return 1
    if value <= 0xFFFF:
        return 3
    if value <= 0xFFFFFFFF:
        return 5
    # LEB128: at most 11
    return 1 + _leb128_len(value)


def encode_hyb128_bytes(value: int) -> bytes:
    """One-shot encode returning a new :class:`bytes` object.

    >>> encode_hyb128_bytes(42)
    b'*'
    >>> encode_hyb128_bytes(1000)
    b'\\x80\\xe8\\x03'
    """
    buf = bytearray(MAX_ENCODED_LEN)
    n = encode_hyb128(value, buf, 0)
    return bytes(buf[:n])


# ═══ Decode ══════════════════════════════════════════════════════════════════

def decode_hyb128(data: bytes | bytearray | memoryview, offset: int = 0) -> tuple[int, int] | None:
    """Decode a Hyb128 value from *data* at *offset*.

    Returns ``(value, header_len)`` or ``None`` if the data is incomplete.

    >>> decode_hyb128(b'\\x2a')
    (42, 1)
    >>> decode_hyb128(b'\\x80\\xe8\\x03')
    (1000, 3)
    """
    if offset >= len(data):
        return None

    first = data[offset]
    mode = first & _MODE_MASK

    # Mode 00: 6-bit value
    if mode == _MODE_SHORT:
        return (first & _SHORT_MASK, 1)

    # Mode 10: u16 LE
    if mode == _MODE_U16:
        if offset + 3 > len(data):
            return None
        value = data[offset + 1] | (data[offset + 2] << 8)
        return (value, 3)

    # Mode 11: u32 LE
    if mode == _MODE_U32:
        if offset + 5 > len(data):
            return None
        value = (
            data[offset + 1]
            | (data[offset + 2] << 8)
            | (data[offset + 3] << 16)
            | (data[offset + 4] << 24)
        )
        return (value, 5)

    # Mode 01: LEB128 continuation
    return _leb128_decode(data, offset + 1)


# ═══ LEB128 helpers ═══════════════════════════════════════════════════════════

def _leb128_len(value: int) -> int:
    """Number of bytes needed for LEB128 encoding of *value*."""
    if value == 0:
        return 1
    count = 0
    while value > 0:
        count += 1
        value >>= 7
    return count


def _leb128_encode(value: int, buf: bytearray, offset: int) -> int:
    """Encode *value* as unsigned LEB128 into *buf* at *offset*.

    Returns number of bytes written.
    """
    start = offset
    while True:
        byte = value & 0x7F
        value >>= 7
        if value != 0:
            byte |= 0x80
        buf[offset] = byte
        offset += 1
        if value == 0:
            break
    return offset - start


def _leb128_decode(data: bytes | bytearray | memoryview, offset: int) -> tuple[int, int] | None:
    """Decode unsigned LEB128 starting at *offset*.

    Returns ``(value, total_bytes_consumed_from_offset)`` or ``None``.
    """
    value = 0
    shift = 0
    i = offset
    for _ in range(10):  # safety cap
        if i >= len(data):
            return None
        byte = data[i]
        i += 1
        value |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            # total bytes consumed = i - offset + 1 for the mode byte
            return (value, i - offset + 1)
        shift += 7
        if shift >= 64:
            return None
    return None
