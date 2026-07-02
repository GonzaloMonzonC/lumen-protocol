//! Macaroons — capability-based authorization tokens with attenuable caveats.
//!
//! Macaroons are bearer tokens that can be restricted (attenuated) by any
//! party in the chain without coordinating with the token issuer.  They use
//! HMAC-SHA256 for chained signatures.
//!
//! ## Wire format (little-endian)
//!
//! ```text
//! [version: u8][id_len: u8][id: UTF-8]
//! [location_len: u8][location: UTF-8]
//! [caveat_count: u8][caveats...]
//! [signature: 32 bytes]
//! ```
//! Each caveat:
//! ```text
//! [caveat_len: u8][caveat: UTF-8]
//! ```
//!
//! ## Key operations
//!
//! ```text
//! Issuer:
//!   root_key = random 32 bytes
//!   m = Macaroon::create(root_key, "lumen-mcp", "server-a")
//!   m = m.attenuate("method = tools/list")
//!   send(m) → client
//!
//! Verifier:
//!   m = Macaroon::decode(received_bytes)
//!   ok = m.verify(root_key, |caveat| check_caveat(caveat))
//! ```

use sha2::Sha256;

// ── Constants ───────────────────────────────────────────────────────────────

/// Macaroon protocol version.
pub const MACAROON_V1: u8 = 1;
/// HMAC-SHA256 signature size in bytes.
pub const SIGNATURE_SIZE: usize = 32;
/// Maximum caveat length in bytes.
pub const MAX_CAVEAT_LEN: usize = 255;
/// Maximum number of caveats per macaroon.
pub const MAX_CAVEATS: usize = 32;

// ── Macaroon ────────────────────────────────────────────────────────────────

/// A LUMEN capability token with attenuable caveats.
///
/// Each caveat is a predicate string that must be satisfied for the
/// macaroon to be valid.  Caveats are added via [`Macaroon::attenuate`],
/// which derives a new signature chaining the caveat into the HMAC.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Macaroon {
    /// Protocol version (currently `MACAROON_V1`).
    pub version: u8,
    /// Opaque identifier (typically a random nonce or key hint).
    pub id: String,
    /// Hint for where to find the root key (e.g., "lumen-mcp").
    pub location: String,
    /// Ordered list of caveats (predicates that must be satisfied).
    pub caveats: Vec<String>,
    /// HMAC-SHA256 signature chaining all caveats.
    pub signature: [u8; SIGNATURE_SIZE],
}

impl Macaroon {
    /// Create a new macaroon with a root key.
    ///
    /// The root key is used to derive the initial signature.  The caller
    /// MUST store the root key securely; it is needed for verification.
    pub fn create(root_key: &[u8; 32], id: &str, location: &str) -> Self {
        let mut mac = Self {
            version: MACAROON_V1,
            id: id.to_string(),
            location: location.to_string(),
            caveats: Vec::new(),
            signature: [0u8; SIGNATURE_SIZE],
        };
        // Initial signature = HMAC-SHA256(root_key, id)
        mac.signature = hmac_sha256(root_key, mac.id.as_bytes());
        mac
    }

    /// Add a caveat, deriving a new signature.
    ///
    /// This operation does NOT require the root key — anyone holding the
    /// macaroon can attenuate it further.  Each attenuation narrows the
    /// set of operations the macaroon authorizes.
    pub fn attenuate(&self, caveat: &str) -> Self {
        let signature = hmac_sha256(&self.signature, caveat.as_bytes());
        let mut caveats = self.caveats.clone();
        caveats.push(caveat.to_string());
        Self {
            version: self.version,
            id: self.id.clone(),
            location: self.location.clone(),
            caveats,
            signature,
        }
    }

    /// Verify the macaroon against a root key and a set of caveat checkers,
    /// validating expiry caveats against the current system time.
    ///
    /// The `check_caveat` closure is called for each non-expiry caveat.
    /// Expiry caveats (`expiry < ISO8601`) are checked automatically against
    /// the current wall-clock time and do NOT reach the closure.
    pub fn verify_with_time<F>(&self, root_key: &[u8; 32], now: u64, mut check_caveat: F) -> bool
    where
        F: FnMut(&str) -> bool,
    {
        for caveat in &self.caveats {
            // Auto-check expiry caveats against provided timestamp
            if let Some(expiry_str) = caveats::parse_expiry(caveat) {
                // Parse ISO 8601 timestamp and compare
                if let Some(expiry_ts) = parse_iso8601_to_unix(expiry_str) {
                    if now >= expiry_ts {
                        return false; // expired
                    }
                    continue; // expiry validated, skip user check
                }
                // If expiry can't be parsed, reject for safety
                return false;
            }
            if !check_caveat(caveat) {
                return false;
            }
        }
        // Recompute signature chain (same as verify)
        let mut sig = hmac_sha256(root_key, self.id.as_bytes());
        for caveat in &self.caveats {
            sig = hmac_sha256(&sig, caveat.as_bytes());
        }
        constant_time_eq(&sig, &self.signature)
    }

    /// Verify the macaroon with automatic expiry checking against current time.
    /// Equivalent to `verify_with_time(root_key, SystemTime::now(), check_caveat)`.
    pub fn verify<F>(&self, root_key: &[u8; 32], check_caveat: F) -> bool
    where
        F: FnMut(&str) -> bool,
    {
        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap_or_default()
            .as_secs();
        self.verify_with_time(root_key, now, check_caveat)
    }

    // ── Serialisation ──────────────────────────────────────────────────

    /// Encode the macaroon to binary for wire transport.
    pub fn encode(&self) -> Vec<u8> {
        let id_bytes = self.id.as_bytes();
        let loc_bytes = self.location.as_bytes();
        let cap = 1
            + 1
            + id_bytes.len()
            + 1
            + loc_bytes.len()
            + 1
            + self.caveats.iter().map(|c| 1 + c.len()).sum::<usize>()
            + SIGNATURE_SIZE;

        let mut buf = Vec::with_capacity(cap);
        buf.push(self.version);
        buf.push(id_bytes.len().min(255) as u8);
        buf.extend_from_slice(&id_bytes[..id_bytes.len().min(255)]);
        buf.push(loc_bytes.len().min(255) as u8);
        buf.extend_from_slice(&loc_bytes[..loc_bytes.len().min(255)]);

        let count = self.caveats.len().min(MAX_CAVEATS) as u8;
        buf.push(count);
        for caveat in self.caveats.iter().take(MAX_CAVEATS) {
            let c_bytes = caveat.as_bytes();
            buf.push(c_bytes.len().min(MAX_CAVEAT_LEN) as u8);
            buf.extend_from_slice(&c_bytes[..c_bytes.len().min(MAX_CAVEAT_LEN)]);
        }

        buf.extend_from_slice(&self.signature);
        buf
    }

    /// Minimum encoded size: version + id_len(0) + loc_len(0) + count(0) + sig = 35.
    pub const MIN_ENCODED_LEN: usize = 1 + 1 + 1 + 1 + SIGNATURE_SIZE;

    /// Decode a macaroon from binary. Returns `None` on malformed input
    /// or unknown version.
    pub fn decode(data: &[u8]) -> Option<Self> {
        if data.len() < Self::MIN_ENCODED_LEN {
            return None;
        }

        let version = data[0];
        // Reject unknown versions — enables safe protocol migration in the future.
        // Currently only MACAROON_V1 (1) is accepted.
        if version != MACAROON_V1 {
            return None;
        }
        let id_len = data[1] as usize;
        if data.len() < 2 + id_len {
            return None;
        }
        let id = String::from_utf8(data[2..2 + id_len].to_vec()).ok()?;

        let pos = 2 + id_len;
        if data.len() < pos + 1 {
            return None;
        }
        let loc_len = data[pos] as usize;
        if data.len() < pos + 1 + loc_len {
            return None;
        }
        let location = String::from_utf8(data[pos + 1..pos + 1 + loc_len].to_vec()).ok()?;

        let pos = pos + 1 + loc_len;
        if data.len() < pos + 1 {
            return None;
        }
        let caveat_count = data[pos] as usize;
        let mut pos = pos + 1;
        let mut caveats = Vec::with_capacity(caveat_count.min(MAX_CAVEATS));

        for _ in 0..caveat_count {
            if data.len() < pos + 1 {
                return None;
            }
            let c_len = data[pos] as usize;
            pos += 1;
            if data.len() < pos + c_len {
                return None;
            }
            let caveat = String::from_utf8(data[pos..pos + c_len].to_vec()).ok()?;
            caveats.push(caveat);
            pos += c_len;
        }

        if data.len() < pos + SIGNATURE_SIZE {
            return None;
        }
        let mut signature = [0u8; SIGNATURE_SIZE];
        signature.copy_from_slice(&data[pos..pos + SIGNATURE_SIZE]);

        Some(Self {
            version,
            id,
            location,
            caveats,
            signature,
        })
    }

    /// Size of the encoded payload in bytes.
    pub fn encoded_len(&self) -> usize {
        Self::MIN_ENCODED_LEN
            + self.id.len().min(255)
            + self.location.len().min(255)
            + self
                .caveats
                .iter()
                .map(|c| 1 + c.len().min(MAX_CAVEAT_LEN))
                .sum::<usize>()
    }
}

// ── Crypto helpers ──────────────────────────────────────────────────────────

/// HMAC-SHA256 (RFC 2104) via the `hmac` crate — verified against the
/// RFC 4231 test vectors in this module's tests.
fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; SIGNATURE_SIZE] {
    use hmac::{Hmac, Mac};
    let mut mac =
        <Hmac<Sha256> as Mac>::new_from_slice(key).expect("HMAC-SHA256 accepts keys of any length");
    mac.update(message);
    mac.finalize().into_bytes().into()
}

/// Constant-time comparison of two 32-byte slices.
fn constant_time_eq(a: &[u8; 32], b: &[u8; 32]) -> bool {
    let mut diff = 0u8;
    for i in 0..32 {
        diff |= a[i] ^ b[i];
    }
    diff == 0
}

/// Parse a simplified ISO 8601 timestamp (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)
/// to a Unix timestamp. Returns None if parsing fails.
fn parse_iso8601_to_unix(s: &str) -> Option<u64> {
    let s = s.trim();
    // Support both "2026-12-31" and "2026-12-31T23:59:59Z"
    if s.len() < 10 {
        return None;
    }
    let year: u32 = s[0..4].parse().ok()?;
    let month: u32 = s[5..7].parse().ok()?;
    let day: u32 = s[8..10].parse().ok()?;
    if !(1..=12).contains(&month) || !(1..=31).contains(&day) {
        return None;
    }
    // Simplified: use day-of-year approximation (good enough for expiry checks)
    let days_in_month = [0, 31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    let is_leap = |y: u32| y.is_multiple_of(4) && (!y.is_multiple_of(100) || y.is_multiple_of(400));
    let feb_days = if is_leap(year) { 29 } else { 28 };
    if month == 2 && day > feb_days {
        return None;
    }
    if day > days_in_month[month as usize] {
        return None;
    }
    // Days since epoch (1970-01-01)
    let mut days = 0u64;
    for y in 1970..year {
        days += if is_leap(y) { 366 } else { 365 };
    }
    let cumulative = [0, 0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    let mut cum = cumulative[month as usize];
    if month > 2 && is_leap(year) {
        cum += 1;
    }
    days += cum as u64 + day as u64 - 1;
    // Parse optional time part (HH:MM:SS)
    let seconds = if s.len() >= 19 && &s[10..11] == "T" {
        let h: u64 = s[11..13].parse().unwrap_or(0);
        let m: u64 = s[14..16].parse().unwrap_or(0);
        let sec: u64 = s[17..19].parse().unwrap_or(0);
        h * 3600 + m * 60 + sec
    } else {
        0
    };
    Some(days * 86400 + seconds)
}

// ── Key generation ──────────────────────────────────────────────────────────

/// Generate a random 32-byte root key using the OS CSPRNG.
pub fn generate_root_key() -> [u8; 32] {
    use rand::RngCore;
    let mut key = [0u8; 32];
    rand::rngs::OsRng.fill_bytes(&mut key);
    key
}

// ── Caveat helpers ──────────────────────────────────────────────────────────

/// Common caveat formats for LUMEN MCP servers.
pub mod caveats {
    /// Restrict to a specific method.
    pub fn method(name: &str) -> String {
        format!("method = {name}")
    }

    /// Time-bounded access (ISO 8601 timestamp).
    pub fn expiry_before(timestamp: &str) -> String {
        format!("expiry < {timestamp}")
    }

    /// Restrict to a specific tool.
    pub fn tool(name: &str) -> String {
        format!("tool = {name}")
    }

    /// Restrict to read-only operations.
    pub fn read_only() -> String {
        "op = read".to_string()
    }

    /// Parse a method restriction caveat.
    pub fn parse_method(caveat: &str) -> Option<&str> {
        caveat.strip_prefix("method = ")
    }

    /// Parse an expiry caveat.
    pub fn parse_expiry(caveat: &str) -> Option<&str> {
        caveat.strip_prefix("expiry < ")
    }

    /// Parse a tool restriction caveat.
    pub fn parse_tool(caveat: &str) -> Option<&str> {
        caveat.strip_prefix("tool = ")
    }

    /// Check if a caveat restricts to read-only.
    pub fn is_read_only(caveat: &str) -> bool {
        caveat == "op = read"
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn hmac_sha256_test_vector() {
        // RFC 4231 test case 1: key=20 bytes of 0x0b, data="Hi There"
        let key = [0x0Bu8; 20];
        let data = b"Hi There";
        let expected: [u8; 32] = [
            0xb0, 0x34, 0x4c, 0x61, 0xd8, 0xdb, 0x38, 0x53, 0x5c, 0xa8, 0xaf, 0xce, 0xaf, 0x0b,
            0xf1, 0x2b, 0x88, 0x1d, 0xc2, 0x00, 0xc9, 0x83, 0x3d, 0xa7, 0x26, 0xe9, 0x37, 0x6c,
            0x2e, 0x32, 0xcf, 0xf7,
        ];
        assert_eq!(hmac_sha256(&key, data), expected);

        // RFC 4231 test case 3: key 131 bytes of 0xAA
        let key3 = [0xAAu8; 131];
        let data3 = b"Test Using Larger Than Block-Size Key - Hash Key First";
        let expected3: [u8; 32] = [
            0x60, 0xe4, 0x31, 0x59, 0x1e, 0xe0, 0xb6, 0x7f, 0x0d, 0x8a, 0x26, 0xaa, 0xcb, 0xf5,
            0xb7, 0x7f, 0x8e, 0x0b, 0xc6, 0x21, 0x37, 0x28, 0xc5, 0x14, 0x05, 0x46, 0x04, 0x0f,
            0x0e, 0xe3, 0x7f, 0x54,
        ];
        assert_eq!(hmac_sha256(&key3, data3), expected3);
    }

    #[test]
    fn create_and_verify_no_caveats() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "session-1", "lumen-mcp");
        assert!(mac.caveats.is_empty());
        assert!(mac.verify(&root_key, |_| true));
    }

    #[test]
    fn wrong_root_key_fails() {
        let key1 = generate_root_key();
        let key2 = generate_root_key();
        let mac = Macaroon::create(&key1, "s1", "lumen");
        assert!(!mac.verify(&key2, |_| true));
    }

    #[test]
    fn attenuate_and_verify() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "s1", "lumen")
            .attenuate(&caveats::method("tools/list"))
            .attenuate(&caveats::read_only());

        assert_eq!(mac.caveats.len(), 2);

        // Verify with matching caveats
        let methods = ["tools/list", "tools/call"];
        assert!(mac.verify(&root_key, |c| {
            if let Some(m) = caveats::parse_method(c) {
                methods.contains(&m)
            } else {
                caveats::is_read_only(c)
            }
        }));

        // Fail with wrong method
        let methods2 = ["tools/call"];
        assert!(!mac.verify(&root_key, |c| {
            if let Some(m) = caveats::parse_method(c) {
                methods2.contains(&m)
            } else {
                caveats::is_read_only(c)
            }
        }));
    }

    #[test]
    fn tampered_caveat_fails() {
        let root_key = generate_root_key();
        let mut mac =
            Macaroon::create(&root_key, "s1", "lumen").attenuate(&caveats::method("tools/list"));

        // Tamper with a caveat
        mac.caveats[0] = caveats::method("tools/call");

        assert!(!mac.verify(&root_key, |c| {
            caveats::parse_method(c) == Some("tools/list")
        }));
    }

    #[test]
    fn encode_decode_roundtrip() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "session-42", "lumen-mcp")
            .attenuate(&caveats::method("tools/call"))
            .attenuate(&caveats::tool("search"))
            .attenuate(&caveats::expiry_before("2026-12-31T23:59:59Z"));

        let encoded = mac.encode();
        let decoded = Macaroon::decode(&encoded).unwrap();

        assert_eq!(decoded.version, mac.version);
        assert_eq!(decoded.id, mac.id);
        assert_eq!(decoded.location, mac.location);
        assert_eq!(decoded.caveats, mac.caveats);
        assert_eq!(decoded.signature, mac.signature);
        assert_eq!(decoded.encoded_len(), encoded.len());

        // Decoded macaroon should still verify
        assert!(decoded.verify(&root_key, |c| {
            caveats::parse_method(c).is_none_or(|m| m == "tools/call")
                && caveats::parse_tool(c).is_none_or(|t| t == "search")
                && caveats::parse_expiry(c).is_none_or(|_| true)
        }));
    }

    #[test]
    fn decode_too_short() {
        assert!(Macaroon::decode(&[]).is_none());
        assert!(Macaroon::decode(&[0u8; 34]).is_none()); // 34 < MIN_ENCODED_LEN (35)
    }

    #[test]
    fn decode_truncated_caveat() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "s", "l").attenuate(&caveats::method("tools/list"));

        let mut encoded = mac.encode();
        // Truncate in the middle of a caveat
        encoded.truncate(encoded.len() - 5);
        assert!(Macaroon::decode(&encoded).is_none());
    }

    #[test]
    fn constant_time_eq_works() {
        let a = [0xAAu8; 32];
        let b = [0xAAu8; 32];
        let c = [0xBBu8; 32];
        assert!(constant_time_eq(&a, &b));
        assert!(!constant_time_eq(&a, &c));

        // Differ in only last byte
        let mut d = a;
        d[31] ^= 1;
        assert!(!constant_time_eq(&a, &d));
    }

    #[test]
    fn caveat_helpers() {
        assert_eq!(caveats::method("tools/list"), "method = tools/list");
        assert_eq!(
            caveats::parse_method("method = tools/call"),
            Some("tools/call")
        );
        assert_eq!(caveats::parse_method("tool = x"), None);
        assert_eq!(
            caveats::parse_expiry("expiry < 2026-01-01"),
            Some("2026-01-01")
        );
        assert!(caveats::is_read_only("op = read"));
        assert!(!caveats::is_read_only("op = write"));
    }

    #[test]
    fn multiple_attenuations_independent() {
        let root_key = generate_root_key();
        let base = Macaroon::create(&root_key, "s1", "lumen");

        // Attenuate in two different directions
        let read_only = base.attenuate(&caveats::read_only());
        let write_only = base.attenuate(&caveats::method("tools/call"));

        // Both verify with the base conditions
        assert!(read_only.verify(&root_key, caveats::is_read_only));
        assert!(write_only.verify(&root_key, |c| {
            caveats::parse_method(c) == Some("tools/call")
        }));

        // But not with swapped conditions
        assert!(!read_only.verify(&root_key, |c| {
            caveats::parse_method(c) == Some("tools/call")
        }));
    }

    #[test]
    fn empty_id_and_location() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "", "");
        assert_eq!(mac.id, "");
        assert_eq!(mac.location, "");

        let encoded = mac.encode();
        let decoded = Macaroon::decode(&encoded).unwrap();
        assert_eq!(decoded.id, "");
        assert!(decoded.verify(&root_key, |_| true));
    }

    // ── Edge cases ──────────────────────────────────────────────────────

    #[test]
    fn macaroon_max_caveats_truncation() {
        let root_key = generate_root_key();
        let mut mac = Macaroon::create(&root_key, "s1", "lumen");
        // Add more than MAX_CAVEATS
        for i in 0..40 {
            mac = mac.attenuate(&format!("caveat-{i}"));
        }
        // Encode truncates to 32 caveats
        let encoded = mac.encode();
        let decoded = Macaroon::decode(&encoded).unwrap();
        // Decode sees only 32 caveats (the encoded ones)
        assert_eq!(decoded.caveats.len(), 32);

        // Signature was computed with all 40 caveats, but decode only has 32
        // → verification MUST fail for truncated macaroons
        assert!(!decoded.verify(&root_key, |_| true));
    }

    #[test]
    fn macaroon_wrong_version_rejected() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "s", "l");
        let mut encoded = mac.encode();
        encoded[0] = 99; // corrupt version
        assert!(
            Macaroon::decode(&encoded).is_none(),
            "unknown version must be rejected"
        );
    }

    #[test]
    fn macaroon_tampered_signature_detected() {
        let root_key = generate_root_key();
        let mut mac = Macaroon::create(&root_key, "s", "l");
        // Flip a bit in the signature
        mac.signature[0] ^= 0x01;
        assert!(!mac.verify(&root_key, |_| true));
    }

    #[test]
    fn macaroon_tampered_id_detected() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "original-id", "l");
        let mut encoded = mac.encode();
        // Tamper the id bytes (id is at offset 3: version=1, len=1)
        encoded[3] = b'X'; // change 'o' to 'X'

        let decoded = Macaroon::decode(&encoded).unwrap();
        assert!(!decoded.verify(&root_key, |_| true));
    }

    #[test]
    fn macaroon_id_truncation_roundtrip() {
        let root_key = generate_root_key();
        let long_id = "a".repeat(300);
        let mac = Macaroon::create(&root_key, &long_id, "lumen");
        let encoded = mac.encode();
        let decoded = Macaroon::decode(&encoded).unwrap();
        // Id was truncated to 255 bytes during encode → decode sees 255
        assert_eq!(decoded.id.len(), 255);
        // Signature was computed with full 300-char id, but decode has 255
        // → verification fails (this is expected: truncation breaks signature)
        assert!(!decoded.verify(&root_key, |_| true));
    }

    #[test]
    fn macaroon_encoded_len_matches() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "session-1", "lumen-mcp")
            .attenuate(&caveats::method("tools/list"))
            .attenuate(&caveats::read_only());
        assert_eq!(mac.encode().len(), mac.encoded_len());
    }

    #[test]
    fn macaroon_verify_with_trailing_data_in_buffer() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "s", "l");
        let mut encoded = mac.encode();
        // Append garbage after the signature
        encoded.extend_from_slice(b"trailing garbage that should not matter");
        // decode ignores trailing bytes after signature
        let decoded = Macaroon::decode(&encoded).unwrap();
        assert!(decoded.verify(&root_key, |_| true));
    }
}
