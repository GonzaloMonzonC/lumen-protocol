/**
 * Dictionary — 128 static + 127 session IDs for key compression.
 *
 * | Range       | Purpose                  |
 * |-------------|--------------------------|
 * | `0x00-0x7F` | Static dictionary (128)  |
 * | `0x80-0xFE` | Session dictionary (127) |
 * | `0xFF`      | Raw UTF-8 key (escape)   |
 *
 * Keys that appear in the static dictionary are encoded as 1 byte
 * instead of their full UTF-8 representation.
 *
 * Ported from Rust `src/dict.rs`.
 */

// ═══ Reserved IDs ══════════════════════════════════════════════════════════

/** Maximum static dictionary ID (exclusive). */
export const STATIC_MAX = 0x80;

/** Maximum session dictionary ID (exclusive). */
export const SESSION_MAX = 0xff;

/** Sentinel: key is not in the dictionary, sent as raw text. */
export const ID_RAW = 0xff;

/** Total number of usable dictionary entries (static + session). */
export const TOTAL_ENTRIES = 255;

// ═══ Static dictionary (128 entries, IDs 0x00..0x7F) ══════════════════════

const STATIC_DICT: (string | null)[] = new Array(STATIC_MAX).fill(null);

// Core MCP/RPC keys (0x00..0x0F)
STATIC_DICT[0x00] = "tool";
STATIC_DICT[0x01] = "arguments";
STATIC_DICT[0x02] = "result";
STATIC_DICT[0x03] = "error";
STATIC_DICT[0x04] = "id";
STATIC_DICT[0x05] = "name";
STATIC_DICT[0x06] = "description";
STATIC_DICT[0x07] = "content";
STATIC_DICT[0x08] = "text";
STATIC_DICT[0x09] = "type";
STATIC_DICT[0x0a] = "method";
STATIC_DICT[0x0b] = "params";
STATIC_DICT[0x0c] = "jsonrpc";
STATIC_DICT[0x0d] = "data";
STATIC_DICT[0x0e] = "code";
STATIC_DICT[0x0f] = "message";

// Input/output (0x10..0x1F)
STATIC_DICT[0x10] = "input";
STATIC_DICT[0x11] = "output";
STATIC_DICT[0x12] = "stream";
STATIC_DICT[0x13] = "uri";
STATIC_DICT[0x14] = "mimeType";
STATIC_DICT[0x15] = "encoding";
STATIC_DICT[0x16] = "language";
STATIC_DICT[0x17] = "title";
STATIC_DICT[0x18] = "value";
STATIC_DICT[0x19] = "key";
STATIC_DICT[0x1a] = "path";
STATIC_DICT[0x1b] = "version";
STATIC_DICT[0x1c] = "schema";
STATIC_DICT[0x1d] = "default";
STATIC_DICT[0x1e] = "required";
STATIC_DICT[0x1f] = "properties";

// Resources & tools (0x20..0x2F)
STATIC_DICT[0x20] = "resources";
STATIC_DICT[0x21] = "tools";
STATIC_DICT[0x22] = "prompts";
STATIC_DICT[0x23] = "resource";
STATIC_DICT[0x24] = "prompt";
STATIC_DICT[0x25] = "handler";
STATIC_DICT[0x26] = "capabilities";
STATIC_DICT[0x27] = "permissions";
STATIC_DICT[0x28] = "scope";
STATIC_DICT[0x29] = "tags";
STATIC_DICT[0x2a] = "category";
STATIC_DICT[0x2b] = "icon";
STATIC_DICT[0x2c] = "metadata";
STATIC_DICT[0x2d] = "timestamp";
STATIC_DICT[0x2e] = "status";
STATIC_DICT[0x2f] = "progress";

// Errors & status (0x30..0x3F)
STATIC_DICT[0x30] = "severity";
STATIC_DICT[0x31] = "details";
STATIC_DICT[0x32] = "cause";
STATIC_DICT[0x33] = "stack";
STATIC_DICT[0x34] = "line";
STATIC_DICT[0x35] = "column";
STATIC_DICT[0x36] = "source";
STATIC_DICT[0x37] = "retry";
STATIC_DICT[0x38] = "timeout";
STATIC_DICT[0x39] = "limit";
STATIC_DICT[0x3a] = "offset";
STATIC_DICT[0x3b] = "count";
STATIC_DICT[0x3c] = "total";
STATIC_DICT[0x3d] = "page";
STATIC_DICT[0x3e] = "cursor";
STATIC_DICT[0x3f] = "next";

// LLM-specific (0x40..0x4F)
STATIC_DICT[0x40] = "model";
STATIC_DICT[0x41] = "provider";
STATIC_DICT[0x42] = "temperature";
STATIC_DICT[0x43] = "max_tokens";
STATIC_DICT[0x44] = "stop";
STATIC_DICT[0x45] = "frequency_penalty";
STATIC_DICT[0x46] = "presence_penalty";
STATIC_DICT[0x47] = "top_p";
STATIC_DICT[0x48] = "logprobs";
STATIC_DICT[0x49] = "user";
STATIC_DICT[0x4a] = "system";
STATIC_DICT[0x4b] = "assistant";
STATIC_DICT[0x4c] = "function";
STATIC_DICT[0x4d] = "tool_calls";
STATIC_DICT[0x4e] = "finish_reason";
STATIC_DICT[0x4f] = "usage";

// ═══ Reverse lookup (lazily-built O(1) HashMap) ═══════════════════════════

let reverseMap: Map<string, number> | null = null;

function getReverseMap(): Map<string, number> {
  if (!reverseMap) {
    reverseMap = new Map();
    for (let i = 0; i < STATIC_MAX; i++) {
      const key = STATIC_DICT[i];
      if (key !== null) {
        reverseMap.set(key, i);
      }
    }
  }
  return reverseMap;
}

// ═══ Public API ════════════════════════════════════════════════════════════

/**
 * Resolve a dictionary ID to its key string.
 * Returns `null` if the ID is not in the static dictionary.
 * ID 0xFF (`ID_RAW`) always returns `null` (meaning "inline text").
 */
export function resolveDictId(id: number): string | null {
  if (id < STATIC_MAX) {
    return STATIC_DICT[id];
  }
  // Session dictionary not yet implemented
  return null;
}

/**
 * O(1) reverse lookup: find the static dictionary ID for a key string.
 * Uses a lazily-built `Map` for constant-time lookup.
 *
 * Always prefer this over linear scan in hot paths (serialization, compression).
 */
export function lookupDictId(key: string): number | null {
  return getReverseMap().get(key) ?? null;
}
