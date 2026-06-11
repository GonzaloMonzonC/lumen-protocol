//! Dictionary-based compression for LUMEN frames.
//!
//! ## Architecture
//!
//! The dictionary maps common MCP keys (like `"tool"`, `"arguments"`, `"result"`)
//! to 1-byte IDs (0x00..0x7F for static/base, 0x80..0xFE for session-dynamic).
//! ID 0xFF is reserved for "uncompressed, inline text".
//!
//! ## Static dictionary (128 entries, IDs 0x00..0x7F)
//!
//! These are defined in the LUMEN specification and never change.
//! See `DICTIONARY.md` for the full table.
//!
//! ## Session dictionary (IDs 0x80..0xFE, 127 entries)
//!
//! Negotiated during handshake and updated via SCHEMA_PATCH frames.

use std::collections::HashMap;
use std::sync::OnceLock;

// ── Reserved IDs ────────────────────────────────────────────────────────────

/// Maximum static dictionary ID (exclusive).
pub const STATIC_MAX: u8 = 0x80;

/// Maximum session dictionary ID (exclusive).
pub const SESSION_MAX: u8 = 0xFF;

/// Sentinel: key is not in the dictionary, sent as raw text.
pub const ID_RAW: u8 = 0xFF;

/// Total number of usable dictionary entries (static + session).
pub const TOTAL_ENTRIES: usize = 255;

// ── Static dictionary ───────────────────────────────────────────────────────

/// The 128 static dictionary entries, indexed by ID.
///
/// These are the most common keys in MCP JSON-RPC communication,
/// packed into the lower half of the dictionary for zero-handshake availability.
pub static STATIC_DICT: [Option<&str>; STATIC_MAX as usize] = {
    let mut arr = [None; STATIC_MAX as usize];

    // Core MCP/RPC keys (0x00..0x0F)
    arr[0x00] = Some("tool");
    arr[0x01] = Some("arguments");
    arr[0x02] = Some("result");
    arr[0x03] = Some("error");
    arr[0x04] = Some("id");
    arr[0x05] = Some("name");
    arr[0x06] = Some("description");
    arr[0x07] = Some("content");
    arr[0x08] = Some("text");
    arr[0x09] = Some("type");
    arr[0x0A] = Some("method");
    arr[0x0B] = Some("params");
    arr[0x0C] = Some("jsonrpc");
    arr[0x0D] = Some("data");
    arr[0x0E] = Some("code");
    arr[0x0F] = Some("message");

    // Input/output (0x10..0x1F)
    arr[0x10] = Some("input");
    arr[0x11] = Some("output");
    arr[0x12] = Some("stream");
    arr[0x13] = Some("uri");
    arr[0x14] = Some("mimeType");
    arr[0x15] = Some("encoding");
    arr[0x16] = Some("language");
    arr[0x17] = Some("title");
    arr[0x18] = Some("value");
    arr[0x19] = Some("key");
    arr[0x1A] = Some("path");
    arr[0x1B] = Some("version");
    arr[0x1C] = Some("schema");
    arr[0x1D] = Some("default");
    arr[0x1E] = Some("required");
    arr[0x1F] = Some("properties");

    // Resources & tools (0x20..0x2F)
    arr[0x20] = Some("resources");
    arr[0x21] = Some("tools");
    arr[0x22] = Some("prompts");
    arr[0x23] = Some("resource");
    arr[0x24] = Some("prompt");
    arr[0x25] = Some("handler");
    arr[0x26] = Some("capabilities");
    arr[0x27] = Some("permissions");
    arr[0x28] = Some("scope");
    arr[0x29] = Some("tags");
    arr[0x2A] = Some("category");
    arr[0x2B] = Some("icon");
    arr[0x2C] = Some("metadata");
    arr[0x2D] = Some("timestamp");
    arr[0x2E] = Some("status");
    arr[0x2F] = Some("progress");

    // Errors & status (0x30..0x3F)
    arr[0x30] = Some("severity");
    arr[0x31] = Some("details");
    arr[0x32] = Some("cause");
    arr[0x33] = Some("stack");
    arr[0x34] = Some("line");
    arr[0x35] = Some("column");
    arr[0x36] = Some("source");
    arr[0x37] = Some("retry");
    arr[0x38] = Some("timeout");
    arr[0x39] = Some("limit");
    arr[0x3A] = Some("offset");
    arr[0x3B] = Some("count");
    arr[0x3C] = Some("total");
    arr[0x3D] = Some("page");
    arr[0x3E] = Some("cursor");
    arr[0x3F] = Some("next");

    // Remaining 64 entries (0x40..0x7F) reserved for future spec additions
    // Examples:
    arr[0x40] = Some("model");
    arr[0x41] = Some("provider");
    arr[0x42] = Some("temperature");
    arr[0x43] = Some("max_tokens");
    arr[0x44] = Some("stop");
    arr[0x45] = Some("frequency_penalty");
    arr[0x46] = Some("presence_penalty");
    arr[0x47] = Some("top_p");
    arr[0x48] = Some("logprobs");
    arr[0x49] = Some("user");
    arr[0x4A] = Some("system");
    arr[0x4B] = Some("assistant");
    arr[0x4C] = Some("function");
    arr[0x4D] = Some("tool_calls");
    arr[0x4E] = Some("finish_reason");
    arr[0x4F] = Some("usage");

    arr
};

// ── Lookup ──────────────────────────────────────────────────────────────────

/// Resolves a dictionary ID to its string key.
///
/// Returns `None` for IDs that are not assigned.
/// ID 0xFF (`ID_RAW`) always returns `None` (meaning "inline text").
pub fn resolve(id: u8) -> Option<&'static str> {
    if id < STATIC_MAX {
        STATIC_DICT[id as usize]
    } else {
        // Session dictionary not yet implemented
        None
    }
}

/// O(n) reverse lookup: finds the static dictionary ID for a key string.
///
/// Prefer [`lookup_fast`] for hot paths — it uses a lazily-built
/// `HashMap` for O(1) lookup.
pub fn lookup(key: &str) -> Option<u8> {
    STATIC_DICT
        .iter()
        .enumerate()
        .find_map(|(id, entry)| entry.filter(|e| *e == key).map(|_| id as u8))
}

// ── Fast O(1) lookup ────────────────────────────────────────────────────────

/// Lazily-initialized reverse map: `key → id`, built once at first use.
static REVERSE_MAP: OnceLock<HashMap<&'static str, u8>> = OnceLock::new();

fn get_reverse_map() -> &'static HashMap<&'static str, u8> {
    REVERSE_MAP.get_or_init(|| {
        let mut map = HashMap::with_capacity(STATIC_MAX as usize);
        for (id, entry) in STATIC_DICT.iter().enumerate() {
            if let Some(key) = entry {
                map.insert(*key, id as u8);
            }
        }
        map
    })
}

/// O(1) reverse lookup via lazily-built `HashMap`.
///
/// Always prefer this over [`lookup`] in hot paths (serialization,
/// compression).  The map is built once on first call and reused forever.
#[inline]
pub fn lookup_fast(key: &str) -> Option<u8> {
    get_reverse_map().get(key).copied()
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn known_keys_resolve() {
        assert_eq!(resolve(0x00), Some("tool"));
        assert_eq!(resolve(0x01), Some("arguments"));
        assert_eq!(resolve(0x06), Some("description"));
        assert_eq!(resolve(0x20), Some("resources"));
        assert_eq!(resolve(0x4F), Some("usage"));
    }

    #[test]
    fn unknown_ids_return_none() {
        // Unassigned static slot
        assert_eq!(resolve(0x50), None);
        // Session range (not yet populated)
        assert_eq!(resolve(0x80), None);
        // Raw sentinel
        assert_eq!(resolve(ID_RAW), None);
    }

    #[test]
    fn reverse_lookup() {
        assert_eq!(lookup("tool"), Some(0x00));
        assert_eq!(lookup("arguments"), Some(0x01));
        assert_eq!(lookup("finish_reason"), Some(0x4E));
        assert_eq!(lookup("nonexistent"), None);
    }

    #[test]
    fn id_raw_is_ff() {
        assert_eq!(ID_RAW, 0xFF);
    }

    #[test]
    fn static_dict_no_overlaps() {
        // Verify no duplicate keys in static dict
        for i in 0..STATIC_MAX as usize {
            if let Some(key) = STATIC_DICT[i] {
                for j in (i + 1)..STATIC_MAX as usize {
                    if let Some(other) = STATIC_DICT[j] {
                        assert_ne!(key, other, "duplicate key '{}' at {} and {}", key, i, j);
                    }
                }
            }
        }
    }

    #[test]
    fn fast_lookup_matches_linear() {
        for id in 0..STATIC_MAX {
            if let Some(key) = resolve(id) {
                assert_eq!(lookup_fast(key), Some(id), "mismatch for key '{key}' id {id}");
            }
        }
    }

    #[test]
    fn fast_lookup_unknown() {
        assert_eq!(lookup_fast("nonexistent_key_xyz"), None);
    }

    #[test]
    fn fast_lookup_idempotent() {
        // Calling twice hits the same cached map
        assert_eq!(lookup_fast("tool"), Some(0x00));
        assert_eq!(lookup_fast("tool"), Some(0x00));
        assert_eq!(lookup_fast("usage"), Some(0x4F));
    }
}
