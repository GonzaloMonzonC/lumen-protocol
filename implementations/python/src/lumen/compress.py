"""
Compact binary payload compression/decompression — port of Rust ``compress.rs``.

Encoding format
---------------

::

    Value:
      Null:    0xE0
      Bool:    0xE1 <0|1:1B>
      Float:   0xE2 <f64 LE:8B>
      Int:     0xE3 <zigzag LEB128>
      StrDict: 0xE4 <id:1B>
      StrRaw:  0xE5 <len:Hyb128> <utf8>
      Array:   0xE6 <count:Hyb128> value*
      Object:  0xE7 <count:Hyb128> (key value)*

    Key (inside Object):
      [dict] <id:1B>     where id in 0x00..0xFE
      [raw]  0xFF <len:Hyb128> <utf8>

Ported from TypeScript ``src/compress.ts`` and Rust ``src/compress.rs``.
"""

from __future__ import annotations

import struct
from typing import Any

from .hyb128 import decode_hyb128, encode_hyb128_bytes, encoded_len as hyb128_encoded_len
from .dict import ID_RAW, STATIC_MAX, lookup_dict_id, resolve_dict_id

# ═══ Value tags ═══════════════════════════════════════════════════════════════

TAG_NULL: int = 0xE0
TAG_BOOL: int = 0xE1
TAG_FLOAT: int = 0xE2
TAG_INT: int = 0xE3
TAG_STR_DICT: int = 0xE4
TAG_STR_RAW: int = 0xE5
TAG_ARRAY: int = 0xE6
TAG_OBJECT: int = 0xE7

_MAX_COUNT: int = 1024  # safety cap on container element counts
_MAX_DEPTH: int = 32    # safety cap on nesting depth (prevents stack overflow DoS)


# ═══ Public API ═══════════════════════════════════════════════════════════════


def compress_value(value: Any) -> bytes:
    """Compress a JSON-compatible value into LUMEN compact binary.

    >>> compress_value(None)
    b'\\xe0'
    >>> compress_value(True)
    b'\\xe1\\x01'
    >>> compress_value({"tool": "search"})
    b'\\xe7\\x01\\x00\\xe5\\x06search'
    """
    chunks: list[bytes] = []
    _encode_value(value, chunks)
    return b"".join(chunks)


def compress_into(value: Any, chunks: list[bytes]) -> None:
    """Compress *value*, appending byte chunks to *chunks*.

    Zero-alloc friendly: reuse the same list across many calls.
    """
    _encode_value(value, chunks)


def decompress_value(data: bytes | bytearray | memoryview) -> Any:
    """Decompress LUMEN compact binary back into a JSON-compatible value.

    Returns ``None`` if the input is malformed.

    >>> decompress_value(b'\\xe0')
    >>> decompress_value(b'\\xe1\\x01')
    True
    """
    if not data:
        return None
    pos = 0
    return _decode_value(data, pos, len(data))[0]


def compressed_size(value: Any) -> int:
    """Estimate (quickly, without full encode) the compressed size in bytes."""
    if value is None:
        return 1
    if isinstance(value, bool):
        return 2
    if isinstance(value, int):
        return 1 + _zigzag_leb128_len(value)
    if isinstance(value, float):
        # Canonicalization: whole-number floats → TAG_INT (matches encode_value)
        if value == int(value) and -0x8000000000000000 <= int(value) <= 0x7FFFFFFFFFFFFFFF:
            return 1 + _zigzag_leb128_len(int(value))
        return 9
    if isinstance(value, str):
        dict_id = lookup_dict_id(value)
        if dict_id is not None:
            return 2
        utf8 = value.encode("utf-8")
        return 1 + hyb128_encoded_len(len(utf8)) + len(utf8)
    if isinstance(value, list):
        sz = 1 + hyb128_encoded_len(len(value))
        for v in value:
            sz += compressed_size(v)
        return sz
    if isinstance(value, dict):
        sz = 1 + hyb128_encoded_len(len(value))
        for k, v in value.items():
            sz += _key_size(k)
            sz += compressed_size(v)
        return sz
    # Unsupported types → encode as null
    return 1


# ═══ Encoder ══════════════════════════════════════════════════════════════════


def _encode_value(value: Any, out: list[bytes]) -> None:
    if value is None:
        out.append(bytes([TAG_NULL]))
        return

    if isinstance(value, bool):
        out.append(bytes([TAG_BOOL, 1 if value else 0]))
        return

    if isinstance(value, int):
        out.append(bytes([TAG_INT]))
        out.append(_encode_zigzag_leb128(value))
        return

    if isinstance(value, float):
        # Canonicalization: whole-number floats → TAG_INT for cross-language interop.
        # Rust (as_i64 round-trip) and TS (Number.isSafeInteger) both encode 0.0/42.0 as TAG_INT.
        if value == int(value) and -0x8000000000000000 <= int(value) <= 0x7FFFFFFFFFFFFFFF:
            out.append(bytes([TAG_INT]))
            out.append(_encode_zigzag_leb128(int(value)))
            return
        buf = bytearray(9)
        buf[0] = TAG_FLOAT
        struct.pack_into("<d", buf, 1, value)
        out.append(bytes(buf))
        return

    if isinstance(value, str):
        dict_id = lookup_dict_id(value)
        if dict_id is not None:
            out.append(bytes([TAG_STR_DICT, dict_id]))
            return
        utf8 = value.encode("utf-8")
        len_buf = encode_hyb128_bytes(len(utf8))
        out.append(bytes([TAG_STR_RAW]) + len_buf + utf8)
        return

    if isinstance(value, list):
        count_buf = encode_hyb128_bytes(len(value))
        out.append(bytes([TAG_ARRAY]) + count_buf)
        for v in value:
            _encode_value(v, out)
        return

    if isinstance(value, dict):
        count_buf = encode_hyb128_bytes(len(value))
        out.append(bytes([TAG_OBJECT]) + count_buf)
        for k, v in value.items():
            _encode_key(k, out)
            _encode_value(v, out)
        return

    # Unsupported types → encode as null
    out.append(bytes([TAG_NULL]))


def _encode_key(key: str, out: list[bytes]) -> None:
    dict_id = lookup_dict_id(key)
    if dict_id is not None:
        out.append(bytes([dict_id]))
        return
    utf8 = key.encode("utf-8")
    len_buf = encode_hyb128_bytes(len(utf8))
    out.append(bytes([ID_RAW]) + len_buf + utf8)


# ═══ Decoder ══════════════════════════════════════════════════════════════════


def _decode_value(
    data: bytes | bytearray | memoryview, pos: int, end: int, depth: int = 0
) -> tuple[Any, int]:
    """Decode one value starting at *pos*. Returns ``(value, new_pos)``."""
    if depth > _MAX_DEPTH:
        return None, pos  # reject deeply nested payloads
    if pos >= end:
        return None, pos

    tag = data[pos]
    pos += 1

    if tag == TAG_NULL:
        return None, pos

    if tag == TAG_BOOL:
        if pos >= end:
            return None, pos
        return data[pos] != 0, pos + 1

    if tag == TAG_FLOAT:
        if pos + 8 > end:
            return None, pos
        value = struct.unpack_from("<d", data, pos)[0]
        return value, pos + 8

    if tag == TAG_INT:
        value, pos = _decode_zigzag_leb128(data, pos, end)
        return value, pos

    if tag == TAG_STR_DICT:
        if pos >= end:
            return None, pos
        return resolve_dict_id(data[pos]), pos + 1

    if tag == TAG_STR_RAW:
        decoded = decode_hyb128(data, pos)
        if decoded is None:
            return None, pos
        length, header_len = decoded
        pos += header_len
        if pos + length > end:
            return None, pos
        s = data[pos : pos + length].tobytes().decode("utf-8") if isinstance(data, memoryview) else bytes(data[pos : pos + length]).decode("utf-8")
        return s, pos + length

    if tag == TAG_ARRAY:
        decoded = decode_hyb128(data, pos)
        if decoded is None:
            return None, pos
        count, header_len = decoded
        pos += header_len
        count = min(count, _MAX_COUNT)
        arr: list[Any] = [None] * count
        for i in range(count):
            arr[i], pos = _decode_value(data, pos, end, depth + 1)
        return arr, pos

    if tag == TAG_OBJECT:
        decoded = decode_hyb128(data, pos)
        if decoded is None:
            return None, pos
        count, header_len = decoded
        pos += header_len
        count = min(count, _MAX_COUNT)
        obj: dict[str, Any] = {}
        for _ in range(count):
            key, pos = _decode_key(data, pos, end)
            val, pos = _decode_value(data, pos, end, depth + 1)
            if key is not None:
                obj[key] = val
        return obj, pos

    # Unknown tag → malformed
    return None, pos


def _decode_key(
    data: bytes | bytearray | memoryview, pos: int, end: int
) -> tuple[str | None, int]:
    if pos >= end:
        return None, pos
    first = data[pos]
    pos += 1

    if first == ID_RAW:
        decoded = decode_hyb128(data, pos)
        if decoded is None:
            return None, pos
        length, header_len = decoded
        pos += header_len
        if pos + length > end:
            return None, pos
        s = data[pos : pos + length].tobytes().decode("utf-8") if isinstance(data, memoryview) else bytes(data[pos : pos + length]).decode("utf-8")
        return s, pos + length

    if first < STATIC_MAX:
        return resolve_dict_id(first), pos

    # Session dictionary (0x80..0xFE)
    if first < 0xFF:
        return resolve_dict_id(first), pos

    return None, pos


# ═══ Zigzag LEB128 helpers ════════════════════════════════════════════════════


def _zigzag_leb128_len(v: int) -> int:
    """Number of bytes needed for zigzag LEB128 encoding of signed *v*."""
    # Zigzag: map signed to unsigned (i64 semantics — mask to u64)
    u = ((v >> 63) ^ (v << 1)) & 0xFFFFFFFFFFFFFFFF
    if u == 0:
        return 1
    count = 0
    while u > 0:
        count += 1
        u >>= 7
    return count


def _encode_zigzag_leb128(v: int) -> bytes:
    """Encode signed int *v* as zigzag LEB128."""
    # Zigzag: map signed to unsigned
    # Python integers are arbitrary-precision; simulate i64 zigzag
    u = ((v >> 63) ^ (v << 1)) & 0xFFFFFFFFFFFFFFFF
    buf: list[int] = []
    while True:
        byte = u & 0x7F
        u >>= 7
        if u != 0:
            byte |= 0x80
        buf.append(byte)
        if u == 0:
            break
    return bytes(buf)


def _decode_zigzag_leb128(
    data: bytes | bytearray | memoryview, pos: int, end: int
) -> tuple[int | None, int]:
    """Decode zigzag LEB128 starting at *pos*. Returns ``(value, new_pos)``."""
    u = 0
    shift = 0
    for _ in range(10):  # safety cap
        if pos >= end:
            return None, pos
        byte = data[pos]
        pos += 1
        u |= (byte & 0x7F) << shift
        if (byte & 0x80) == 0:
            # Zigzag decode
            value = (u >> 1) ^ -(u & 1)
            return value, pos
        shift += 7
        if shift >= 64:
            return None, pos
    return None, pos


def _key_size(key: str) -> int:
    dict_id = lookup_dict_id(key)
    if dict_id is not None:
        return 1
    utf8 = key.encode("utf-8")
    return 1 + hyb128_encoded_len(len(utf8)) + len(utf8)
