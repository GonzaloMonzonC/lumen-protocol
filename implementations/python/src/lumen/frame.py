"""
Frame — LUMEN binary frame builder and parser.

Frame format::

    [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]

Hyb128 encodes PAYLOAD length only (not TYPE+FLAGS).

Ported from TypeScript ``src/frame.ts`` and Rust ``src/frame.rs``.
"""

from __future__ import annotations

import struct
from typing import NamedTuple

from .hyb128 import decode_hyb128, encode_hyb128, encoded_len as hyb128_encoded_len

# ═══ Frame Types ══════════════════════════════════════════════════════════════

TYPE_REQUEST: int = 0x01
TYPE_RESPONSE: int = 0x02
TYPE_NOTIFY: int = 0x03
TYPE_STREAM_DATA: int = 0x04
TYPE_SCHEMA_PATCH: int = 0x05
TYPE_STREAM_INIT: int = 0x06
TYPE_DICT_SYNC: int = 0x07
TYPE_DISCOVER: int = 0x08
TYPE_MUX: int = 0x09
TYPE_HEARTBEAT: int = 0x0A
TYPE_PROBE: int = 0x0F
TYPE_PROBE_ACK: int = 0x10

_TYPE_NAMES: dict[int, str] = {
    TYPE_REQUEST: "REQUEST",
    TYPE_RESPONSE: "RESPONSE",
    TYPE_NOTIFY: "NOTIFY",
    TYPE_STREAM_DATA: "STREAM_DATA",
    TYPE_SCHEMA_PATCH: "SCHEMA_PATCH",
    TYPE_STREAM_INIT: "STREAM_INIT",
    TYPE_DICT_SYNC: "DICT_SYNC",
    TYPE_DISCOVER: "DISCOVER",
    TYPE_MUX: "MUX",
    TYPE_HEARTBEAT: "HEARTBEAT",
    TYPE_PROBE: "PROBE",
    TYPE_PROBE_ACK: "PROBE_ACK",
}

# ═══ Frame Flags ══════════════════════════════════════════════════════════════

FLAG_COMPRESSED: int = 0x01
FLAG_ENCRYPTED: int = 0x02
FLAG_PRIORITY: int = 0x04
FLAG_FRAGMENTED: int = 0x08


# ═══ Frame struct ═════════════════════════════════════════════════════════════


class Frame(NamedTuple):
    """A parsed LUMEN frame header + payload reference."""

    frame_type: int
    """Frame type (see TYPE_* constants)."""
    flags: int
    """Bitmask of FLAG_*."""
    payload: bytes
    """Payload bytes — a copy for Python (no zero-copy across the GIL)."""


# ═══ ParseResult ══════════════════════════════════════════════════════════════


class ParseComplete(NamedTuple):
    frame: Frame
    consumed: int


class ParseIncompletePayload(NamedTuple):
    expected: int
    available: int


class ParseError(NamedTuple):
    message: str


ParseResult = ParseComplete | ParseIncompletePayload | type(ParseIncomplete)

# Sentinel for incomplete parse (not enough header bytes yet).
ParseIncomplete = type("ParseIncomplete", (), {})()


# ═══ Builder ══════════════════════════════════════════════════════════════════


def build_frame(
    frame_type: int,
    flags: int,
    payload: bytes | bytearray,
    buf: bytearray | None = None,
    offset: int = 0,
) -> bytes:
    """Build a LUMEN frame.

    If *buf* is given, write into it at *offset*; otherwise allocate a new
    :class:`bytes` object.
    """
    header_len = hyb128_encoded_len(len(payload))
    total = header_len + 2 + len(payload)

    if buf is None:
        buf = bytearray(total)

    n = encode_hyb128(len(payload), buf, offset)
    buf[offset + n] = frame_type
    buf[offset + n + 1] = flags
    buf[offset + n + 2 : offset + total] = payload

    return bytes(buf[offset : offset + total])


def build_size(payload_len: int) -> int:
    """Total buffer size needed for a frame with the given payload length."""
    return hyb128_encoded_len(payload_len) + 2 + payload_len


# ═══ Parser ═══════════════════════════════════════════════════════════════════


def parse_frame(data: bytes | bytearray | memoryview, offset: int = 0) -> ParseResult:
    """Attempt to parse one LUMEN frame from *data* at *offset*.

    Returns:
        - :class:`ParseComplete` — frame parsed successfully
        - ``ParseIncomplete`` — not enough data for header
        - :class:`ParseIncompletePayload` — header parsed but payload incomplete
        - :class:`ParseError` — malformed data
    """
    if offset >= len(data):
        return ParseIncomplete

    # Decode Hyb128 length
    decoded = decode_hyb128(data, offset)
    if decoded is None:
        return ParseIncomplete

    payload_len, header_len = decoded

    # Check that TYPE + FLAGS + payload fit
    needed = header_len + 2 + payload_len
    available = len(data) - offset

    if available < needed:
        return ParseIncompletePayload(expected=needed, available=available)

    # Read TYPE and FLAGS
    type_pos = offset + header_len
    frame_type = data[type_pos]
    flags = data[type_pos + 1]

    # Extract payload
    payload_start = type_pos + 2
    payload = (
        data[payload_start : payload_start + payload_len].tobytes()
        if isinstance(data, memoryview)
        else bytes(data[payload_start : payload_start + payload_len])
    )

    return ParseComplete(
        frame=Frame(frame_type=frame_type, flags=flags, payload=payload),
        consumed=needed,
    )


# ═══ Convenience ══════════════════════════════════════════════════════════════


def type_name(frame_type: int) -> str:
    """Human-readable name for a frame type constant."""
    return _TYPE_NAMES.get(frame_type, f"UNKNOWN(0x{frame_type:02X})")


def is_compressed(frame_or_flags: Frame | int) -> bool:
    """Check whether the FLAG_COMPRESSED bit is set."""
    flags = frame_or_flags.flags if isinstance(frame_or_flags, Frame) else frame_or_flags
    return bool(flags & FLAG_COMPRESSED)


def is_encrypted(frame_or_flags: Frame | int) -> bool:
    """Check whether the FLAG_ENCRYPTED bit is set."""
    flags = frame_or_flags.flags if isinstance(frame_or_flags, Frame) else frame_or_flags
    return bool(flags & FLAG_ENCRYPTED)


def is_priority(frame_or_flags: Frame | int) -> bool:
    """Check whether the FLAG_PRIORITY bit is set."""
    flags = frame_or_flags.flags if isinstance(frame_or_flags, Frame) else frame_or_flags
    return bool(flags & FLAG_PRIORITY)


def is_fragmented(frame_or_flags: Frame | int) -> bool:
    """Check whether the FLAG_FRAGMENTED bit is set."""
    flags = frame_or_flags.flags if isinstance(frame_or_flags, Frame) else frame_or_flags
    return bool(flags & FLAG_FRAGMENTED)
