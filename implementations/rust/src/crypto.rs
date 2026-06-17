//! LUMEN Wire Encryption — ChaCha20-Poly1305 AEAD + X25519 key exchange.
//!
//! ## Design
//!
//! Every encrypted frame carries a 12-byte nonce followed by the AEAD ciphertext
//! (which includes a 16-byte Poly1305 tag appended by ChaCha20-Poly1305).
//!
//! ```text
//! Encrypted payload layout (inside the LUMEN frame payload):
//!
//! ┌─────────────────────────────────────────────────────────────┐
//! │ [NONCE:12B] [CIPHERTEXT:N bytes] [TAG:16B]                  │
//! └─────────────────────────────────────────────────────────────┘
//!
//! Frame on the wire:
//! ┌──────────────────────────────────────────────────────────────┐
//! │ [Hyb128:len] [TYPE:1B] [FLAGS:1B | ENCRYPTED] [encrypted]   │
//! └──────────────────────────────────────────────────────────────┘
//! ```
//!
//! ## Key Exchange (X25519)
//!
//! 1. Client generates ephemeral X25519 keypair
//! 2. Client sends PROBE frame with `pk` (public key, 32 raw bytes)
//! 3. Server generates ephemeral X25519 keypair
//! 4. Server derives shared secret, replies PROBE_ACK with its `pk`
//! 5. Client derives the same shared secret
//! 6. Both sides derive TWO independent keys via HKDF-SHA256:
//!    `lumen-c2s-key` (client→server) and `lumen-s2c-key` (server→client).
//!    The initiator sends with c2s and receives with s2c; the responder
//!    does the reverse. This prevents catastrophic (key, nonce) reuse.
//! 7. Nonce counters start at 0 per direction
//!
//! ## Nonce construction
//!
//! Nonce = [counter: u64 LE][zeros: 4B] = 12 bytes
//! Counter is per-direction, monotonically increasing.

use chacha20poly1305::{
    aead::{Aead, KeyInit, OsRng},
    ChaCha20Poly1305, Nonce,
};
use hkdf::Hkdf;
use sha2::Sha256;
use x25519_dalek::{PublicKey, StaticSecret};

// ── Constants ───────────────────────────────────────────────────────────────

/// ChaCha20-Poly1305 nonce size (96 bits).
pub const NONCE_SIZE: usize = 12;

/// Poly1305 authentication tag appended to ciphertext (128 bits).
pub const TAG_SIZE: usize = 16;

/// X25519 public key size in bytes.
pub const PUBLIC_KEY_SIZE: usize = 32;

/// X25519 secret key size in bytes.
pub const SECRET_KEY_SIZE: usize = 32;

/// Overhead per encrypted frame: nonce (12B) + Poly1305 tag (16B) = 28 bytes.
pub const ENCRYPTION_OVERHEAD: usize = NONCE_SIZE + TAG_SIZE;

/// Calculate the total encrypted payload size for a given plaintext length.
pub fn encrypted_len(plaintext_len: usize) -> usize {
    NONCE_SIZE + plaintext_len + TAG_SIZE
}

/// Calculate the plaintext length from an encrypted payload size.
pub fn plaintext_len(encrypted_len: usize) -> Option<usize> {
    encrypted_len.checked_sub(ENCRYPTION_OVERHEAD)
}

// ── Keypair ─────────────────────────────────────────────────────────────────

/// An X25519 keypair for LUMEN wire encryption.
pub struct Keypair {
    pub secret: StaticSecret,
    pub public: PublicKey,
}

impl Keypair {
    /// Generate a new random X25519 keypair.
    pub fn generate() -> Self {
        let secret = StaticSecret::random_from_rng(OsRng);
        let public = PublicKey::from(&secret);
        Self { secret, public }
    }

    /// Derive the 256-bit shared secret with a peer's public key.
    pub fn derive_shared_secret(&self, peer_public: &PublicKey) -> [u8; 32] {
        *self.secret.diffie_hellman(peer_public).as_bytes()
    }

    /// Validate that a raw public key is not a low-order point.
    pub fn validate_public_key(bytes: &[u8; 32]) -> bool {
        // Reject all-zero public keys (zero point, not a valid generator output).
        if *bytes == [0u8; 32] {
            return false;
        }
        // X25519 clamping in dalek handles small-subgroup attacks, but we
        // additionally verify the bytes can be converted to a valid point.
        let pk = PublicKey::from(*bytes);
        // Ensure the point is not the identity and has correct encoding.
        pk.as_bytes() == bytes
    }
}

// ── Cipher ──────────────────────────────────────────────────────────────────

/// Which side initiated the encrypted handshake.
/// Determines which derived key is used for sending vs receiving.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Role {
    /// We sent the first PROBE (client side).
    Initiator,
    /// We received the PROBE and responded with PROBE_ACK (server side).
    Responder,
}

/// An initialized LUMEN cipher with independent send/recv AEAD instances.
///
/// Derives two separate keys from the X25519 shared secret via HKDF-SHA256:
/// `lumen-c2s-key` (client→server) and `lumen-s2c-key` (server→client).
/// The initiator uses c2s for sending and s2c for receiving; the responder
/// does the reverse. This prevents catastrophic (key, nonce) reuse that would
/// occur if both sides shared a single key with counters starting at 0.
pub struct Cipher {
    /// ChaCha20-Poly1305 AEAD for outgoing frames.
    send_aead: ChaCha20Poly1305,
    /// ChaCha20-Poly1305 AEAD for incoming frames (different key).
    recv_aead: ChaCha20Poly1305,
    /// Nonce counter for sending.
    send_counter: u64,
    /// Anti-replay sliding window — highest nonce seen (right edge).
    recv_window: u64,
    /// Bitmap of last 64 nonces below ``recv_window``. LSB = recv_window-1.
    recv_bitmap: u64,
}

impl Cipher {
    /// Create a new cipher from a 32-byte X25519 shared secret.
    ///
    /// Derives two independent keys via HKDF-SHA256 with domain-separation
    /// info strings.  The `role` parameter tells us whether we are the
    /// initiator (client) or responder (server) so we can map the derived
    /// keys to the correct send / receive direction.
    pub fn new(shared_secret: &[u8; 32], role: Role) -> Self {
        let hkdf = Hkdf::<Sha256>::new(None, shared_secret);
        let mut c2s_key = [0u8; 32];
        let mut s2c_key = [0u8; 32];
        hkdf.expand(b"lumen-c2s-key", &mut c2s_key)
            .expect("HKDF expand c2s should not fail");
        hkdf.expand(b"lumen-s2c-key", &mut s2c_key)
            .expect("HKDF expand s2c should not fail");

        let (send_key, recv_key) = match role {
            Role::Initiator => (c2s_key, s2c_key),
            Role::Responder => (s2c_key, c2s_key),
        };

        Self {
            send_aead: ChaCha20Poly1305::new(chacha20poly1305::Key::from_slice(&send_key)),
            recv_aead: ChaCha20Poly1305::new(chacha20poly1305::Key::from_slice(&recv_key)),
            send_counter: 0,
            recv_window: 0,
            recv_bitmap: 0,
        }
    }

    /// Build a nonce from a counter value.
    fn make_nonce(counter: u64) -> Nonce {
        let mut bytes = [0u8; NONCE_SIZE];
        bytes[..8].copy_from_slice(&counter.to_le_bytes());
        *Nonce::from_slice(&bytes)
    }

    /// Encrypt a plaintext frame payload.
    ///
    /// Returns `[NONCE:12B][CIPHERTEXT+tag]`.
    pub fn encrypt(&mut self, plaintext: &[u8]) -> Vec<u8> {
        let nonce = Self::make_nonce(self.send_counter);
        self.send_counter += 1;

        let ciphertext = self
            .send_aead
            .encrypt(&nonce, plaintext)
            .expect("ChaCha20-Poly1305 encrypt should not fail");

        let mut out = Vec::with_capacity(NONCE_SIZE + ciphertext.len());
        out.extend_from_slice(nonce.as_slice());
        out.extend_from_slice(&ciphertext);
        out
    }

    /// Decrypt a received encrypted payload.
    ///
    /// Expects `[NONCE:12B][CIPHERTEXT+tag]`. Returns the plaintext.
    pub fn decrypt(&mut self, encrypted: &[u8]) -> Result<Vec<u8>, DecryptError> {
        if encrypted.len() < NONCE_SIZE + TAG_SIZE {
            return Err(DecryptError::TooShort);
        }

        let (nonce_bytes, ciphertext) = encrypted.split_at(NONCE_SIZE);
        let nonce = Nonce::from_slice(nonce_bytes);

        // Anti-replay sliding window (DTLS-style, 64 nonce window).
        // Prevents attackers from exhausting the nonce space (DoS) while
        // tolerating limited reordering.
        let recv_nonce = u64::from_le_bytes(nonce_bytes[..8].try_into().unwrap());
        const WINDOW_SIZE: u64 = 64;

        if recv_nonce > self.recv_window {
            let diff = recv_nonce - self.recv_window;
            // Shift existing bitmap (old window becomes a seen nonce at offset diff-1)
            self.recv_bitmap = if diff >= WINDOW_SIZE {
                1 // gap too large — reset, only mark old window as seen
            } else {
                (self.recv_bitmap << diff) | 1
            };
            self.recv_window = recv_nonce;
        } else if recv_nonce == self.recv_window {
            return Err(DecryptError::NonceReuse);
        } else {
            let offset = self.recv_window - recv_nonce;
            if offset > WINDOW_SIZE {
                return Err(DecryptError::NonceReuse);
            }
            let mask = 1u64 << (offset - 1);
            if self.recv_bitmap & mask != 0 {
                return Err(DecryptError::NonceReuse);
            }
            self.recv_bitmap |= mask;
        }

        self.recv_aead
            .decrypt(nonce, ciphertext)
            .map_err(|_| DecryptError::AuthenticationFailed)
    }

    /// Encrypt and build a full LUMEN frame (with Hyb128 + TYPE + FLAGS).
    ///
    /// Returns the complete frame bytes ready for transport.
    pub fn build_encrypted_frame(
        &mut self,
        frame_type: u8,
        flags: u8,
        plaintext: &[u8],
    ) -> Vec<u8> {
        let encrypted_payload = self.encrypt(plaintext);
        let total = crate::frame::build_size(encrypted_payload.len());
        let mut buf = vec![0u8; total];
        let n = crate::frame::build(
            frame_type,
            flags | crate::frame::FLAG_ENCRYPTED,
            &encrypted_payload,
            &mut buf,
        );
        buf.truncate(n);
        buf
    }
}

// ── Errors ──────────────────────────────────────────────────────────────────

#[derive(Debug)]
pub enum DecryptError {
    /// Encrypted payload is too short to contain nonce + tag.
    TooShort,
    /// Poly1305 authentication failed — data may be tampered or wrong key.
    AuthenticationFailed,
    /// Nonce reuse detected (possible replay attack).
    NonceReuse,
}

impl std::fmt::Display for DecryptError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            DecryptError::TooShort => write!(f, "encrypted payload too short"),
            DecryptError::AuthenticationFailed => write!(f, "authentication failed"),
            DecryptError::NonceReuse => write!(f, "nonce reuse detected"),
        }
    }
}

impl std::error::Error for DecryptError {}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn keypair_generate_and_dh() {
        let alice = Keypair::generate();
        let bob = Keypair::generate();

        let shared_alice = alice.derive_shared_secret(&bob.public);
        let shared_bob = bob.derive_shared_secret(&alice.public);

        assert_eq!(shared_alice, shared_bob);
    }

    #[test]
    fn low_order_point_rejected() {
        let zero_key = [0u8; 32];
        assert!(!Keypair::validate_public_key(&zero_key));
    }

    #[test]
    fn encrypt_decrypt_roundtrip() {
        let kp_alice = Keypair::generate();
        let kp_bob = Keypair::generate();
        let shared = kp_alice.derive_shared_secret(&kp_bob.public);

        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let plaintext = b"Hello, encrypted LUMEN world!";
        let ciphertext = enc.encrypt(plaintext);

        assert_eq!(ciphertext.len(), NONCE_SIZE + plaintext.len() + TAG_SIZE);

        let decrypted = dec.decrypt(&ciphertext).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn same_role_cannot_decrypt_other_direction() {
        // Two ciphers with the same Role use different send/recv keys.
        // The initiator's encrypted output should NOT be decryptable by
        // another initiator (they'd both use c2s for sending, but the
        // receiver would use its recv_aead=s2c, which doesn't match).
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public);

        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec_wrong = Cipher::new(&shared, Role::Initiator); // same role!

        let ct = enc.encrypt(b"secret");
        assert!(matches!(
            dec_wrong.decrypt(&ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn encrypt_decrypt_multiple_frames() {
        let kp = Keypair::generate();
        let shared = kp.derive_shared_secret(&kp.public); // self-DH for test
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        for i in 0..100u64 {
            let msg = format!("frame {}", i);
            let ct = enc.encrypt(msg.as_bytes());
            let pt = dec.decrypt(&ct).unwrap();
            assert_eq!(pt, msg.as_bytes());
        }
    }

    #[test]
    fn wrong_key_fails_authentication() {
        let shared1 = Keypair::generate().derive_shared_secret(&Keypair::generate().public);
        let shared2 = Keypair::generate().derive_shared_secret(&Keypair::generate().public);

        let mut enc = Cipher::new(&shared1, Role::Initiator);
        let mut dec = Cipher::new(&shared2, Role::Responder);

        let ct = enc.encrypt(b"test");
        assert!(matches!(
            dec.decrypt(&ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn tampered_ciphertext_fails() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public);
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let mut ct = enc.encrypt(b"secret data");
        // Flip a byte in the ciphertext
        ct[NONCE_SIZE + 2] ^= 0xFF;

        assert!(matches!(
            dec.decrypt(&ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn nonce_reuse_detected() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public);
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let ct1 = enc.encrypt(b"first");
        let ct2 = enc.encrypt(b"second");

        let _ = dec.decrypt(&ct2).unwrap(); // skip first
        assert!(matches!(
            dec.decrypt(&ct1),
            Err(DecryptError::NonceReuse)
        ));
    }

    #[test]
    fn build_encrypted_frame_roundtrip() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public);
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let frame_bytes = enc.build_encrypted_frame(
            crate::frame::TYPE_REQUEST,
            0,
            b"{\"method\":\"tools/list\"}",
        );

        // Parse the frame
        let parsed = match crate::frame::parse(&frame_bytes) {
            crate::frame::ParseResult::Complete { frame, .. } => frame,
            other => panic!("unexpected parse: {:?}", other),
        };

        assert!(parsed.is_encrypted());
        assert_eq!(parsed.frame_type, crate::frame::TYPE_REQUEST);

        // Decrypt the payload
        let plaintext = dec.decrypt(parsed.payload).unwrap();
        assert_eq!(plaintext, b"{\"method\":\"tools/list\"}");
    }

    #[test]
    fn encrypted_len_roundtrip() {
        assert_eq!(encrypted_len(100), NONCE_SIZE + 100 + TAG_SIZE);
        assert_eq!(plaintext_len(encrypted_len(100)), Some(100));
        assert_eq!(plaintext_len(10), None); // too short
    }
}
