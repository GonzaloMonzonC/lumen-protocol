/**
 * Frame — LUMEN binary frame builder and parser.
 *
 * Frame format:
 * ```
 * [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]
 * ```
 *
 * Hyb128 encodes PAYLOAD length only (not TYPE+FLAGS).
 */

// ── Frame Types ──────────────────────────────────────────────────────────────

export enum FrameType {
  REQUEST = 0x01,
  RESPONSE = 0x02,
  NOTIFY = 0x03,
  STREAM_DATA = 0x04,
  SCHEMA_PATCH = 0x05,
  STREAM_INIT = 0x06,
  DICT_SYNC = 0x07,
  DISCOVER = 0x08,
  MUX = 0x09,
  HEARTBEAT = 0x0A,
  PROBE = 0x0F,
  PROBE_ACK = 0x10,
}

// ── Frame Flags ──────────────────────────────────────────────────────────────

export enum FrameFlag {
  /** Payload is compressed with dictionary encoding. */
  COMPRESSED = 0x01,
  /** Frame is a stream continuation. */
  STREAM = 0x02,
  /** Frame is the last in a stream. */
  STREAM_END = 0x04,
}

// ── Parsed Frame ─────────────────────────────────────────────────────────────

export interface ParsedFrame {
  type: FrameType;
  flags: number;
  payload: Buffer;
  /** Total bytes consumed from input (including header). */
  consumed: number;
}

export type ParseResult =
  | { kind: "complete"; frame: ParsedFrame }
  | { kind: "incomplete"; needed: number }
  | { kind: "error"; message: string };

// ── Builder ──────────────────────────────────────────────────────────────────

/**
 * Build a LUMEN frame into a Buffer.
 * Returns the number of bytes written.
 */
export function buildFrame(
  type: FrameType,
  flags: number,
  payload: Buffer,
  buf: Buffer,
  offset = 0
): number {
  // TODO: port from Rust (src/frame.rs)
  throw new Error("frame.buildFrame: not yet implemented");
}

/** Total buffer size needed for a frame with the given payload length. */
export function buildSize(payloadLen: number): number {
  // Hyb128 header + TYPE + FLAGS + payload
  const { hyb128EncodedLen } = require("./hyb128.js");
  return hyb128EncodedLen(payloadLen) + 2 + payloadLen;
}

// ── Parser ───────────────────────────────────────────────────────────────────

/**
 * Parse a LUMEN frame from a Buffer.
 */
export function parseFrame(buf: Buffer, offset = 0): ParseResult {
  // TODO: port from Rust (src/frame.rs)
  throw new Error("frame.parseFrame: not yet implemented");
}
