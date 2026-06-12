/**
 * Frame — LUMEN binary frame builder and parser.
 *
 * Frame format:
 * ```
 * [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]
 * ```
 *
 * Hyb128 encodes PAYLOAD length only (not TYPE+FLAGS).
 *
 * Ported from Rust `src/frame.rs`.
 */

import { decodeHyb128, encodeHyb128, encodedLen } from "./hyb128.js";

// ═══ Frame Types ═══════════════════════════════════════════════════════════

/** Request: client asks server to perform an operation. */
export const TYPE_REQUEST = 0x01;
/** Response: server replies to a request. */
export const TYPE_RESPONSE = 0x02;
/** Notification: fire-and-forget message. */
export const TYPE_NOTIFY = 0x03;
/** Stream data chunk (after STREAM_INIT). */
export const TYPE_STREAM_DATA = 0x04;
/** Schema delta update. */
export const TYPE_SCHEMA_PATCH = 0x05;
/** Initialize a token/element stream. */
export const TYPE_STREAM_INIT = 0x06;
/** Dictionary synchronization frame. */
export const TYPE_DICT_SYNC = 0x07;
/** Dynamic discovery / introspection request. */
export const TYPE_DISCOVER = 0x08;
/** Multiplex wrapper (carries another frame on a logical channel). */
export const TYPE_MUX = 0x09;
/** Heartbeat / keep-alive. */
export const TYPE_HEARTBEAT = 0x0a;
/** Protocol probe (negotiation). */
export const TYPE_PROBE = 0x0f;
/** Protocol probe acknowledgement. */
export const TYPE_PROBE_ACK = 0x10;

// ═══ Frame Flags ═══════════════════════════════════════════════════════════

/** Payload is compressed with dictionary encoding. */
export const FLAG_COMPRESSED = 0x01;
/** Payload is encrypted. */
export const FLAG_ENCRYPTED = 0x02;
/** Priority frame (expedite). */
export const FLAG_PRIORITY = 0x04;
/** Frame is fragmented (continuation follows). */
export const FLAG_FRAGMENTED = 0x08;

// ═══ Frame struct ══════════════════════════════════════════════════════════

/** A parsed LUMEN frame header + payload reference. */
export interface Frame {
  /** Frame type (see TYPE_* constants). */
  frameType: number;
  /** Bitmask of FLAG_*. */
  flags: number;
  /** Payload bytes (slice of the original buffer for zero-copy). */
  payload: Uint8Array;
}

// ═══ ParseResult ═══════════════════════════════════════════════════════════

export type ParseResult =
  | { kind: "complete"; frame: Frame; consumed: number }
  | { kind: "incomplete" }
  | { kind: "incompletePayload"; expected: number; available: number }
  | { kind: "error"; message: string };

// ═══ Builder ═══════════════════════════════════════════════════════════════

/**
 * Build a LUMEN frame into `buf` at `offset`.
 *
 * Returns the number of bytes written.
 * Panics (throws) if the buffer is too small.
 */
export function buildFrame(
  frameType: number,
  flags: number,
  payload: Uint8Array,
  buf: Uint8Array,
  offset = 0,
): number {
  const headerLen = encodedLen(payload.length);
  const total = headerLen + 2 + payload.length;

  const n = encodeHyb128(payload.length, buf, offset);
  buf[offset + n] = frameType;
  buf[offset + n + 1] = flags;
  buf.set(payload, offset + n + 2);

  return total;
}

/** Total buffer size needed for a frame with the given payload length. */
export function buildSize(payloadLen: number): number {
  return encodedLen(payloadLen) + 2 + payloadLen;
}

// ═══ Parser ════════════════════════════════════════════════════════════════

/**
 * Attempt to parse one LUMEN frame from `bytes` at `offset`.
 *
 * On success, returns `{ kind: "complete", ... }` with the frame and
 * how many bytes were consumed. The remaining bytes can be fed back on
 * the next call — enabling streaming parsing over TCP/UDS/stdio.
 */
export function parseFrame(
  bytes: Uint8Array,
  offset = 0,
): ParseResult {
  if (offset >= bytes.length) {
    return { kind: "incomplete" };
  }

  // 1. Decode the Hyb128 length
  const decoded = decodeHyb128(bytes, offset);
  if (!decoded) {
    return { kind: "incomplete" };
  }

  const headerLen = decoded.headerLen;
  const payloadLen = decoded.value;

  // 2. Read TYPE and FLAGS
  const typeOffset = offset + headerLen;
  const flagsOffset = typeOffset + 1;
  const payloadOffset = flagsOffset + 1;

  if (payloadOffset > bytes.length) {
    return { kind: "incomplete" };
  }

  const frameType = bytes[typeOffset];
  const flags = bytes[flagsOffset];

  // 3. Verify payload length
  const totalLen = payloadOffset + payloadLen;
  if (bytes.length < totalLen) {
    return {
      kind: "incompletePayload",
      expected: totalLen,
      available: bytes.length,
    };
  }

  // 4. Extract payload (zero-copy slice via subarray)
  const payload = bytes.subarray(payloadOffset, totalLen);

  return {
    kind: "complete",
    frame: { frameType, flags, payload },
    consumed: totalLen - offset,
  };
}

// ═══ Helpers ═══════════════════════════════════════════════════════════════

/** Human-readable name for a frame type. */
export function typeName(frameType: number): string {
  const names: Record<number, string> = {
    [TYPE_REQUEST]: "REQUEST",
    [TYPE_RESPONSE]: "RESPONSE",
    [TYPE_NOTIFY]: "NOTIFY",
    [TYPE_STREAM_DATA]: "STREAM_DATA",
    [TYPE_SCHEMA_PATCH]: "SCHEMA_PATCH",
    [TYPE_STREAM_INIT]: "STREAM_INIT",
    [TYPE_DICT_SYNC]: "DICT_SYNC",
    [TYPE_DISCOVER]: "DISCOVER",
    [TYPE_MUX]: "MUX",
    [TYPE_HEARTBEAT]: "HEARTBEAT",
    [TYPE_PROBE]: "PROBE",
    [TYPE_PROBE_ACK]: "PROBE_ACK",
  };
  return names[frameType] ?? `UNKNOWN(0x${frameType.toString(16)})`;
}

/** Check if a frame has the COMPRESSED flag set. */
export function isCompressed(frame: Frame): boolean {
  return (frame.flags & FLAG_COMPRESSED) !== 0;
}

/** Check if a frame has the ENCRYPTED flag set. */
export function isEncrypted(frame: Frame): boolean {
  return (frame.flags & FLAG_ENCRYPTED) !== 0;
}

/** Check if a frame has the PRIORITY flag set. */
export function isPriority(frame: Frame): boolean {
  return (frame.flags & FLAG_PRIORITY) !== 0;
}

/** Check if a frame has the FRAGMENTED flag set. */
export function isFragmented(frame: Frame): boolean {
  return (frame.flags & FLAG_FRAGMENTED) !== 0;
}
