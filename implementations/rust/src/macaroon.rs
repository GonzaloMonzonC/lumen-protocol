//! Macaroons — capability-based authorization tokens with attenuable caveats.
//!
//! Macaroons are bearer tokens that can be restricted (attenuated) by any
//! party in the chain without coordinating with the token issuer.  They use
//! HMAC-SHA256 for chained signatures.
//!
//! ## Wire format (little-endian)
//!
//! ```
//! [version: u8][id_len: u8][id: UTF-8]
//! [location_len: u8][location: UTF-8]
//! [caveat_count: u8][caveats...]
//! [signature: 32 bytes]
//!
//! Each caveat:
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

use sha2::{Sha256, Digest};

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

    /// Verify the macaroon against a root key and a set of caveat checkers.
    ///
    /// The `check_caveat` closure is called for each caveat in order.  If
    /// any caveat fails, verification returns `false`.  The signature is
    /// recomputed from the root key and all caveats, and compared against
    /// the stored signature.
    ///
    /// ## Example
    ///
    /// ```ignore
    /// let ok = mac.verify(&root_key, |caveat| {
    ///     if caveat.starts_with("method = ") {
    ///         let allowed = caveat.strip_prefix("method = ").unwrap();
    ///         allowed == requested_method
    ///     } else {
    ///         false // unknown caveat format → reject
    ///     }
    /// });
    /// ```
    pub fn verify<F>(&self, root_key: &[u8; 32], mut check_caveat: F) -> bool
    where
        F: FnMut(&str) -> bool,
    {
        // Check all caveats against the verifier's policy
        for caveat in &self.caveats {
            if !check_caveat(caveat) {
                return false;
            }
        }

        // Recompute the signature chain
        let mut sig = hmac_sha256(root_key, self.id.as_bytes());
        for caveat in &self.caveats {
            sig = hmac_sha256(&sig, caveat.as_bytes());
        }

        // Constant-time comparison to prevent timing attacks
        constant_time_eq(&sig, &self.signature)
    }

    // ── Serialisation ──────────────────────────────────────────────────

    /// Encode the macaroon to binary for wire transport.
    pub fn encode(&self) -> Vec<u8> {
        let id_bytes = self.id.as_bytes();
        let loc_bytes = self.location.as_bytes();
        let cap = 1 + 1 + id_bytes.len()
            + 1 + loc_bytes.len()
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

    /// Decode a macaroon from binary. Returns `None` on malformed input.
    pub fn decode(data: &[u8]) -> Option<Self> {
        if data.len() < Self::MIN_ENCODED_LEN {
            return None;
        }

        let version = data[0];
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
            + self.caveats.iter().map(|c| 1 + c.len().min(MAX_CAVEAT_LEN)).sum::<usize>()
    }
}

// ── Crypto helpers ──────────────────────────────────────────────────────────

/// HMAC-SHA256 as defined in RFC 2104.
///
/// HMAC(K, m) = H((K' ⊕ opad) || H((K' ⊕ ipad) || m))
/// where K' is K zero-padded to 64 bytes (SHA-256 block size),
/// ipad = 0x36 repeated, opad = 0x5C repeated.
fn hmac_sha256(key: &[u8], message: &[u8]) -> [u8; SIGNATURE_SIZE] {
    use sha2::{Sha256, Digest};

    const BLOCK_SIZE: usize = 64;
    let mut k_prime = [0u8; BLOCK_SIZE];

    // If key is longer than block size, hash it first
    if key.len() > BLOCK_SIZE {
        let mut hasher = Sha256::new();
        hasher.update(key);
        let hashed = hasher.finalize();
        k_prime[..32].copy_from_slice(&hashed);
    } else {
        let len = key.len().min(BLOCK_SIZE);
        k_prime[..len].copy_from_slice(key);
    }

    // Inner hash: H((K' ⊕ ipad) || message)
    let mut inner = Sha256::new();
    for b in &k_prime {
        inner.update([b ^ 0x36]);
    }
    inner.update(message);
    let inner_hash = inner.finalize();

    // Outer hash: H((K' ⊕ opad) || inner_hash)
    let mut outer = Sha256::new();
    for b in &k_prime {
        outer.update([b ^ 0x5C]);
    }
    outer.update(inner_hash);
    let result = outer.finalize();

    let mut tag = [0u8; SIGNATURE_SIZE];
    tag.copy_from_slice(&result);
    tag
}

/// Constant-time comparison of two 32-byte slices.
fn constant_time_eq(a: &[u8; 32], b: &[u8; 32]) -> bool {
    let mut diff = 0u8;
    for i in 0..32 {
        diff |= a[i] ^ b[i];
    }
    diff == 0
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
            0xb0, 0x34, 0x4c, 0x61, 0xd8, 0xdb, 0x38, 0x53,
            0x5c, 0xa8, 0xaf, 0xce, 0xaf, 0x0b, 0xf1, 0x2b,
            0x88, 0x1d, 0xc2, 0x00, 0xc9, 0x83, 0x3d, 0xa7,
            0x26, 0xe9, 0x37, 0x6c, 0x2e, 0x32, 0xcf, 0xf7,
        ];
        assert_eq!(hmac_sha256(&key, data), expected);

        // RFC 4231 test case 3: key 131 bytes of 0xAA
        let key3 = [0xAAu8; 131];
        let data3 = b"Test Using Larger Than Block-Size Key - Hash Key First";
        let expected3: [u8; 32] = [
            0x60, 0xe4, 0x31, 0x59, 0x1e, 0xe0, 0xb6, 0x7f,
            0x0d, 0x8a, 0x26, 0xaa, 0xcb, 0xf5, 0xb7, 0x7f,
            0x8e, 0x0b, 0xc6, 0x21, 0x37, 0x28, 0xc5, 0x14,
            0x05, 0x46, 0x04, 0x0f, 0x0e, 0xe3, 0x7f, 0x54,
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
            } else if caveats::is_read_only(c) {
                true
            } else {
                false
            }
        }));

        // Fail with wrong method
        let methods2 = ["tools/call"];
        assert!(!mac.verify(&root_key, |c| {
            if let Some(m) = caveats::parse_method(c) {
                methods2.contains(&m)
            } else if caveats::is_read_only(c) {
                true
            } else {
                false
            }
        }));
    }

    #[test]
    fn tampered_caveat_fails() {
        let root_key = generate_root_key();
        let mut mac = Macaroon::create(&root_key, "s1", "lumen")
            .attenuate(&caveats::method("tools/list"));

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
            caveats::parse_method(c).map_or(true, |m| m == "tools/call")
                && caveats::parse_tool(c).map_or(true, |t| t == "search")
                && caveats::parse_expiry(c).map_or(true, |_| true)
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
        let mac = Macaroon::create(&root_key, "s", "l")
            .attenuate(&caveats::method("tools/list"));

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
        assert_eq!(caveats::parse_method("method = tools/call"), Some("tools/call"));
        assert_eq!(caveats::parse_method("tool = x"), None);
        assert_eq!(caveats::parse_expiry("expiry < 2026-01-01"), Some("2026-01-01"));
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
        assert!(read_only.verify(&root_key, |c| caveats::is_read_only(c)));
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
    fn macaroon_wrong_version_decode() {
        let root_key = generate_root_key();
        let mac = Macaroon::create(&root_key, "s", "l");
        let mut encoded = mac.encode();
        encoded[0] = 99; // corrupt version

        let decoded = Macaroon::decode(&encoded).unwrap();
        assert_eq!(decoded.version, 99); // decode accepts any version
        // But verify still works — version is not validated in verify()
        assert!(decoded.verify(&root_key, |_| true));
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
    fn macaroon_encoded_len_matches()
    {
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
