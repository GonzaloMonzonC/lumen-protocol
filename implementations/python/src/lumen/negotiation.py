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


# ═══ Types ════════════════════════════════════════════════════════════════════


@dataclass
class LumenProbe:
    """LUMEN PROBE payload: client capabilities."""

    protocol: str = "LUMEN"
    version: str = "1.0"
    client_name: str = ""
    supported_versions: list[str] = field(default_factory=lambda: ["1.0"])

    def to_bytes(self) -> bytes:
        """Serialize this probe to wire format (PROBE frame)."""
        return _build_probe_frame(self)


@dataclass
class LumenAck:
    """LUMEN PROBE_ACK payload: server capabilities (intersection with client)."""

    protocol: str = "LUMEN"
    server_name: str = ""
    accepted_version: str = ""

    def to_bytes(self) -> bytes:
        """Serialize this ack to wire format (PROBE_ACK frame)."""
        return _build_ack_frame(self)


# ═══ Build ════════════════════════════════════════════════════════════════════


def _build_probe_frame(probe: LumenProbe) -> bytes:
    """Internal: build PROBE frame bytes from a LumenProbe."""
    payload = compress_value({
        "protocol": probe.protocol,
        "version": probe.version,
        "client_name": probe.client_name,
        "supported_versions": probe.supported_versions,
    })
    frame = build_frame(TYPE_PROBE, FLAG_COMPRESSED, payload)
    return frame.to_bytes()


def build_probe(
    client_name: str = "",
    supported_versions: list[str] | None = None,
    version: str = "1.0",
) -> LumenProbe:
    """Build a LUMEN PROBE object.

    Returns a :class:`LumenProbe`. Call ``.to_bytes()`` for wire format.
    """
    return LumenProbe(
        client_name=client_name,
        supported_versions=supported_versions or ["1.0"],
        version=version,
    )


def _build_ack_frame(ack: LumenAck) -> bytes:
    """Internal: build PROBE_ACK frame bytes from a LumenAck."""
    payload = compress_value({
        "protocol": ack.protocol,
        "server_name": ack.server_name,
        "accepted_version": ack.accepted_version,
    })
    frame = build_frame(TYPE_PROBE_ACK, FLAG_COMPRESSED, payload)
    return frame.to_bytes()


def build_ack(server_name: str = "", accepted_version: str = "") -> LumenAck:
    """Build a LUMEN PROBE_ACK object.

    Returns a :class:`LumenAck`. Call ``.to_bytes()`` for wire format.
    """
    return LumenAck(server_name=server_name, accepted_version=accepted_version)


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
        return LumenAck(
            protocol=str(value.get("protocol", "LUMEN")),
            server_name=str(value.get("server_name", "")),
            accepted_version=str(value.get("accepted_version", "")),
        )
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
        sv = value.get("supported_versions", [])
        if not isinstance(sv, list):
            sv = [str(sv)]
        return LumenProbe(
            protocol=str(value.get("protocol", "LUMEN")),
            version=str(value.get("version", "1.0")),
            client_name=str(value.get("client_name", "")),
            supported_versions=[str(v) for v in sv],
        )
    except Exception:
        return None
