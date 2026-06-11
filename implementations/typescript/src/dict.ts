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
 */

/** Static dictionary: ID → key. Indexed by ID. */
const STATIC_DICT: (string | null)[] = new Array(128).fill(null);

/** Reverse lookup: key → ID. Built lazily. */
let reverseMap: Map<string, number> | null = null;

// ── Static entries (aligned with Rust dict.rs) ───────────────────────────────

const STATIC_ENTRIES: [number, string][] = [
  [0x00, "tool"],
  [0x01, "arguments"],
  [0x02, "result"],
  [0x03, "error"],
  [0x04, "method"],
  [0x05, "params"],
  [0x06, "id"],
  [0x07, "jsonrpc"],
  [0x08, "text"],
  [0x09, "data"],
  [0x0A, "code"],
  [0x0B, "message"],
  [0x0C, "name"],
  [0x0D, "description"],
  [0x0E, "type"],
  [0x0F, "content"],
  [0x10, "uri"],
  [0x11, "path"],
  [0x12, "query"],
  [0x13, "value"],
  [0x14, "key"],
  [0x15, "url"],
  [0x16, "title"],
  [0x17, "status"],
  [0x18, "version"],
  [0x19, "language"],
  [0x1A, "inputSchema"],
  [0x1B, "properties"],
  [0x1C, "required"],
  [0x1D, "stream"],
  [0x1E, "token"],
  [0x20, "resources"],
  [0x21, "tools"],
  [0x22, "prompts"],
  [0x30, "model"],
  [0x31, "provider"],
  [0x32, "temperature"],
  [0x33, "max_tokens"],
  [0x34, "stop"],
  [0x40, "command"],
  [0x41, "args"],
  [0x42, "env"],
  [0x43, "cwd"],
  [0x4F, "usage"],
  [0x50, "total"],
  [0x51, "prompt"],
  [0x52, "completion"],
  [0x60, "file"],
  [0x61, "start_line"],
  [0x62, "end_line"],
  [0x63, "max_results"],
  [0x64, "recursive"],
  [0x65, "overwrite"],
  [0x66, "timeout_ms"],
  [0x67, "working_dir"],
  [0x68, "severity"],
  [0x69, "operation"],
];

// Initialize static dictionary
for (const [id, key] of STATIC_ENTRIES) {
  STATIC_DICT[id] = key;
}

/** Sentinel: raw UTF-8 key follows. */
export const ID_RAW = 0xFF;

/** Maximum static dictionary ID. */
export const STATIC_MAX = 0x7F;

// ── Public API ───────────────────────────────────────────────────────────────

/**
 * Resolve a dictionary ID to its key string.
 * Returns `null` if the ID is not in the static dictionary.
 */
export function resolveDictId(id: number): string | null {
  if (id < STATIC_DICT.length) {
    return STATIC_DICT[id];
  }
  return null;
}

/**
 * Look up a key in the dictionary, returning its ID.
 * Returns `null` if the key is not in the static dictionary.
 */
export function lookupDictId(key: string): number | null {
  if (!reverseMap) {
    reverseMap = new Map();
    for (let i = 0; i < STATIC_DICT.length; i++) {
      const k = STATIC_DICT[i];
      if (k !== null) {
        reverseMap.set(k, i);
      }
    }
  }
  return reverseMap.get(key) ?? null;
}
