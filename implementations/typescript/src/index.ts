/**
 * @lumen/mcp-transport — LUMEN binary transport for MCP SDK
 *
 * Drop-in replacement transports that speak LUMEN binary protocol
 * natively, with automatic fallback to JSON-RPC.
 *
 * @packageDocumentation
 */

// ── Public API ───────────────────────────────────────────────────────────────

export { LumenStdioTransport } from "./transport.js";
export { LumenWebSocketTransport } from "./transport.js";
export type { LumenTransportOptions, LumenStdioOptions } from "./transport.js";

// ── Low-level encoders (for advanced use) ────────────────────────────────────

export { encodeHyb128, decodeHyb128, hyb128EncodedLen } from "./hyb128.js";
export { buildFrame, parseFrame, FrameType, FrameFlag } from "./frame.js";
export { compressValue, decompressValue } from "./compress.js";
export { resolveDictId, lookupDictId } from "./dict.js";

// ── Constants ────────────────────────────────────────────────────────────────

/** LUMEN protocol version implemented by this package. */
export const LUMEN_VERSION = 1;

/** Maximum Hyb128 encoded length in bytes. */
export const HYB128_MAX_ENCODED_LEN = 11;
