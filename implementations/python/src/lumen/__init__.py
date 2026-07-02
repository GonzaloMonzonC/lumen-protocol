"""
LUMEN — Lightweight Universal Model Exchange Network
=====================================================

Python implementation of the LUMEN binary protocol for MCP (Model Context Protocol).

Drop-in replacements for MCP SDK transports with automatic LUMEN negotiation
and transparent JSON-RPC fallback.

Quick start::

    from lumen import LumenStdioTransport, compress_value, decompress_value

    # Compress/decompress standalone
    payload = {"tool": "search", "arguments": {"query": "hello"}}
    compressed = compress_value(payload)   # 47-55% smaller than JSON
    restored = decompress_value(compressed)

    # Use as MCP transport
    transport = LumenStdioTransport(command="python", args=["server.py"])
    await transport.start()  # auto-negotiates LUMEN, falls back to JSON-RPC
"""

from __future__ import annotations

# ═══ Hyb128 ═══════════════════════════════════════════════════════════════════
from .hyb128 import (
    MAX_ENCODED_LEN as HYB128_MAX_ENCODED_LEN,
    MAX_SHORT as HYB128_MAX_SHORT,
    decode_hyb128,
    encode_hyb128,
    encode_hyb128_bytes,
    encoded_len as hyb128_encoded_len,
)

# ═══ Dictionary ═══════════════════════════════════════════════════════════════
from .dict import (
    ID_RAW,
    SESSION_MAX,
    STATIC_MAX,
    TOTAL_ENTRIES,
    lookup_dict_id,
    resolve_dict_id,
)

# ═══ Compress ═════════════════════════════════════════════════════════════════
from .compress import (
    TAG_ARRAY,
    TAG_BOOL,
    TAG_FLOAT,
    TAG_INT,
    TAG_NULL,
    TAG_OBJECT,
    TAG_STR_DICT,
    TAG_STR_RAW,
    compress_into,
    compress_value,
    compressed_size,
    decompress_value,
)

# ═══ Frame ════════════════════════════════════════════════════════════════════
from .frame import (
    FLAG_COMPRESSED,
    FLAG_ENCRYPTED,
    FLAG_FRAGMENTED,
    FLAG_PRIORITY,
    TYPE_DICT_SYNC,
    TYPE_DISCOVER,
    TYPE_HEARTBEAT,
    TYPE_TRANSPORT_INIT,
    TYPE_TRANSPORT_ACK,
    TYPE_BATCH,
    TYPE_FLOW_CTL,
    TYPE_MUX,
    TYPE_NOTIFY,
    TYPE_PROBE,
    TYPE_PROBE_ACK,
    TYPE_REQUEST,
    TYPE_RESPONSE,
    TYPE_SCHEMA_PATCH,
    TYPE_STREAM_DATA,
    TYPE_STREAM_INIT,
    Frame,
    ParseComplete,
    ParseError,
    ParseIncomplete,
    ParseIncompletePayload,
    ParseResult,
    build_frame,
    build_size,
    is_compressed,
    is_encrypted,
    is_fragmented,
    is_priority,
    parse_frame,
    type_name,
)

# ═══ Frame Assembler ══════════════════════════════════════════════════════════
from .frame_assembler import FrameAssembler

# ═══ Negotiation ══════════════════════════════════════════════════════════════
from .negotiation import (
    DEFAULT_PROBE_TIMEOUT_MS,
    LumenAck,
    LumenProbe,
    build_ack,
    build_probe,
    parse_ack,
    parse_probe,
)

# ═══ Transport ════════════════════════════════════════════════════════════════
from .transport import (
    LumenStdioTransport,
    LumenWebSocketTransport,
    Transport,
)

# ═══ Cadencia ═════════════════════════════════════════════════════════════════
from .cadencia import (
    BridgeCommand,
    BridgeIndexResponse,
    BridgeOptions,
    BridgeResponse,
    CadenciaBridge,
)

# ═══ Shared Memory ══════════════════════════════════════════════════════════════
from .shm import (
    ShmRegion,
    ShmRingBuffer,
    ShmTransport,
    RingSide,
    DEFAULT_REGION_SIZE as SHM_DEFAULT_REGION_SIZE,
    MAX_FRAME_SIZE as SHM_MAX_FRAME_SIZE,
)

__all__ = [
    # hyb128
    "HYB128_MAX_ENCODED_LEN",
    "HYB128_MAX_SHORT",
    "decode_hyb128",
    "encode_hyb128",
    "encode_hyb128_bytes",
    "hyb128_encoded_len",
    # dict
    "ID_RAW",
    "SESSION_MAX",
    "STATIC_MAX",
    "TOTAL_ENTRIES",
    "lookup_dict_id",
    "resolve_dict_id",
    # compress
    "TAG_ARRAY",
    "TAG_BOOL",
    "TAG_FLOAT",
    "TAG_INT",
    "TAG_NULL",
    "TAG_OBJECT",
    "TAG_STR_DICT",
    "TAG_STR_RAW",
    "compress_into",
    "compress_value",
    "compressed_size",
    "decompress_value",
    # frame
    "FLAG_COMPRESSED",
    "FLAG_ENCRYPTED",
    "FLAG_FRAGMENTED",
    "FLAG_PRIORITY",
    "TYPE_DICT_SYNC",
    "TYPE_DISCOVER",
    "TYPE_HEARTBEAT",
    "TYPE_MUX",
    "TYPE_NOTIFY",
    "TYPE_PROBE",
    "TYPE_PROBE_ACK",
    "TYPE_REQUEST",
    "TYPE_RESPONSE",
    "TYPE_SCHEMA_PATCH",
    "TYPE_STREAM_DATA",
    "TYPE_STREAM_INIT",
    "Frame",
    "ParseComplete",
    "ParseError",
    "ParseIncomplete",
    "ParseIncompletePayload",
    "ParseResult",
    "build_frame",
    "build_size",
    "is_compressed",
    "is_encrypted",
    "is_fragmented",
    "is_priority",
    "parse_frame",
    "type_name",
    # frame assembler
    "FrameAssembler",
    # negotiation
    "DEFAULT_PROBE_TIMEOUT_MS",
    "LumenAck",
    "LumenProbe",
    "build_ack",
    "build_probe",
    "parse_ack",
    "parse_probe",
    # transport
    "LumenStdioTransport",
    "LumenWebSocketTransport",
    "Transport",
    # cadencia
    "BridgeCommand",
    "BridgeIndexResponse",
    "BridgeOptions",
    "BridgeResponse",
    "CadenciaBridge",
    # shm
    "ShmRegion",
    "ShmRingBuffer",
    "ShmTransport",
    "RingSide",
    "SHM_DEFAULT_REGION_SIZE",
    "SHM_MAX_FRAME_SIZE",
]
