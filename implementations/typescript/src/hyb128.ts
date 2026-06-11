/**
 * Hyb128 — Hybrid length encoding with O(1) decode.
 *
 * 4 encoding modes selected by the top 2 bits of the first byte:
 *
 * | Mode | Bits | Range         | Bytes          |
 * |------|------|---------------|----------------|
 * | `00` | 00   | 0–63 B        | 1 byte         |
 * | `10` | 10   | 64 B–64 KB    | 3 bytes (u16)  |
 * | `11` | 11   | 64 KB–4 GB    | 5 bytes (u32)  |
 * | `01` | 01   | >4 GB         | LEB128 variable|
 */

/** Maximum encoded length of a Hyb128 value (11 bytes). */
export const MAX_ENCODED_LEN = 11;

/** Decoded Hyb128 result. */
export interface Hyb128Decoded {
  /** The decoded numeric value. */
  value: number;
  /** Number of bytes consumed from the header. */
  headerLen: number;
}

/**
 * Encode a value as Hyb128 into a Buffer at the given offset.
 * Returns the number of bytes written.
 */
export function encodeHyb128(value: number, buf: Buffer, offset = 0): number {
  // TODO: port from Rust (src/hyb128.rs)
  throw new Error("hyb128.encodeHyb128: not yet implemented");
}

/**
 * Decode a Hyb128 value from a Buffer at the given offset.
 * Returns `null` if the buffer is too short.
 */
export function decodeHyb128(buf: Buffer, offset = 0): Hyb128Decoded | null {
  // TODO: port from Rust (src/hyb128.rs)
  throw new Error("hyb128.decodeHyb128: not yet implemented");
}

/**
 * Number of bytes needed to encode `value` as Hyb128.
 */
export function hyb128EncodedLen(value: number): number {
  if (value <= 63) return 1;
  if (value <= 65535) return 3;
  if (value <= 4294967295) return 5;
  // LEB128 fallback
  let v = value;
  let len = 0;
  do {
    len++;
    v >>= 7;
  } while (v > 0);
  return len + 1; // +1 for mode byte
}
