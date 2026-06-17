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

from .hyb128 import decode_hyb128, encode_hyb128, MAX_ENCODED_LEN, encoded_len as hyb128_encoded_len

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


class Frame:
    """A parsed LUMEN frame header + payload."""

    __slots__ = ("frame_type", "flags", "payload")

    def __init__(self, frame_type: int, flags: int, payload: bytes) -> None:
        self.frame_type = frame_type
        self.flags = flags
        self.payload = payload

    def to_bytes(self) -> bytes:
        """Serialize this frame to wire format."""
        return _build_wire(self.frame_type, self.flags, self.payload)

    def __repr__(self) -> str:
        return (
            f"Frame(type={type_name(self.frame_type)}, flags=0x{self.flags:02X}, "
            f"payload_len={len(self.payload)})"
        )


# ═══ ParseResult ══════════════════════════════════════════════════════════════


class ParseComplete(NamedTuple):
    frame: Frame
    consumed: int


class ParseIncompletePayload(NamedTuple):
    expected: int
    available: int


class ParseError(NamedTuple):
    message: str


class ParseIncomplete:
    """Sentinel for incomplete frame header parse (not enough bytes)."""
    __slots__ = ()

    _instance: ParseIncomplete | None = None

    def __new__(cls) -> ParseIncomplete:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "ParseIncomplete"


ParseResult = ParseComplete | ParseIncompletePayload | ParseIncomplete | ParseError


# ═══ Builder ══════════════════════════════════════════════════════════════════


def _build_wire(
    frame_type: int,
    flags: int,
    payload: bytes | bytearray,
    buf: bytearray | None = None,
    offset: int = 0,
) -> bytes:
    """Low-level: write frame to wire format bytes."""
    header_len = hyb128_encoded_len(len(payload))
    total = header_len + 2 + len(payload)

    if buf is None:
        buf = bytearray(total)

    n = encode_hyb128(len(payload), buf, offset)
    buf[offset + n] = frame_type
    buf[offset + n + 1] = flags
    buf[offset + n + 2 : offset + total] = payload

    return bytes(buf[offset : offset + total])


def build_frame(
    frame_type: int,
    flags: int = 0,
    payload: bytes | bytearray = b"",
    buf: bytearray | None = None,
    offset: int = 0,
) -> Frame:
    """Build a LUMEN frame.

    Returns a :class:`Frame` object. Use ``frame.to_bytes()`` for wire format.
    If *buf* is given, the wire bytes are also written into it at *offset*.
    """
    if buf is not None:
        _build_wire(frame_type, flags, payload, buf, offset)
    return Frame(frame_type=frame_type, flags=flags, payload=bytes(payload))


def build_size(payload_len: int = 0, *, frame_type: int = 0) -> int:
    """Total wire size needed for a frame.

    The *frame_type* keyword is accepted for API compatibility but ignored
    (type is always 1 byte regardless of value).
    """
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
        return ParseIncomplete()

    # Decode Hyb128 length
    decoded = decode_hyb128(data, offset)
    if decoded is None:
        # If we have enough bytes for a full Hyb128 header but still can't
        # decode, the data is malformed, not incomplete.
        if len(data) - offset >= MAX_ENCODED_LEN:
            return ParseError(message="malformed Hyb128 header")
        return ParseIncomplete()

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
