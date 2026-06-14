/**
 * Compact binary payload compression/decompression — port of Rust `compress.rs`.
 *
 * ## Encoding format
 *
 * ```text
 * Value:
 *   Null:    0xE0
 *   Bool:    0xE1 <0|1:1B>
 *   Float:   0xE2 <f64 LE:8B>
 *   Int:     0xE3 <zigzag LEB128>
 *   StrDict: 0xE4 <id:1B>
 *   StrRaw:  0xE5 <len:Hyb128> <utf8>
 *   Array:   0xE6 <count:Hyb128> value*
 *   Object:  0xE7 <count:Hyb128> (key value)*
 *
 * Key (inside Object):
 *   [dict] <id:1B>     where id ∈ 0x00..0xFE
 *   [raw]  0xFF <len:Hyb128> <utf8>
 * ```
 *
 * Tags chosen so that 0xE0..0xE7 = value types, 0x00..0xFE = dict key IDs,
 * 0xFF = raw key sentinel.
 */

import { decodeHyb128, encodeHyb128, encodedLen } from "./hyb128.js";
import { lookupDictId, resolveDictId, ID_RAW, STATIC_MAX } from "./dict.js";

// ═══ Value tags ═════════════════════════════════════════════════════════════

const TAG_NULL = 0xe0;
const TAG_BOOL = 0xe1;
const TAG_FLOAT = 0xe2;
const TAG_INT = 0xe3;
const TAG_STR_DICT = 0xe4;
const TAG_STR_RAW = 0xe5;
const TAG_ARRAY = 0xe6;
const TAG_OBJECT = 0xe7;

// ═══ Public API ═════════════════════════════════════════════════════════════

/**
 * Compress a JSON-compatible value into LUMEN compact binary.
 * Returns the compressed Uint8Array.
 */
export function compressValue(value: unknown): Uint8Array {
  const chunks: Uint8Array[] = [];
  encodeValue(value, chunks);
  return concatChunks(chunks);
}

/**
 * Compress a JSON-compatible value, appending to an existing `chunks` array.
 * Zero-alloc friendly: can reuse pre-allocated chunks across many calls.
 */
export function compressInto(value: unknown, chunks: Uint8Array[]): void {
  encodeValue(value, chunks);
}

/**
 * Decompress LUMEN compact binary back into a JSON-compatible value.
 * Returns `null` if the input is malformed.
 */
export function decompressValue(data: Uint8Array): unknown {
  let pos = 0;
  return decodeValue(data, new Int32Array([pos]), data.length);
}

/**
 * Estimate (quickly, without full encode) the compressed size in bytes.
 * Useful for buffer pre-allocation.
 */
export function compressedSize(value: unknown): number {
  if (value === null || value === undefined) return 1; // TAG_NULL
  if (typeof value === "boolean") return 2; // TAG_BOOL + 1
  if (typeof value === "number") {
    if (Number.isSafeInteger(value)) {
      return 1 + i64Leb128Len(value); // TAG_INT + zigzag LEB128
    }
    return 9; // TAG_FLOAT + f64
  }
  if (typeof value === "string") {
    const id = lookupDictId(value);
    if (id !== null) return 2; // TAG_STR_DICT + id
    return 1 + 1 + encodedLen(value.length) + value.length; // TAG + Hyb128 + utf8
  }
  if (Array.isArray(value)) {
    let sz = 1 + encodedLen(value.length); // TAG + count
    for (const v of value) sz += compressedSize(v);
    return sz;
  }
  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj);
    let sz = 1 + encodedLen(keys.length); // TAG + count
    for (const k of keys) {
      sz += keySize(k);
      sz += compressedSize(obj[k]);
    }
    return sz;
  }
  // Functions, symbols, etc. → encode as null
  return 1;
}

// ═══ Encoder ════════════════════════════════════════════════════════════════

function encodeValue(value: unknown, out: Uint8Array[]): void {
  if (value === null || value === undefined) {
    out.push(new Uint8Array([TAG_NULL]));
    return;
  }

  if (typeof value === "boolean") {
    out.push(new Uint8Array([TAG_BOOL, value ? 1 : 0]));
    return;
  }

  if (typeof value === "number") {
    // Preserve integer vs float distinction
    if (Number.isSafeInteger(value)) {
      out.push(new Uint8Array([TAG_INT]));
      out.push(encodeI64Leb128(value));
      return;
    }
    const buf = new Uint8Array(9);
    buf[0] = TAG_FLOAT;
    const dv = new DataView(buf.buffer, buf.byteOffset, 9);
    dv.setFloat64(1, value, true); // little-endian
    out.push(buf);
    return;
  }

  if (typeof value === "string") {
    const id = lookupDictId(value);
    if (id !== null) {
      out.push(new Uint8Array([TAG_STR_DICT, id]));
      return;
    }
    const utf8 = new TextEncoder().encode(value);
    const lenBuf = encodeHyb128Buf(utf8.length);
    const buf = new Uint8Array(1 + lenBuf.length + utf8.length);
    buf[0] = TAG_STR_RAW;
    buf.set(lenBuf, 1);
    buf.set(utf8, 1 + lenBuf.length);
    out.push(buf);
    return;
  }

  if (Array.isArray(value)) {
    const countBuf = encodeHyb128Buf(value.length);
    out.push(new Uint8Array([TAG_ARRAY]));
    out.push(countBuf);
    for (const v of value) {
      encodeValue(v, out);
    }
    return;
  }

  if (typeof value === "object") {
    const obj = value as Record<string, unknown>;
    const keys = Object.keys(obj);
    const countBuf = encodeHyb128Buf(keys.length);
    out.push(new Uint8Array([TAG_OBJECT]));
    out.push(countBuf);
    for (const k of keys) {
      encodeKey(k, out);
      encodeValue(obj[k], out);
    }
    return;
  }

  // Unsupported types → encode as null
  out.push(new Uint8Array([TAG_NULL]));
}

function encodeKey(key: string, out: Uint8Array[]): void {
  const id = lookupDictId(key);
  if (id !== null) {
    out.push(new Uint8Array([id]));
    return;
  }
  const utf8 = new TextEncoder().encode(key);
  const lenBuf = encodeHyb128Buf(utf8.length);
  const buf = new Uint8Array(1 + lenBuf.length + utf8.length);
  buf[0] = ID_RAW;
  buf.set(lenBuf, 1);
  buf.set(utf8, 1 + lenBuf.length);
  out.push(buf);
}

// ═══ Decoder ════════════════════════════════════════════════════════════════

function decodeValue(
  data: Uint8Array,
  pos: Int32Array, // mutable position holder
  end: number,
): unknown {
  if (pos[0] >= end) return null;
  const tag = data[pos[0]++];

  switch (tag) {
    case TAG_NULL:
      return null;

    case TAG_BOOL: {
      if (pos[0] >= end) return null;
      return data[pos[0]++] !== 0;
    }

    case TAG_FLOAT: {
      if (pos[0] + 8 > end) return null;
      const dv = new DataView(
        data.buffer,
        data.byteOffset + pos[0],
        8,
      );
      pos[0] += 8;
      return dv.getFloat64(0, true);
    }

    case TAG_INT: {
      return decodeI64Leb128(data, pos, end);
    }

    case TAG_STR_DICT: {
      if (pos[0] >= end) return null;
      const id = data[pos[0]++];
      return resolveDictId(id);
    }

    case TAG_STR_RAW: {
      const decoded = decodeHyb128(data, pos[0]);
      if (!decoded) return null;
      pos[0] += decoded.headerLen;
      const len = decoded.value;
      if (pos[0] + len > end) return null;
      const utf8 = data.subarray(pos[0], pos[0] + len);
      pos[0] += len;
      return new TextDecoder("utf-8", { fatal: true }).decode(utf8);
    }

    case TAG_ARRAY: {
      const decoded = decodeHyb128(data, pos[0]);
      if (!decoded) return null;
      pos[0] += decoded.headerLen;
      const count = Math.min(decoded.value, 1024);
      const arr: unknown[] = new Array(count);
      for (let i = 0; i < count; i++) {
        arr[i] = decodeValue(data, pos, end);
      }
      return arr;
    }

    case TAG_OBJECT: {
      const decoded = decodeHyb128(data, pos[0]);
      if (!decoded) return null;
      pos[0] += decoded.headerLen;
      const count = Math.min(decoded.value, 1024);
      const obj: Record<string, unknown> = {};
      for (let i = 0; i < count; i++) {
        const key = decodeKey(data, pos, end);
        const val = decodeValue(data, pos, end);
        if (key !== null) obj[key] = val;
      }
      return obj;
    }

    default:
      // Unknown tag — malformed
      return null;
  }
}

function decodeKey(
  data: Uint8Array,
  pos: Int32Array,
  end: number,
): string | null {
  if (pos[0] >= end) return null;
  const first = data[pos[0]++];

  if (first === ID_RAW) {
    const decoded = decodeHyb128(data, pos[0]);
    if (!decoded) return null;
    pos[0] += decoded.headerLen;
    const len = decoded.value;
    if (pos[0] + len > end) return null;
    const utf8 = data.subarray(pos[0], pos[0] + len);
    pos[0] += len;
    return new TextDecoder("utf-8", { fatal: true }).decode(utf8);
  } else if (first < STATIC_MAX) {
    return resolveDictId(first);
  } else {
    // Session-range IDs not yet supported
    return null;
  }
}

// ═══ Helpers ════════════════════════════════════════════════════════════════

function keySize(key: string): number {
  const id = lookupDictId(key);
  if (id !== null) return 1;
  return 1 + 1 + encodedLen(key.length) + key.length;
}

function encodeHyb128Buf(n: number): Uint8Array {
  const buf = new Uint8Array(11); // MAX_ENCODED_LEN
  const len = encodeHyb128(n, buf, 0);
  return buf.subarray(0, len);
}

/** Encode i64 as signed LEB128 (zigzag style). Uses BigInt to avoid 32-bit truncation. */
function encodeI64Leb128(v: number): Uint8Array {
  // Zigzag encode: (n << 1) ^ (n >> 63) — using BigInt to handle full i64 range
  let u = Number((BigInt(v) << 1n) ^ (BigInt(v) >> 63n));
  const buf: number[] = [];
  do {
    let byte = u & 0x7f;
    u >>>= 7; // unsigned right shift (keeps u positive)
    if (u !== 0) byte |= 0x80;
    buf.push(byte);
  } while (u !== 0);
  return new Uint8Array(buf);
}

/** Zigzag decode signed LEB128 from data starting at pos. */
function decodeI64Leb128(
  data: Uint8Array,
  pos: Int32Array,
  end: number,
): number | null {
  let u = 0;
  let shift = 0;
  for (let i = 0; i < 10; i++) {
    if (pos[0] >= end) return null;
    const byte = data[pos[0]++];
    u |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) {
      // Zigzag decode
      return (u >>> 1) ^ -(u & 1);
    }
    shift += 7;
    if (shift >= 64) return null; // overflow
  }
  return null;
}

function i64Leb128Len(v: number): number {
  let u = Number((BigInt(v) << 1n) ^ (BigInt(v) >> 63n));
  let len = 0;
  do {
    len++;
    u >>>= 7;
  } while (u !== 0);
  return len;
}

function concatChunks(chunks: Uint8Array[]): Uint8Array {
  let total = 0;
  for (const c of chunks) total += c.length;
  const out = new Uint8Array(total);
  let offset = 0;
  for (const c of chunks) {
    out.set(c, offset);
    offset += c.length;
  }
  return out;
}
