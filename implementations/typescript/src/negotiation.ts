/**
 * Protocol negotiation — LUMEN probe/ack handshake with JSON-RPC fallback.
 *
 * Flow:
 * ```
 * Client                         Server
 *   |                              |
 *   |── [PROBE frame (binary)] ──→|
 *   |                              |
 *   |  (wait up to probeTimeoutMs) |
 *   |                              |
 *   |←── [ACK frame (binary)] ────|  ← Server speaks LUMEN → use binary
 *   |                              |
 *   OR                            |
 *   |                              |
 *   |  (timeout after N ms)        |  ← Server doesn't speak LUMEN
 *   |                              |     → fallback to JSON-RPC
 *   |── {"jsonrpc":"2.0",...} ───→|
 * ```
 *
 * The probe is sent as a raw LUMEN binary frame BEFORE any MCP
 * initialization. JSON-RPC-only servers will ignore the binary
 * frame (it looks like garbage JSON to them). After the timeout,
 * the client sends the standard MCP initialize request as JSON.
 */

import { FrameType } from "./frame.js";

/** Default probe timeout in milliseconds. */
export const DEFAULT_PROBE_TIMEOUT_MS = 500;

/** LUMEN PROBE payload: client capabilities. */
export interface LumenProbe {
  v: number;
  caps: string[];
}

/** LUMEN ACK payload: server capabilities (intersection with client). */
export interface LumenAck {
  v: number;
  caps: string[];
}

/**
 * Default client probe payload.
 */
export const DEFAULT_PROBE: LumenProbe = {
  v: 1,
  caps: ["compression", "streaming"],
};

/**
 * Build a LUMEN PROBE frame (raw binary Buffer).
 */
export function buildProbe(probe: LumenProbe = DEFAULT_PROBE): Buffer {
  // TODO: encode probe as LUMEN frame with TYPE=PROBE (0x0F)
  throw new Error("negotiation.buildProbe: not yet implemented");
}

/**
 * Try to parse a LUMEN ACK frame from raw bytes.
 * Returns null if the data is not a valid ACK frame.
 */
export function parseAck(data: Buffer): LumenAck | null {
  // TODO: parse TYPE=PROBE_ACK (0x10) frame, decompress payload
  throw new Error("negotiation.parseAck: not yet implemented");
}
