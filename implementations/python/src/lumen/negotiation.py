"""
Protocol negotiation — LUMEN probe/ack handshake with JSON-RPC fallback.

Flow::

    Client                         Server
      |                              |
      |── [PROBE frame (binary)] ──→|
      |                              |
      |  (wait up to probe_timeout)  |
      |                              |
      |←── [PROBE_ACK frame] ───────|  ← Server speaks LUMEN → use binary
      |                              |
      OR                            |
      |                              |
      |  (timeout after N ms)        |  ← Server doesn't speak LUMEN
      |                              |     → fallback to JSON-RPC

Ported from TypeScript ``src/negotiation.ts``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .compress import compress_value, decompress_value
from .frame import (
    FLAG_COMPRESSED,
    TYPE_PROBE,
    TYPE_PROBE_ACK,
    build_frame,
    build_size,
    ParseComplete,
    parse_frame,
)

# ═══ Constants ════════════════════════════════════════════════════════════════

DEFAULT_PROBE_TIMEOUT_MS: float = 500.0
_LUMEN_VERSION: int = 1


# ═══ Types ════════════════════════════════════════════════════════════════════


@dataclass
class LumenProbe:
    """LUMEN PROBE payload: client capabilities."""

    v: int = _LUMEN_VERSION
    caps: list[str] = field(default_factory=lambda: ["compression", "streaming"])


@dataclass
class LumenAck:
    """LUMEN PROBE_ACK payload: server capabilities (intersection with client)."""

    v: int
    caps: list[str]


DEFAULT_PROBE: LumenProbe = LumenProbe()


# ═══ Build ════════════════════════════════════════════════════════════════════


def build_probe(probe: LumenProbe | None = None) -> bytes:
    """Build a LUMEN PROBE frame as raw bytes.

    The probe payload is compressed using the LUMEN compact encoder.
    """
    if probe is None:
        probe = DEFAULT_PROBE
    payload = compress_value({"v": probe.v, "caps": probe.caps})
    total = build_size(len(payload))
    buf = bytearray(total)
    build_frame(TYPE_PROBE, FLAG_COMPRESSED, payload, buf, 0)
    return bytes(buf)


def build_ack(ack: LumenAck) -> bytes:
    """Build a LUMEN PROBE_ACK frame as raw bytes."""
    payload = compress_value({"v": ack.v, "caps": ack.caps})
    total = build_size(len(payload))
    buf = bytearray(total)
    build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, payload, buf, 0)
    return bytes(buf)


# ═══ Parse ════════════════════════════════════════════════════════════════════


def parse_ack(data: bytes | bytearray | memoryview) -> LumenAck | None:
    """Try to parse a LUMEN PROBE_ACK frame from raw bytes.

    Returns ``None`` if the data is not a valid ACK frame.
    """
    result = parse_frame(data, 0)
    if not isinstance(result, ParseComplete):
        return None
    if result.frame.frame_type != TYPE_PROBE_ACK:
        return None

    try:
        value = decompress_value(result.frame.payload)
        if not isinstance(value, dict):
            return None
        v = value.get("v")
        caps = value.get("caps")
        if not isinstance(v, int) or not isinstance(caps, list):
            return None
        return LumenAck(v=v, caps=list(caps))
    except Exception:
        return None


def parse_probe(data: bytes | bytearray | memoryview) -> LumenProbe | None:
    """Try to parse a LUMEN PROBE frame from raw bytes.

    Returns ``None`` if the data is not a valid PROBE frame.
    """
    result = parse_frame(data, 0)
    if not isinstance(result, ParseComplete):
        return None
    if result.frame.frame_type != TYPE_PROBE:
        return None

    try:
        value = decompress_value(result.frame.payload)
        if not isinstance(value, dict):
            return None
        v = value.get("v")
        caps = value.get("caps")
        if not isinstance(v, int) or not isinstance(caps, list):
            return None
        return LumenProbe(v=v, caps=list(caps))
    except Exception:
        return None
