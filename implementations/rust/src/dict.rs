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
//! Each transport/connection owns its own `SessionDict` instance.
//! Negotiated during handshake and updated via SCHEMA_PATCH frames.
//!
//! ## LRU adaptive eviction
//!
//! Each session slot tracks an access counter + generation timestamp
//! via lock-free `AtomicU64`.  When all 127 slots are full and a new
//! key needs registration, the slot with the lowest `(access_count,
//! last_generation)` is evicted automatically.  This keeps hot keys
//! (like `"temperature"` during an LLM call burst) in the dictionary
//! while cold keys (used once during setup) age out naturally.

use std::collections::HashMap;
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::OnceLock;
use std::sync::RwLock;

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

    // LLM / AI (0x40..0x4F)
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

    // HTTP / Web (0x50..0x5F)
    arr[0x50] = Some("url");
    arr[0x51] = Some("http_method");
    arr[0x52] = Some("headers");
    arr[0x53] = Some("body");
    arr[0x54] = Some("query");
    arr[0x55] = Some("http_status");
    arr[0x56] = Some("cookie");
    arr[0x57] = Some("session");
    arr[0x58] = Some("token");
    arr[0x59] = Some("auth");
    arr[0x5A] = Some("redirect");
    arr[0x5B] = Some("host");
    arr[0x5C] = Some("port");
    arr[0x5D] = Some("origin");
    arr[0x5E] = Some("referrer");
    arr[0x5F] = Some("agent");

    // File System (0x60..0x6F)
    arr[0x60] = Some("filename");
    arr[0x61] = Some("directory");
    arr[0x62] = Some("extension");
    arr[0x63] = Some("size");
    arr[0x64] = Some("modified");
    arr[0x65] = Some("created");
    arr[0x66] = Some("accessed");
    arr[0x67] = Some("mode");
    arr[0x68] = Some("owner");
    arr[0x69] = Some("group");
    arr[0x6A] = Some("symlink");
    arr[0x6B] = Some("binary");
    arr[0x6C] = Some("base64");
    arr[0x6D] = Some("hash");
    arr[0x6E] = Some("algorithm");
    arr[0x6F] = Some("chunk");

    // Operations (0x70..0x7F)
    arr[0x70] = Some("execute");
    arr[0x71] = Some("read");
    arr[0x72] = Some("write");
    arr[0x73] = Some("delete");
    arr[0x74] = Some("update");
    arr[0x75] = Some("create");
    arr[0x76] = Some("search");
    arr[0x77] = Some("list");
    arr[0x78] = Some("get");
    arr[0x79] = Some("set");
    arr[0x7A] = Some("watch");
    arr[0x7B] = Some("subscribe");
    arr[0x7C] = Some("notify");
    arr[0x7D] = Some("cancel");
    arr[0x7E] = Some("pause");
    arr[0x7F] = Some("resume");

    arr
};

// ── Lookup ──────────────────────────────────────────────────────────────────

/// Resolves a dictionary ID to its string key.
///
/// Returns `None` for IDs that are not assigned.
/// ID 0xFF (`ID_RAW`) always returns `None` (meaning "inline text").
/// For session-range IDs (0x80..0xFE), returns [`None`] because
/// session keys are owned and not `&'static str`.  Use
/// [`resolve_any`] with a [`SessionDict`] to resolve session-range IDs.
pub fn resolve(id: u8) -> Option<&'static str> {
    if id < STATIC_MAX {
        STATIC_DICT[id as usize]
    } else {
        // Session dictionary has owned Strings, not &'static str.
        None
    }
}

/// Resolves a dictionary ID to a string, checking both static and session dicts.
///
/// Returns owned `String` for session-range IDs.  Prefer this over
/// [`resolve`] in decode paths where the key may be in the session dict.
/// Pass `None` for `session` if no session dictionary is available
/// (session-range IDs will return `None` in that case).
pub fn resolve_any(id: u8, session: Option<&SessionDict>) -> Option<String> {
    if id < STATIC_MAX {
        STATIC_DICT[id as usize].map(|s| s.to_owned())
    } else if id < SESSION_MAX {
        session.and_then(|s| s.resolve(id).map(|s| s.to_owned()))
    } else {
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

/// Returns a lazily-initialized reverse map for the static dictionary.
fn get_reverse_map() -> &'static HashMap<&'static str, u8> {
    static MAP: OnceLock<HashMap<&'static str, u8>> = OnceLock::new();
    MAP.get_or_init(|| {
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
/// compression). Checks the static dictionary first, then the
/// optional session dictionary if provided.
///
/// Pass `None` for `session` if no session dictionary is available.
#[inline]
pub fn lookup_fast(key: &str, session: Option<&SessionDict>) -> Option<u8> {
    // Try static dict first (hot path, always available)
    if let Some(id) = get_reverse_map().get(key).copied() {
        return Some(id);
    }
    // Then try session dict if provided
    session.and_then(|s| s.lookup(key))
}

// ── Session dictionary (0x80..0xFE, 127 dynamic slots) ─────────────────────

/// A thread-safe session dictionary holding 127 dynamic key→ID mappings.
///
/// Each transport/connection should own its own `SessionDict` instance.
/// Slots are in range `0x80..=0xFE`.  Keys are owned `String`s so the
/// dictionary can outlive the strings passed to `register()`.
///
/// Each slot carries lock-free LRU metadata (`access_count` and
/// `last_generation`) so the hot read path never needs a write lock.
///
/// ## Cloning
///
/// Cloning creates a fresh dictionary with the same key→ID mappings
/// but reset LRU metadata (counters and generation start at zero).
pub struct SessionDict {
    /// Forward map: ID → key (index = id - 0x80)
    forward: [Option<String>; 127],
    /// Reverse map: key → ID
    reverse: HashMap<String, u8>,
    /// Per-slot access counters (lock-free, atomically incremented on touch).
    lru_count: [AtomicU64; 127],
    /// Per-slot last-generation stamps (lock-free, set on touch).
    lru_gen: [AtomicU64; 127],
    /// Monotonically-increasing LRU generation counter (per-instance).
    lru_generation: AtomicU64,
}

impl Clone for SessionDict {
    fn clone(&self) -> Self {
        // Clone the key mappings but start with fresh LRU metadata.
        // We need to read the forward array and reverse map.
        // Since we're taking &self (not &mut), and the forward/reverse
        // are only mutated under write locks, this is safe.
        Self {
            forward: self.forward.clone(),
            reverse: self.reverse.clone(),
            lru_count: std::array::from_fn(|_| AtomicU64::new(0)),
            lru_gen: std::array::from_fn(|_| AtomicU64::new(0)),
            lru_generation: AtomicU64::new(0),
        }
    }
}

impl SessionDict {
    /// Create an empty session dictionary.
    pub fn new() -> Self {
        Self {
            forward: std::array::from_fn(|_| None),
            reverse: HashMap::with_capacity(16),
            lru_count: std::array::from_fn(|_| AtomicU64::new(0)),
            lru_gen: std::array::from_fn(|_| AtomicU64::new(0)),
            lru_generation: AtomicU64::new(0),
        }
    }

    /// Bump the instance LRU generation and return the new value.
    #[inline]
    fn next_lru_gen(&self) -> u64 {
        self.lru_generation.fetch_add(1, Ordering::Relaxed)
    }

    /// Touch a slot: increment its access counter and update its generation.
    ///
    /// Lock-free — safe to call from any thread, including inside a
    /// read-lock on the outer `RwLock<SessionDict>`.
    #[inline]
    pub fn touch(&self, id: u8) {
        if id < STATIC_MAX || id >= SESSION_MAX {
            return;
        }
        let idx = (id - STATIC_MAX) as usize;
        self.lru_count[idx].fetch_add(1, Ordering::Relaxed);
        self.lru_gen[idx].store(self.next_lru_gen(), Ordering::Relaxed);
    }

    /// Find the ID of the least-recently-used slot (lowest `last_gen`,
    /// tie-broken by lowest `access_count`).
    ///
    /// Returns `None` if all slots are empty (no eviction needed).
    /// This is called under write lock — the scan is O(127).
    pub fn find_lru(&self) -> Option<u8> {
        let mut best_idx: Option<usize> = None;
        let mut best_gen = u64::MAX;
        let mut best_count = u64::MAX;

        for i in 0..127 {
            if self.forward[i].is_none() {
                continue;
            }
            let gen = self.lru_gen[i].load(Ordering::Relaxed);
            let cnt = self.lru_count[i].load(Ordering::Relaxed);
            if gen < best_gen || (gen == best_gen && cnt < best_count) {
                best_gen = gen;
                best_count = cnt;
                best_idx = Some(i);
            }
        }
        best_idx.map(|i| (i as u8) + STATIC_MAX)
    }

    /// Evict the least-recently-used slot, making room for a new key.
    ///
    /// Returns the ID that was freed, or `None` if there was an empty slot
    /// already (no eviction needed) or if somehow `find_lru` found nothing.
    pub fn evict_lru(&mut self) -> Option<u8> {
        // If there's an empty slot, no need to evict
        if let Some(idx) = self.forward.iter().position(|s| s.is_none()) {
            return Some((idx as u8) + STATIC_MAX);
        }
        let id = self.find_lru()?;
        self.unregister(id);
        Some(id)
    }

    /// Register a key, auto-evicting the LRU slot if all 127 are full.
    ///
    /// - `key`: the string key to register (owned).
    ///
    /// Returns the ID assigned (always in `0x80..=0xFE`).
    /// Panics only if the dictionary is in an inconsistent state.
    pub fn register_lru(&mut self, key: impl Into<String>) -> u8 {
        let key_str = key.into();

        // Check if already registered — just touch and return
        if let Some(&id) = self.reverse.get(&key_str) {
            self.touch(id);
            return id;
        }

        let id = self.evict_lru().expect("SessionDict should always have 127 slots");
        let _ = self.register(key_str, id);
        id
    }

    /// Register a key at a session dictionary slot.
    ///
    /// - `key`: the string key to register (owned, can be any `impl Into<String>`).
    /// - `id`: session slot ID, must be in `0x80..=0xFE`.
    ///
    /// Returns `Ok(())` on success, or `Err(msg)` if the ID is out of range.
    pub fn register(&mut self, key: impl Into<String>, id: u8) -> Result<(), String> {
        if id < STATIC_MAX || id >= SESSION_MAX {
            return Err(format!(
                "session ID {id:#04x} out of range ({:#04x}..{:#04x})",
                STATIC_MAX, SESSION_MAX
            ));
        }
        let idx = (id - STATIC_MAX) as usize;
        let key_str = key.into();

        // Remove old reverse entry if overwriting
        if let Some(ref old_key) = self.forward[idx] {
            self.reverse.remove(old_key);
        }

        self.reverse.insert(key_str.clone(), id);
        self.forward[idx] = Some(key_str);

        // Reset LRU metadata for the new occupant
        self.lru_count[idx].store(0, Ordering::Relaxed);
        self.lru_gen[idx].store(self.next_lru_gen(), Ordering::Relaxed);

        Ok(())
    }

    /// Remove a slot from the session dictionary.
    pub fn unregister(&mut self, id: u8) {
        if id < STATIC_MAX || id >= SESSION_MAX {
            return;
        }
        let idx = (id - STATIC_MAX) as usize;
        if let Some(ref key) = self.forward[idx] {
            self.reverse.remove(key);
            self.forward[idx] = None;
            // Reset LRU metadata
            self.lru_count[idx].store(0, Ordering::Relaxed);
            self.lru_gen[idx].store(0, Ordering::Relaxed);
        }
    }

    /// Resolve a session dictionary ID to its key string.
    pub fn resolve(&self, id: u8) -> Option<&str> {
        if id < STATIC_MAX || id >= SESSION_MAX {
            return None;
        }
        self.forward[(id - STATIC_MAX) as usize].as_deref()
    }

    /// Look up a key in the session dictionary, returning its ID.
    /// Touches the slot if found (updates LRU metadata).
    pub fn lookup(&self, key: &str) -> Option<u8> {
        let id = self.reverse.get(key).copied()?;
        self.touch(id);
        Some(id)
    }

    /// Initialize the session dictionary with pre-registered keys.
    ///
    /// Clears existing entries, then registers each `(id, key)` pair.
    pub fn init(&mut self, entries: impl IntoIterator<Item = (u8, String)>) {
        self.clear();
        for (id, key) in entries {
            let _ = self.register(key, id);
        }
    }

    /// Remove all entries.
    pub fn clear(&mut self) {
        self.forward.fill(None);
        self.reverse.clear();
        for i in 0..127 {
            self.lru_count[i].store(0, Ordering::Relaxed);
            self.lru_gen[i].store(0, Ordering::Relaxed);
        }
        // Reset generation counter so fresh entries start at 0
        self.lru_generation.store(0, Ordering::Relaxed);
    }

    /// Number of registered entries.
    pub fn len(&self) -> usize {
        self.reverse.len()
    }

    /// Whether the dictionary is empty.
    pub fn is_empty(&self) -> bool {
        self.reverse.is_empty()
    }
}

impl Default for SessionDict {
    fn default() -> Self {
        Self::new()
    }
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
        // Session range without a session dict returns None
        assert_eq!(resolve_any(0x80, None), None);
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
                assert_eq!(lookup_fast(key, None), Some(id), "mismatch for key '{key}' id {id}");
            }
        }
    }

    #[test]
    fn fast_lookup_unknown() {
        assert_eq!(lookup_fast("nonexistent_key_xyz", None), None);
    }

    #[test]
    fn fast_lookup_idempotent() {
        assert_eq!(lookup_fast("tool", None), Some(0x00));
        assert_eq!(lookup_fast("tool", None), Some(0x00));
        assert_eq!(lookup_fast("usage", None), Some(0x4F));
    }

    #[test]
    fn fast_lookup_with_session() {
        let mut session = SessionDict::new();
        session.register("custom_key", 0x80).unwrap();
        // Should find in session dict
        assert_eq!(lookup_fast("custom_key", Some(&session)), Some(0x80));
        // Static still works
        assert_eq!(lookup_fast("tool", Some(&session)), Some(0x00));
    }

    #[test]
    fn resolve_any_with_session() {
        let mut session = SessionDict::new();
        session.register("session_key", 0x80).unwrap();
        // Static range
        assert_eq!(resolve_any(0x00, Some(&session)), Some("tool".to_string()));
        // Session range
        assert_eq!(resolve_any(0x80, Some(&session)), Some("session_key".to_string()));
        // Session range without session
        assert_eq!(resolve_any(0x80, None), None);
    }

    // ── LRU session dictionary tests ─────────────────────────────────────

    fn new_session() -> SessionDict {
        SessionDict::new()
    }

    #[test]
    fn lru_register_and_lookup() {
        let mut s = new_session();
        s.register("custom_key_1", 0x80).unwrap();
        let id = s.lookup("custom_key_1");
        assert_eq!(id, Some(0x80));
    }

    #[test]
    fn lru_touch_updates_generation() {
        let mut s = new_session();
        s.register("hot_key", 0x80).unwrap();

        // Read the gen after registration
        let gen_after_reg = s.lru_gen[0].load(Ordering::Relaxed);

        // Touch it
        s.lookup("hot_key");

        let gen_after_touch = s.lru_gen[0].load(Ordering::Relaxed);
        assert!(gen_after_touch > gen_after_reg, "touch should bump generation");
    }

    #[test]
    fn lru_touch_increments_count() {
        let mut s = new_session();
        s.register("popular", 0x81).unwrap();
        let idx = (0x81 - STATIC_MAX) as usize;

        for i in 1..=5 {
            s.lookup("popular");
            let cnt = s.lru_count[idx].load(Ordering::Relaxed);
            assert_eq!(cnt, i, "count should be {i} after {i} lookups");
        }
    }

    #[test]
    fn lru_evict_least_recent() {
        let mut s = new_session();

        // Fill all 127 slots
        for i in 0..127u8 {
            let id = 0x80 + i;
            s.register(&format!("key_{id:02x}"), id).unwrap();
            // Touch each one so they have different generations
            s.lookup(&format!("key_{id:02x}"));
        }
        assert_eq!(s.len(), 127);

        // key_80 was touched first, so it should be LRU
        let lru_id = s.find_lru();
        assert_eq!(lru_id, Some(0x80), "first registered should be LRU");

        // Evict and check
        let evicted = s.evict_lru();
        assert_eq!(evicted, Some(0x80));
        assert_eq!(s.len(), 126);
        assert!(s.resolve(0x80).is_none());
    }

    #[test]
    fn lru_register_lru_auto_evict() {
        let mut s = new_session();

        // Fill all 127 slots
        for i in 0..127u8 {
            let id = 0x80 + i;
            s.register(&format!("key_{id:02x}"), id).unwrap();
            s.lookup(&format!("key_{id:02x}"));
        }
        assert_eq!(s.len(), 127);

        // Now auto-register a new key — should evict the LRU (0x80)
        let new_id = s.register_lru("brand_new_key");
        assert!(new_id >= 0x80 && new_id < 0xFF);
        assert_eq!(s.len(), 127); // still full

        // The new key should resolve
        assert_eq!(s.resolve(new_id), Some("brand_new_key"));
        // The old LRU should be gone
        assert!(s.lookup("key_80").is_none());
    }

    #[test]
    fn lru_register_lru_duplicate_noop() {
        let mut s = new_session();
        s.register("only_key", 0x80).unwrap();
        assert_eq!(s.len(), 1);

        // Re-registering the same key should return the same ID
        let id = s.register_lru("only_key");
        assert_eq!(id, 0x80);
        assert_eq!(s.len(), 1);
    }

    #[test]
    fn lru_touch_out_of_range_noops() {
        let s = new_session();
        // These should not panic
        s.touch(0x00); // static range
        s.touch(0xFF); // ID_RAW
        s.touch(0x7F); // last static
    }

    #[test]
    fn lru_evict_empty_dict() {
        let mut s = new_session();
        let evicted = s.evict_lru();
        // With an empty dict, there's an empty slot, so evict_lru returns it directly
        assert!(evicted.is_some());
        assert_eq!(s.len(), 0);
    }

    #[test]
    fn lru_find_lru_empty_dict() {
        let s = new_session();
        let lru = s.find_lru();
        assert_eq!(lru, None); // no occupied slots
    }

    #[test]
    fn lru_clear_resets_counters() {
        let mut s = new_session();
        s.register("temp", 0x85).unwrap();
        s.lookup("temp");
        s.lookup("temp");

        let idx = (0x85 - STATIC_MAX) as usize;
        assert!(s.lru_count[idx].load(Ordering::Relaxed) > 0);

        s.clear();
        assert_eq!(s.lru_count[idx].load(Ordering::Relaxed), 0);
        assert_eq!(s.len(), 0);
    }

    #[test]
    fn lru_register_overwrite_resets_lru() {
        let mut s = new_session();
        s.register("alpha", 0x80).unwrap();
        s.lookup("alpha");
        s.lookup("alpha");
        assert_eq!(s.lru_count[0].load(Ordering::Relaxed), 2);

        // Overwrite with a new key at the same slot
        s.register("beta", 0x80).unwrap();
        assert_eq!(s.lru_count[0].load(Ordering::Relaxed), 0);
        assert_eq!(s.resolve(0x80), Some("beta"));
    }

    #[test]
    fn session_dict_clone() {
        let mut original = SessionDict::new();
        original.register("key_a", 0x80).unwrap();
        original.register("key_b", 0x81).unwrap();
        original.lookup("key_a"); // bump LRU for key_a

        let cloned = original.clone();
        // Same mappings
        assert_eq!(cloned.resolve(0x80), Some("key_a"));
        assert_eq!(cloned.resolve(0x81), Some("key_b"));
        assert_eq!(cloned.len(), 2);

        // But fresh LRU metadata
        assert_eq!(cloned.lru_count[0].load(Ordering::Relaxed), 0);
        assert_eq!(cloned.lru_count[1].load(Ordering::Relaxed), 0);
        // Original LRU untouched
        assert!(original.lru_count[0].load(Ordering::Relaxed) > 0);
    }

    #[test]
    fn session_dict_init() {
        let mut s = SessionDict::new();
        s.init(vec![(0x80, "hello".into()), (0x81, "world".into())]);
        assert_eq!(s.len(), 2);
        assert_eq!(s.resolve(0x80), Some("hello"));
        assert_eq!(s.resolve(0x81), Some("world"));
    }
}
