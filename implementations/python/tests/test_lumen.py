"""
Comprehensive test suite for the LUMEN Python binding.

Covers: Hyb128, Dict, Compress, Frame, FrameAssembler, Negotiation,
and cross-module round-trip correctness against JSON.

Run with:

    cd implementations/python
    python -m pytest tests/ -v
"""

from __future__ import annotations

import json
import math

import pytest

from lumen import (
    # hyb128
    decode_hyb128,
    encode_hyb128,
    encode_hyb128_bytes,
    hyb128_encoded_len,
    HYB128_MAX_SHORT,
    HYB128_MAX_ENCODED_LEN,
    # dict
    ID_RAW,
    STATIC_MAX,
    lookup_dict_id,
    resolve_dict_id,
    # compress
    compress_value,
    decompress_value,
    compressed_size,
    compress_into,
    TAG_NULL,
    TAG_BOOL,
    TAG_FLOAT,
    TAG_INT,
    TAG_STR_DICT,
    TAG_STR_RAW,
    TAG_ARRAY,
    TAG_OBJECT,
    # frame
    TYPE_REQUEST,
    TYPE_RESPONSE,
    TYPE_NOTIFY,
    TYPE_HEARTBEAT,
    TYPE_PROBE,
    TYPE_PROBE_ACK,
    FLAG_COMPRESSED,
    FLAG_ENCRYPTED,
    FLAG_PRIORITY,
    FLAG_FRAGMENTED,
    Frame,
    build_frame,
    build_size,
    parse_frame,
    ParseComplete,
    ParseIncomplete,
    ParseIncompletePayload,
    is_compressed,
    # frame assembler
    FrameAssembler,
    # negotiation
    LumenProbe,
    LumenAck,
    build_probe,
    build_ack,
    parse_probe,
    parse_ack,
)


# ═══ Test payloads (matching TS zeroalloc.test.ts) ═══════════════════════════

PAYLOADS: list[dict] = [
    # ── Primitives ──────────────────────────────────────────────────────
    {"name": "null", "value": None},
    {"name": "bool_true", "value": True},
    {"name": "bool_false", "value": False},
    {"name": "int_zero", "value": 0},
    {"name": "int_positive", "value": 42},
    {"name": "int_negative", "value": -1},
    {"name": "int_large", "value": 1_000_000},
    {"name": "int_negative_large", "value": -65536},
    {"name": "float_zero", "value": 0.0},
    {"name": "float_pi", "value": 3.141592653589793},
    {"name": "float_negative", "value": -2.718281828459045},
    {"name": "string_empty", "value": ""},
    {"name": "string_ascii", "value": "hello world"},
    {"name": "string_unicode", "value": "héllo wörld 🚀"},
    {"name": "string_long", "value": "a" * 500},
    {"name": "string_escapes", "value": 'line1\nline2\t"quoted"\\backslash'},
    # ── Arrays ──────────────────────────────────────────────────────────
    {"name": "array_empty", "value": []},
    {"name": "array_ints", "value": [1, 2, 3, 4, 5]},
    {"name": "array_mixed", "value": [None, True, 42, "text", 3.14]},
    {"name": "array_nested", "value": [[1, 2], [3, [4, 5]]]},
    {"name": "array_large", "value": list(range(100))},
    # ── Objects ─────────────────────────────────────────────────────────
    {"name": "object_empty", "value": {}},
    {"name": "object_flat", "value": {"a": 1, "b": "two", "c": True}},
    {
        "name": "object_dict_keys",
        "value": {
            "tool": "search",
            "arguments": {"query": "hello", "limit": 10},
            "result": {"text": "found"},
            "error": None,
        },
    },
    {
        "name": "object_nested",
        "value": {
            "level1": {
                "level2": {
                    "level3": {"value": 42},
                    "list": [1, 2, 3],
                },
            },
        },
    },
    # ── Realistic MCP payloads ──────────────────────────────────────────
    {
        "name": "initialize",
        "value": {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "clientInfo": {"name": "test-client", "version": "1.0.0"},
            },
        },
    },
    {
        "name": "tools_list",
        "value": {
            "jsonrpc": "2.0",
            "id": 2,
            "result": {
                "tools": [
                    {
                        "name": "search_code",
                        "description": "Search source code with regex",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"query": {"type": "string"}},
                        },
                    },
                    {
                        "name": "read_file",
                        "description": "Read file contents at path",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                ],
            },
        },
    },
    {
        "name": "llm_request",
        "value": {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "llm_complete",
                "arguments": {
                    "model": "deepseek-v4",
                    "messages": [{"role": "user", "content": "Explain LUMEN protocol"}],
                    "temperature": 0.7,
                },
            },
        },
    },
    {
        "name": "error_response",
        "value": {
            "jsonrpc": "2.0",
            "id": 4,
            "error": {
                "code": -32600,
                "message": "Invalid Request",
                "data": {"detail": "missing method"},
            },
        },
    },
    # ── Deeply nested ───────────────────────────────────────────────────
    {"name": "deep_array", "value": [[[[[[[[1]]]]]]]]},
    {
        "name": "deep_object",
        "value": {"a": {"b": {"c": {"d": {"e": {"f": {"g": {"h": "deep"}}}}}}}},
    },
    # ── Edge cases: dict vs raw keys ────────────────────────────────────
    {"name": "dict_key_tool", "value": {"tool": "test", "arguments": {"x": 1}}},
    {
        "name": "raw_key_custom",
        "value": {"customUncompressedKey": "value", "anotherCustomKey": 42},
    },
]


def json_roundtrip(value):
    """Simulate the TS approach: JSON.stringify → JSON.parse."""
    return json.loads(json.dumps(value, ensure_ascii=False))


# ═══ Hyb128 tests ═════════════════════════════════════════════════════════════


class TestHyb128Encode:
    def test_mode_00_boundary(self):
        buf = bytearray(HYB128_MAX_ENCODED_LEN)
        assert encode_hyb128(0, buf) == 1
        assert encode_hyb128(63, buf) == 1
        assert encode_hyb128(42, buf) == 1

    def test_mode_10_boundary(self):
        buf = bytearray(HYB128_MAX_ENCODED_LEN)
        assert encode_hyb128(64, buf) == 3
        assert encode_hyb128(65535, buf) == 3
        assert encode_hyb128(1000, buf) == 3

    def test_mode_11_boundary(self):
        buf = bytearray(HYB128_MAX_ENCODED_LEN)
        assert encode_hyb128(65536, buf) == 5
        assert encode_hyb128(1000000, buf) == 5

    def test_rejects_negative(self):
        buf = bytearray(11)
        with pytest.raises(ValueError):
            encode_hyb128(-1, buf)

    def test_encode_hyb128_bytes(self):
        assert encode_hyb128_bytes(42) == bytes([42])
        assert len(encode_hyb128_bytes(1000)) == 3

    def test_encoded_len(self):
        assert hyb128_encoded_len(0) == 1
        assert hyb128_encoded_len(63) == 1
        assert hyb128_encoded_len(64) == 3
        assert hyb128_encoded_len(1000) == 3
        assert hyb128_encoded_len(1000000) == 5


class TestHyb128Decode:
    def test_mode_00(self):
        assert decode_hyb128(bytes([42])) == (42, 1)
        assert decode_hyb128(bytes([0])) == (0, 1)
        assert decode_hyb128(bytes([63])) == (63, 1)

    def test_mode_10(self):
        encoded = bytes([0x80, 0xE8, 0x03])
        assert decode_hyb128(encoded) == (1000, 3)

    def test_mode_11(self):
        encoded = bytes([0xC0, 0xA0, 0x86, 0x01, 0x00])
        assert decode_hyb128(encoded) == (100000, 5)

    def test_roundtrip(self):
        for val in [0, 1, 42, 63, 64, 255, 1000, 65535, 65536, 1000000, 2**30]:
            encoded = encode_hyb128_bytes(val)
            result = decode_hyb128(encoded)
            assert result is not None
            assert result[0] == val

    def test_incomplete_mode_10(self):
        assert decode_hyb128(bytes([0x80])) is None
        assert decode_hyb128(bytes([0x80, 0x00])) is None

    def test_incomplete_mode_11(self):
        assert decode_hyb128(bytes([0xC0, 0x00, 0x00])) is None

    def test_empty(self):
        assert decode_hyb128(b"") is None


# ═══ Dict tests ═══════════════════════════════════════════════════════════════


class TestDict:
    def test_resolve_known_ids(self):
        assert resolve_dict_id(0x00) == "tool"
        assert resolve_dict_id(0x01) == "arguments"
        assert resolve_dict_id(0x04) == "id"
        assert resolve_dict_id(0x05) == "name"
        assert resolve_dict_id(0x40) == "model"
        assert resolve_dict_id(0x4F) == "usage"
        assert resolve_dict_id(0x7F) == "resume"

    def test_resolve_unknown_ids(self):
        assert resolve_dict_id(STATIC_MAX) is None
        assert resolve_dict_id(0xFF) is None
        assert resolve_dict_id(999) is None

    def test_lookup_known_keys(self):
        assert lookup_dict_id("tool") == 0x00
        assert lookup_dict_id("arguments") == 0x01
        assert lookup_dict_id("model") == 0x40

    def test_lookup_unknown_keys(self):
        assert lookup_dict_id("nonexistent_key_xyz") is None
        assert lookup_dict_id("") is None

    def test_dict_coverage(self):
        for i in range(STATIC_MAX):
            resolved = resolve_dict_id(i)
            assert resolved is None or isinstance(resolved, str)
            if resolved:
                assert lookup_dict_id(resolved) == i


# ═══ Compress tests ═══════════════════════════════════════════════════════════


class TestCompressRoundtrip:
    @pytest.mark.parametrize("entry", PAYLOADS, ids=lambda e: e["name"])
    def test_roundtrip_vs_json(self, entry):
        value = entry["value"]
        compressed = compress_value(value)
        result = decompress_value(compressed)
        expected = json_roundtrip(value)
        assert result == expected, f"Mismatch for '{entry['name']}'"

    def test_compress_into(self):
        chunks: list[bytes] = []
        compress_into({"x": 1}, chunks)
        compress_into([1, 2, 3], chunks)
        result = b"".join(chunks)
        assert len(result) > 5

    def test_compressed_size_accurate(self):
        for entry in PAYLOADS[:10]:
            value = entry["value"]
            estimated = compressed_size(value)
            actual = len(compress_value(value))
            assert estimated == actual, (
                f"Size mismatch for '{entry['name']}': "
                f"estimated={estimated}, actual={actual}"
            )


class TestCompressPrimitives:
    def test_null(self):
        assert compress_value(None) == bytes([TAG_NULL])
        assert decompress_value(bytes([TAG_NULL])) is None

    def test_bool(self):
        assert compress_value(True) == bytes([TAG_BOOL, 1])
        assert compress_value(False) == bytes([TAG_BOOL, 0])
        assert decompress_value(bytes([TAG_BOOL, 1])) is True
        assert decompress_value(bytes([TAG_BOOL, 0])) is False

    def test_int(self):
        compressed = compress_value(42)
        assert compressed[0] == TAG_INT
        assert decompress_value(compressed) == 42

    def test_int_negative(self):
        compressed = compress_value(-100)
        assert compressed[0] == TAG_INT
        assert decompress_value(compressed) == -100

    def test_float(self):
        compressed = compress_value(3.14)
        assert compressed[0] == TAG_FLOAT
        result = decompress_value(compressed)
        assert math.isclose(result, 3.14)

    def test_string_dict(self):
        compressed = compress_value("tool")
        assert compressed[0] == TAG_STR_DICT
        assert compressed[1] == lookup_dict_id("tool")
        assert decompress_value(compressed) == "tool"

    def test_string_raw(self):
        compressed = compress_value("not-a-dict-key-xyz")
        assert compressed[0] == TAG_STR_RAW
        assert decompress_value(compressed) == "not-a-dict-key-xyz"


class TestCompressMalformed:
    def test_empty_buffer(self):
        assert decompress_value(b"") is None

    def test_truncated_float(self):
        buf = bytes([TAG_FLOAT, 0x00, 0x00, 0x00])
        assert decompress_value(buf) is None

    def test_truncated_bool(self):
        assert decompress_value(bytes([TAG_BOOL])) is None

    def test_unknown_tag(self):
        assert decompress_value(bytes([0xFF, 0x00])) is None

    def test_truncated_raw_string(self):
        buf = bytes([TAG_STR_RAW, 0x80, 0x64])
        assert decompress_value(buf) is None


class TestCompressDictKeys:
    def test_dict_key_is_compressed(self):
        value = {"tool": "search"}
        compressed = compress_value(value)
        assert len(compressed) < len(json.dumps(value)) * 2

    def test_raw_key_uses_string_tag(self):
        value = {"customKeyNotInDict": "value"}
        compressed = compress_value(value)
        assert TAG_STR_RAW in compressed


# ═══ Frame tests ══════════════════════════════════════════════════════════════


class TestFrameBuildBasic:
    def test_build_no_payload(self):
        f = build_frame(TYPE_HEARTBEAT)
        assert f.type == TYPE_HEARTBEAT
        assert f.flags == 0
        assert f.payload == b""
        assert not is_compressed(f)

    def test_build_with_payload(self):
        f = build_frame(TYPE_RESPONSE, payload=b"test")
        assert f.type == TYPE_RESPONSE
        assert f.payload == b"test"

    def test_build_with_flags(self):
        f = build_frame(TYPE_REQUEST, flags=FLAG_COMPRESSED, payload=b"data")
        assert is_compressed(f)

    def test_build_size_no_payload(self):
        assert build_size(TYPE_HEARTBEAT) == 4  # 1B Hyb128 len + 1B type + 1B flags + 1B len field (mode 00)

    def test_build_size_with_payload(self):
        size = build_size(TYPE_RESPONSE, payload_len=100)
        assert size > 100  # header + payload


class TestFrameParse:
    def test_roundtrip_no_payload(self):
        f = build_frame(TYPE_NOTIFY)
        wire = f.to_bytes()
        result = parse_frame(wire)
        assert isinstance(result, ParseComplete)
        assert result.frame.type == TYPE_NOTIFY
        assert result.frame.payload == b""

    def test_roundtrip_with_payload(self):
        f = build_frame(TYPE_RESPONSE, payload=b"hello")
        wire = f.to_bytes()
        result = parse_frame(wire)
        assert isinstance(result, ParseComplete)
        assert result.frame.payload == b"hello"

    def test_roundtrip_with_flags(self):
        f = build_frame(TYPE_REQUEST, flags=FLAG_COMPRESSED | FLAG_PRIORITY, payload=b"p")
        wire = f.to_bytes()
        result = parse_frame(wire)
        assert isinstance(result, ParseComplete)
        assert is_compressed(result.frame)

    def test_incomplete_header(self):
        result = parse_frame(b"\x00")
        assert isinstance(result, ParseIncomplete)

    def test_empty_buffer(self):
        result = parse_frame(b"")
        assert isinstance(result, ParseIncomplete)

    def test_incomplete_payload(self):
        f = build_frame(TYPE_RESPONSE, payload=b"abcdefghij")
        wire = f.to_bytes()
        # truncate last 3 bytes
        result = parse_frame(wire[:-3])
        assert isinstance(result, ParseIncompletePayload)
        assert result.expected_len > len(wire[:-3])


# ═══ Frame Assembler tests ════════════════════════════════════════════════════


class TestFrameAssembler:
    def test_single_frame(self):
        assembler = FrameAssembler()
        f = build_frame(TYPE_RESPONSE, payload=b"hello")
        results = assembler.push(f.to_bytes())
        assert len(results) == 1
        assert results[0].payload == b"hello"

    def test_two_frames(self):
        assembler = FrameAssembler()
        f1 = build_frame(TYPE_NOTIFY, payload=b"first")
        f2 = build_frame(TYPE_RESPONSE, payload=b"second")
        results = assembler.push(f1.to_bytes() + f2.to_bytes())
        assert len(results) == 2
        assert results[0].payload == b"first"
        assert results[1].payload == b"second"

    def test_fragmented_delivery(self):
        assembler = FrameAssembler()
        f = build_frame(TYPE_RESPONSE, payload=b"fragmented-test")
        wire = f.to_bytes()
        # Split the frame arbitrarily
        mid = len(wire) // 2
        results1 = assembler.push(wire[:mid])
        assert len(results1) == 0
        results2 = assembler.push(wire[mid:])
        assert len(results2) == 1
        assert results2[0].payload == b"fragmented-test"

    def test_flush_returns_incomplete(self):
        assembler = FrameAssembler()
        f = build_frame(TYPE_RESPONSE, payload=b"incomplete")
        wire = f.to_bytes()
        assembler.push(wire[:3])
        flushed = assembler.flush()
        assert len(flushed) == 0  # partial frame discarded or buffered

    def test_reset(self):
        assembler = FrameAssembler()
        f = build_frame(TYPE_RESPONSE, payload=b"hello")
        assembler.push(f.to_bytes()[:2])
        assert len(assembler) > 0
        assembler.reset()
        assert len(assembler) == 0
        # After reset, a full frame should parse cleanly
        results = assembler.push(f.to_bytes())
        assert len(results) == 1

    def test_interleaved_small_chunks(self):
        assembler = FrameAssembler()
        f1 = build_frame(TYPE_NOTIFY, payload=b"A")
        f2 = build_frame(TYPE_RESPONSE, payload=b"BB")
        wire = f1.to_bytes() + f2.to_bytes()
        results = assembler.push(wire)
        assert len(results) == 2
        assert results[0].payload == b"A"
        assert results[1].payload == b"BB"

    def test_multiple_push_calls(self):
        assembler = FrameAssembler()
        f1 = build_frame(TYPE_RESPONSE, payload=b"one")
        f2 = build_frame(TYPE_RESPONSE, payload=b"two")
        r1 = assembler.push(f1.to_bytes())
        r2 = assembler.push(f2.to_bytes())
        assert len(r1) == 1
        assert len(r2) == 1

    def test_len_reflects_buffered(self):
        assembler = FrameAssembler()
        f = build_frame(TYPE_RESPONSE, payload=b"x" * 100)
        wire = f.to_bytes()
        assembler.push(wire[:5])
        assert len(assembler) > 0
        assembler.reset()
        assert len(assembler) == 0


# ═══ Negotiation tests ════════════════════════════════════════════════════════


class TestNegotiation:
    def test_build_probe(self):
        probe = build_probe("test_client", supported_versions=["1.0", "1.1-draft"])
        assert probe.protocol == "LUMEN"
        assert probe.version == "1.0"
        assert probe.client_name == "test_client"
        assert "1.1-draft" in probe.supported_versions

    def test_parse_probe(self):
        wire = build_probe("agent", supported_versions=["1.0"]).to_bytes()
        probe = parse_probe(wire)
        assert probe is not None
        assert probe.client_name == "agent"
        assert probe.protocol == "LUMEN"

    def test_parse_probe_invalid(self):
        assert parse_probe(b"not a lumen probe") is None

    def test_build_ack(self):
        ack = build_ack("server_v1", accepted_version="1.0")
        assert ack.protocol == "LUMEN"
        assert ack.server_name == "server_v1"
        assert ack.accepted_version == "1.0"

    def test_parse_ack(self):
        wire = build_ack("srv", accepted_version="1.0").to_bytes()
        ack = parse_ack(wire)
        assert ack is not None
        assert ack.server_name == "srv"

    def test_parse_ack_invalid(self):
        assert parse_ack(b"garbage data") is None

    def test_roundtrip_probe(self):
        wire = build_probe("client", supported_versions=["1.0", "2.0"]).to_bytes()
        parsed = parse_probe(wire)
        assert parsed is not None
        assert parsed.client_name == "client"
        assert parsed.supported_versions == ["1.0", "2.0"]

    def test_roundtrip_ack(self):
        wire = build_ack("server", accepted_version="1.0").to_bytes()
        parsed = parse_ack(wire)
        assert parsed is not None
        assert parsed.server_name == "server"
        assert parsed.accepted_version == "1.0"
