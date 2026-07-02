/**
 * @lumen/mcp-transport — LUMEN binary transport for MCP SDK
 *
 * Drop-in replacement transports that speak LUMEN binary protocol
 * natively, with automatic fallback to JSON-RPC.
 *
 * @packageDocumentation
 */

// ═══ Transports ═════════════════════════════════════════════════════════════

export {
  LumenStdioTransport,
  LumenWebSocketTransport,
} from "./transport.js";
export type {
  Transport,
  JsonRpcMessage,
  LumenTransportOptions,
  LumenStdioOptions,
  LumenWebSocketOptions,
  WebSocketLike,
  MessageEventLike,
} from "./transport.js";
export { WebSocketReadyState } from "./transport.js";

// ═══ Negotiation ════════════════════════════════════════════════════════════

export {
  buildProbe,
  buildAck,
  parseProbe,
  parseAck,
  DEFAULT_PROBE_TIMEOUT_MS,
} from "./negotiation.js";
export type { LumenProbe, LumenAck } from "./negotiation.js";

// ═══ Cadencia Bridge ════════════════════════════════════════════════════════

export { CadenciaBridge } from "./cadencia.js";
export type {
  BridgeCommand,
  BridgeResponse,
  BridgeOptions,
} from "./cadencia.js";

// ═══ Low-level encoders (for advanced use) ══════════════════════════════════

export {
  encodeHyb128,
  decodeHyb128,
  encodedLen as hyb128EncodedLen,
} from "./hyb128.js";
export type { Hyb128Decoded } from "./hyb128.js";

export {
  buildFrame,
  buildSize,
  parseFrame,
  typeName,
  isCompressed,
  isEncrypted,
  isPriority,
  isFragmented,
  TYPE_REQUEST,
  TYPE_RESPONSE,
  TYPE_NOTIFY,
  TYPE_STREAM_DATA,
  TYPE_SCHEMA_PATCH,
  TYPE_STREAM_INIT,
  TYPE_DICT_SYNC,
  TYPE_DISCOVER,
  TYPE_MUX,
  TYPE_HEARTBEAT,
  TYPE_TRANSPORT_INIT,
  TYPE_TRANSPORT_ACK,
  TYPE_BATCH,
  TYPE_FLOW_CTL,
  FLAG_FLOW_PAUSE,
  TYPE_PROBE,
  TYPE_PROBE_ACK,
  FLAG_COMPRESSED,
  FLAG_ENCRYPTED,
  FLAG_PRIORITY,
  FLAG_FRAGMENTED,
} from "./frame.js";
export type { Frame, ParseResult } from "./frame.js";

export { FrameAssembler } from "./frame-assembler.js";

export {
  compressValue,
  compressInto,
  decompressValue,
  compressedSize,
} from "./compress.js";

export {
  compressValue as compressValueFFI,
  compressInto as compressIntoFFI,
  decompressValue as decompressValueFFI,
  compressedSize as compressedSizeFFI,
} from "./compress_ffi.js";

export {
  ZeroAllocDecompressor,
  decompressValueZeroAlloc,
} from "./zeroalloc.js";

export {
  resolveDictId,
  lookupDictId,
  registerSessionKey,
  unregisterSessionKey,
  initSessionDict,
  clearSessionDict,
  sessionDictSize,
  ID_RAW,
  STATIC_MAX,
  SESSION_MAX,
  TOTAL_ENTRIES,
} from "./dict.js";

// ═══ Level 2: Zero-Copy Shared Memory (FFI) ═══════════════════════════════

export {
  ShmTransportFFI,
  RING_A,
  RING_B,
  DEFAULT_SHM_SIZE,
} from "./shm_ffi.js";

// ═══ Level 3: Datagram Transport (UDP / multicast) ══════════════════════════

export {
  DatagramTransport,
  buildDgram,
  parseDgram,
  MAX_DATAGRAM_SIZE,
  MAX_FRAME_PAYLOAD,
  DEFAULT_MULTICAST_TTL,
} from "./dgram.js";
export type { DatagramTransportOptions } from "./dgram.js";

// ═══ Constants ═══════════════════════════════════════════════════════════════

/** LUMEN protocol version implemented by this package. */
export const LUMEN_VERSION = 1;

/** Maximum Hyb128 encoded length in bytes. */
export const HYB128_MAX_ENCODED_LEN = 11;
