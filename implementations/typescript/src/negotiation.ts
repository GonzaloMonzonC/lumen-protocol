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
 *   |←── [PROBE_ACK frame] ───────|  ← Server speaks LUMEN → use binary
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

import {
  buildFrame,
  buildSize,
  parseFrame,
  TYPE_PROBE,
  TYPE_PROBE_ACK,
} from "./frame.js";
import { compressValue, decompressValue } from "./compress.js";

// ═══ Constants ══════════════════════════════════════════════════════════════

/** Default probe timeout in milliseconds. */
export const DEFAULT_PROBE_TIMEOUT_MS = 500;

/** Current LUMEN protocol version. */
const LUMEN_VERSION = 1;

// ═══ Types ══════════════════════════════════════════════════════════════════

/** LUMEN PROBE payload: client capabilities. */
export interface LumenProbe {
  v: number;
  caps: string[];
}

/** LUMEN PROBE_ACK payload: server capabilities (intersection with client). */
export interface LumenAck {
  v: number;
  caps: string[];
}

/** Default client probe payload. */
export const DEFAULT_PROBE: LumenProbe = {
  v: LUMEN_VERSION,
  caps: ["compression", "streaming"],
};

// ═══ Build ══════════════════════════════════════════════════════════════════

/**
 * Build a LUMEN PROBE frame as a raw binary Uint8Array.
 * The probe payload is compressed using the LUMEN compact encoder.
 */
export function buildProbe(probe: LumenProbe = DEFAULT_PROBE): Uint8Array {
  const payload = compressValue(probe as unknown as Record<string, unknown>);
  const total = buildSize(payload.length);
  const buf = new Uint8Array(total);
  buildFrame(TYPE_PROBE, 0x01 /* FLAG_COMPRESSED */, payload, buf, 0);
  return buf;
}

/**
 * Build a LUMEN PROBE_ACK frame as a raw binary Uint8Array.
 */
export function buildAck(ack: LumenAck): Uint8Array {
  const payload = compressValue(ack as unknown as Record<string, unknown>);
  const total = buildSize(payload.length);
  const buf = new Uint8Array(total);
  buildFrame(TYPE_PROBE_ACK, 0x01 /* FLAG_COMPRESSED */, payload, buf, 0);
  return buf;
}

// ═══ Parse ══════════════════════════════════════════════════════════════════

/**
 * Try to parse a LUMEN PROBE_ACK frame from raw bytes.
 * Returns `null` if the data is not a valid ACK frame.
 */
export function parseAck(data: Uint8Array): LumenAck | null {
  const result = parseFrame(data, 0);
  if (result.kind !== "complete") return null;
  if (result.frame.frameType !== TYPE_PROBE_ACK) return null;

  try {
    const value = decompressValue(result.frame.payload);
    if (!value || typeof value !== "object") return null;
    const obj = value as Record<string, unknown>;
    if (typeof obj.v !== "number" || !Array.isArray(obj.caps)) return null;
    return {
      v: obj.v as number,
      caps: obj.caps as string[],
    };
  } catch {
    return null;
  }
}

/**
 * Try to parse a LUMEN PROBE frame from raw bytes.
 * Returns `null` if the data is not a valid PROBE frame.
 */
export function parseProbe(data: Uint8Array): LumenProbe | null {
  const result = parseFrame(data, 0);
  if (result.kind !== "complete") return null;
  if (result.frame.frameType !== TYPE_PROBE) return null;

  try {
    const value = decompressValue(result.frame.payload);
    if (!value || typeof value !== "object") return null;
    const obj = value as Record<string, unknown>;
    if (typeof obj.v !== "number" || !Array.isArray(obj.caps)) return null;
    return {
      v: obj.v as number,
      caps: obj.caps as string[],
    };
  } catch {
    return null;
  }
}

// ═══ Helpers ════════════════════════════════════════════════════════════════
