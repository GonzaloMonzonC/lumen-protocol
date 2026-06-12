/**
 * Hyb128 — Hybrid length encoding with O(1) decode.
 *
 * = Encoding scheme =
 *
 * Byte 0: `[MODE:2bits][PAYLOAD:6bits]`
 *
 * | Mode | Bits | Meaning                              | Total bytes |
 * |------|------|--------------------------------------|-------------|
 * | `00` | `00` | Payload is the 6 lower bits (0..63)  | 1           |
 * | `01` | `01` | Next bytes are LEB128 continuation   | 2–11        |
 * | `10` | `10` | Next 2 bytes are u16 little-endian   | 3           |
 * | `11` | `11` | Next 4 bytes are u32 little-endian   | 5           |
 *
 * = Properties =
 *
 * - **O(1) header parse**: the mode bits tell the parser exactly how many
 *   bytes to skip in a single branch.
 * - **Zero overhead for small messages**: 63-byte payloads cost 1 byte.
 * - **Scales to 4 GiB**: mode `11` covers any realistic MCP payload.
 *
 * Ported from Rust `src/hyb128.rs`.
 */

// ═══ Constants ══════════════════════════════════════════════════════════════

/** Maximum value encodable in mode `00` (6 bits). */
export const MAX_SHORT = 0x3f; // 63

/** Maximum encoded length of any Hyb128 value (1 mode byte + 10 LEB128). */
export const MAX_ENCODED_LEN = 11;

// Mode byte tags (upper 2 bits of the first byte)
const MODE_MASK = 0xc0;
const SHORT_MASK = 0x3f;
const MODE_SHORT = 0x00; // 00______
const MODE_LEB128 = 0x40; // 01______
const MODE_U16 = 0x80; // 10______
const MODE_U32 = 0xc0; // 11______

// ═══ Decoded result ════════════════════════════════════════════════════════

/** Result of decoding a Hyb128 value. */
export interface Hyb128Decoded {
  /** The decoded numeric value (payload length). */
  value: number;
  /** Number of bytes consumed from the input buffer. */
  headerLen: number;
}

// ═══ Encode ════════════════════════════════════════════════════════════════

/**
 * Encode `value` into `buf` at `offset`.
 *
 * Returns the number of bytes written (1, 3, 5, or 2–11 for LEB128).
 * Throws if the buffer is too small.
 *
 * @param value  Must be a non-negative safe integer.
 */
export function encodeHyb128(
  value: number,
  buf: Uint8Array,
  offset = 0,
): number {
  if (!Number.isSafeInteger(value) || value < 0) {
    throw new RangeError(
      `hyb128.encode: value must be a safe non-negative integer, got ${value}`,
    );
  }

  // Mode 00: 6-bit short (0–63)
  if (value <= MAX_SHORT) {
    buf[offset] = MODE_SHORT | (value & SHORT_MASK);
    return 1;
  }

  // Mode 10: u16 little-endian (64 – 65535)
  if (value <= 0xffff) {
    buf[offset] = MODE_U16;
    buf[offset + 1] = value & 0xff;
    buf[offset + 2] = (value >>> 8) & 0xff;
    return 3;
  }

  // Mode 11: u32 little-endian (65536 – 4294967295)
  if (value <= 0xffffffff) {
    buf[offset] = MODE_U32;
    buf[offset + 1] = value & 0xff;
    buf[offset + 2] = (value >>> 8) & 0xff;
    buf[offset + 3] = (value >>> 16) & 0xff;
    buf[offset + 4] = (value >>> 24) & 0xff;
    return 5;
  }

  // Mode 01: LEB128 fallback (extremely rare — values > 4 GiB)
  buf[offset] = MODE_LEB128;
  return 1 + leb128Encode(value, buf, offset + 1);
}

/**
 * Number of bytes `encodeHyb128(value)` would consume.
 */
export function encodedLen(value: number): number {
  if (value <= MAX_SHORT) return 1;
  if (value <= 0xffff) return 3;
  if (value <= 0xffffffff) return 5;
  // LEB128 worst case: 1 mode + up to 10 bytes
  let v = value;
  let len = 1; // mode byte
  do {
    len++;
    v >>>= 7;
  } while (v > 0);
  return len;
}

// ═══ Decode ════════════════════════════════════════════════════════════════

/**
 * Decode a Hyb128 value from `buf` at `offset`.
 *
 * Returns `null` if the buffer is too short to contain a complete header.
 */
export function decodeHyb128(
  buf: Uint8Array,
  offset = 0,
): Hyb128Decoded | null {
  if (offset >= buf.length) return null;

  const first = buf[offset];
  const mode = first & MODE_MASK;

  switch (mode) {
    // ── Mode 00: 6-bit short ──────────────────────────────────────────
    case MODE_SHORT:
      return { value: first & SHORT_MASK, headerLen: 1 };

    // ── Mode 10: u16 little-endian ────────────────────────────────────
    case MODE_U16: {
      if (offset + 3 > buf.length) return null;
      return {
        value: buf[offset + 1] | (buf[offset + 2] << 8),
        headerLen: 3,
      };
    }

    // ── Mode 11: u32 little-endian ────────────────────────────────────
    case MODE_U32: {
      if (offset + 5 > buf.length) return null;
      return {
        value:
          (buf[offset + 1] |
            (buf[offset + 2] << 8) |
            (buf[offset + 3] << 16) |
            (buf[offset + 4] << 24)) >>> 0,
        headerLen: 5,
      };
    }

    // ── Mode 01: LEB128 ───────────────────────────────────────────────
    case MODE_LEB128:
      return leb128Decode(buf, offset + 1);

    default:
      return null;
  }
}

// ═══ LEB128 helpers (mode 01 path) ═════════════════════════════════════════

function leb128Encode(value: number, buf: Uint8Array, offset: number): number {
  let written = 0;
  let v = value;
  do {
    let byte = v & 0x7f;
    v >>>= 7;
    if (v !== 0) byte |= 0x80;
    buf[offset + written] = byte;
    written++;
  } while (v > 0);
  return written;
}

function leb128Decode(
  buf: Uint8Array,
  offset: number,
): Hyb128Decoded | null {
  let value = 0;
  let shift = 0;
  for (let i = 0; i < 10; i++) {
    if (offset + i >= buf.length) return null;
    const byte = buf[offset + i];
    value |= (byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) {
      return { value: value >>> 0, headerLen: 1 + i + 1 };
    }
    shift += 7;
    if (shift >= 64) return null;
  }
  return null;
}
