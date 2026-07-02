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
//! ## Security Considerations
//!
//! **WARNING: X25519 key exchange provides encryption but NOT
//! authentication.** Without an external authentication mechanism
//! (TLS, Ed25519 signatures, pre-shared keys, or certificate pinning),
//! LUMEN wire encryption is vulnerable to man-in-the-middle attacks.
//!
//! The current implementation is **opportunistic encryption** — it
//! protects against passive eavesdropping but NOT against active
//! attackers who can intercept and modify the key exchange.
//!
//! For production deployments that need authenticated channels:
//! - Use LUMEN over a TLS connection (QUIC or TCP+TLS)
//! - Or add Ed25519 identity keys and signature verification to the
//!   handshake (planned for v0.2)
//! - Or use a trusted side-channel for public key distribution
//!
//! **Frame metadata authentication:** frame type and flags are included
//! in the AEAD additional authenticated data (AAD), so an attacker
//! cannot change REQUEST↔RESPONSE or toggle COMPRESSED/ENCRYPTED
//! without detection.
//!
//! **Anti-replay:** a DTLS-style sliding window (64 nonces) prevents
//! replay attacks. The window is only advanced AFTER successful AEAD
//! authentication, preventing DoS via invalid ciphertext.
//! ## Nonce construction
//!
//! Nonce = [counter: u64 LE][zeros: 4B] = 12 bytes
//! Counter is per-direction, monotonically increasing.

use chacha20poly1305::{
    aead::{KeyInit, OsRng},
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
    ///
    /// Returns `None` if the DH output is all zeros, which happens exactly
    /// when the peer's public key is a low-order point (contributory-behavior
    /// check, RFC 7748 §6.1). A `None` result MUST abort the encrypted
    /// handshake — deriving session keys from a zero secret would let an
    /// active attacker force a predictable key.
    pub fn derive_shared_secret(&self, peer_public: &PublicKey) -> Option<[u8; 32]> {
        let shared = self.secret.diffie_hellman(peer_public);
        if !shared.was_contributory() {
            return None;
        }
        Some(*shared.as_bytes())
    }

    /// Cheap pre-check on a raw peer public key: rejects the all-zero encoding.
    ///
    /// This is NOT a complete low-order-point check — that is done by the
    /// contributory check in [`Keypair::derive_shared_secret`], which rejects
    /// every peer key whose DH output is all zeros (the full set of low-order
    /// points, not just the zero encoding).
    pub fn validate_public_key(bytes: &[u8; 32]) -> bool {
        *bytes != [0u8; 32]
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

/// DTLS-style sliding window size (64 nonces).
const WINDOW_SIZE: u64 = 64;

/// Check whether `nonce` is acceptable without modifying state.
///
/// Returns `Ok(())` if the nonce passes anti-replay checks, or
/// `Err(DecryptError::NonceReuse)` if it's a replay or outside window.
fn check_nonce_candidate(
    window: u64,
    bitmap: u64,
    nonce: u64,
) -> Result<(), DecryptError> {
    // Sentinel: u64::MAX means "no nonces received yet" — accept any.
    if window == u64::MAX {
        return Ok(());
    }

    if nonce > window {
        // Nonce in the future — acceptable (gap)
        Ok(())
    } else if nonce == window {
        Err(DecryptError::NonceReuse)
    } else {
        let offset = window - nonce;
        if offset > WINDOW_SIZE {
            return Err(DecryptError::NonceReuse);
        }
        let mask = 1u64 << (offset - 1);
        if bitmap & mask != 0 {
            Err(DecryptError::NonceReuse)
        } else {
            Ok(())
        }
    }
}

/// Commit a nonce to the sliding window after successful AEAD decryption.
fn commit_nonce(window: &mut u64, bitmap: &mut u64, nonce: u64) {
    // Sentinel → first nonce: mark all prior nonces as "seen" so only
    // the first nonce itself is accepted. Anything before the session
    // start is a replay.
    if *window == u64::MAX {
        *window = nonce;
        // Mark all nonces from 0..nonce as seen (bitmask covering the gap).
        // Cap at WINDOW_SIZE since that's all we can track.
        if nonce > 0 {
            let gap = nonce.min(WINDOW_SIZE);
            *bitmap = if gap >= 64 { u64::MAX } else { (1u64 << gap) - 1 };
        }
        return;
    }

    if nonce > *window {
        let diff = nonce - *window;
        *bitmap = if diff >= WINDOW_SIZE {
            // The old right edge scrolled out of the 64-nonce range; nothing
            // below the new window is tracked as seen.
            0
        } else {
            // Shift, then mark the OLD right edge (now at bit diff-1) as
            // seen. Nonces inside the gap stay unseen so late out-of-order
            // frames are still accepted.
            (*bitmap << diff) | (1u64 << (diff - 1))
        };
        *window = nonce;
    } else if nonce == *window {
        // Should've been caught by check_nonce_candidate — nothing to do.
    } else {
        let offset = *window - nonce;
        let mask = 1u64 << (offset - 1);
        *bitmap |= mask;
    }
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
            // Sentinel: u64::MAX means "no nonces received yet".
            // The first nonce (typically 0) will be > u64::MAX? No — but we
            // treat the sentinel specially in check_nonce.
            recv_window: u64::MAX,
            recv_bitmap: 0,
        }
    }

    /// Build a nonce from a counter value.
    fn make_nonce(counter: u64) -> Nonce {
        let mut bytes = [0u8; NONCE_SIZE];
        bytes[..8].copy_from_slice(&counter.to_le_bytes());
        *Nonce::from_slice(&bytes)
    }

    /// Encrypt a plaintext frame payload with AAD.
    ///
    /// AAD = `[frame_type: u8][flags: u8]` — authenticates frame metadata
    /// so an attacker cannot change type/flags without detection.
    /// Returns `[NONCE:12B][CIPHERTEXT+tag]`.
    pub fn encrypt(&mut self, frame_type: u8, flags: u8, plaintext: &[u8]) -> Vec<u8> {
        use chacha20poly1305::aead::AeadInPlace;
        let nonce = Self::make_nonce(self.send_counter);
        self.send_counter += 1;

        // Build AAD from frame metadata
        let aad = [frame_type, flags];

        // ciphertext = plaintext + tag (16 bytes)
        let mut buffer = Vec::with_capacity(plaintext.len() + TAG_SIZE);
        buffer.extend_from_slice(plaintext);
        buffer.resize(plaintext.len() + TAG_SIZE, 0);

        let tag = self
            .send_aead
            .encrypt_in_place_detached(&nonce, &aad, &mut buffer[..plaintext.len()])
            .expect("ChaCha20-Poly1305 encrypt should not fail");
        buffer[plaintext.len()..].copy_from_slice(tag.as_slice());

        let mut out = Vec::with_capacity(NONCE_SIZE + buffer.len());
        out.extend_from_slice(nonce.as_slice());
        out.extend_from_slice(&buffer);
        out
    }

    /// Decrypt a received encrypted payload with AAD verification.
    ///
    /// Expects `[NONCE:12B][CIPHERTEXT+tag]`. AAD must match the frame's
    /// type and flags. Returns the plaintext.
    pub fn decrypt(
        &mut self,
        frame_type: u8,
        flags: u8,
        encrypted: &[u8],
    ) -> Result<Vec<u8>, DecryptError> {
        use chacha20poly1305::aead::AeadInPlace;
        use chacha20poly1305::Tag;

        if encrypted.len() < NONCE_SIZE + TAG_SIZE {
            return Err(DecryptError::TooShort);
        }

        let (nonce_bytes, ciphertext) = encrypted.split_at(NONCE_SIZE);
        let nonce = Nonce::from_slice(nonce_bytes);
        let recv_nonce = u64::from_le_bytes(nonce_bytes[..8].try_into().unwrap());

        // Step 1: Check anti-replay WITHOUT modifying state.
        check_nonce_candidate(self.recv_window, self.recv_bitmap, recv_nonce)?;

        // Step 2: Authenticate and decrypt with AAD.
        let aad = [frame_type, flags];
        let plaintext_len = ciphertext.len() - TAG_SIZE;
        let mut buffer = ciphertext.to_vec();
        let tag = Tag::from_slice(&ciphertext[plaintext_len..]);

        self.recv_aead
            .decrypt_in_place_detached(nonce, &aad, &mut buffer[..plaintext_len], tag)
            .map_err(|_| DecryptError::AuthenticationFailed)?;

        buffer.truncate(plaintext_len);

        // Step 3: Only NOW commit the nonce — AEAD already verified.
        commit_nonce(&mut self.recv_window, &mut self.recv_bitmap, recv_nonce);

        Ok(buffer)
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
        let encrypted_payload = self.encrypt(frame_type, flags, plaintext);
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
    use crate::frame::TYPE_REQUEST;

    #[test]
    fn keypair_generate_and_dh() {
        let alice = Keypair::generate();
        let bob = Keypair::generate();

        let shared_alice = alice.derive_shared_secret(&bob.public).unwrap();
        let shared_bob = bob.derive_shared_secret(&alice.public).unwrap();

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
        let shared = kp_alice.derive_shared_secret(&kp_bob.public).unwrap();

        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let plaintext = b"Hello, encrypted LUMEN world!";
        let ciphertext = enc.encrypt(TYPE_REQUEST, 0, plaintext);

        assert_eq!(ciphertext.len(), NONCE_SIZE + plaintext.len() + TAG_SIZE);

        let decrypted = dec.decrypt(TYPE_REQUEST, 0, &ciphertext).unwrap();
        assert_eq!(decrypted, plaintext);
    }

    #[test]
    fn same_role_cannot_decrypt_other_direction() {
        // Two ciphers with the same Role use different send/recv keys.
        // The initiator's encrypted output should NOT be decryptable by
        // another initiator (they'd both use c2s for sending, but the
        // receiver would use its recv_aead=s2c, which doesn't match).
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();

        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec_wrong = Cipher::new(&shared, Role::Initiator); // same role!

        let ct = enc.encrypt(TYPE_REQUEST, 0, b"secret");
        assert!(matches!(
            dec_wrong.decrypt(TYPE_REQUEST, 0, &ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn encrypt_decrypt_multiple_frames() {
        let kp = Keypair::generate();
        let shared = kp.derive_shared_secret(&kp.public).unwrap(); // self-DH for test
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        for i in 0..100u64 {
            let msg = format!("frame {}", i);
            let ct = enc.encrypt(TYPE_REQUEST, 0, msg.as_bytes());
            let pt = dec.decrypt(TYPE_REQUEST, 0, &ct).unwrap();
            assert_eq!(pt, msg.as_bytes());
        }
    }

    #[test]
    fn wrong_key_fails_authentication() {
        let shared1 = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let shared2 = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();

        let mut enc = Cipher::new(&shared1, Role::Initiator);
        let mut dec = Cipher::new(&shared2, Role::Responder);

        let ct = enc.encrypt(TYPE_REQUEST, 0, b"test");
        assert!(matches!(
            dec.decrypt(TYPE_REQUEST, 0, &ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn tampered_ciphertext_fails() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let mut ct = enc.encrypt(TYPE_REQUEST, 0, b"secret data");
        // Flip a byte in the ciphertext
        ct[NONCE_SIZE + 2] ^= 0xFF;

        assert!(matches!(
            dec.decrypt(TYPE_REQUEST, 0, &ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn nonce_reuse_detected() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let ct1 = enc.encrypt(TYPE_REQUEST, 0, b"first");
        let ct2 = enc.encrypt(TYPE_REQUEST, 0, b"second");

        let _ = dec.decrypt(TYPE_REQUEST, 0, &ct2).unwrap(); // skip first
        assert!(matches!(
            dec.decrypt(TYPE_REQUEST, 0, &ct1),
            Err(DecryptError::NonceReuse)
        ));
    }

    #[test]
    fn out_of_order_delivery_with_gap() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let ct0 = enc.encrypt(TYPE_REQUEST, 0, b"n0");
        let ct1 = enc.encrypt(TYPE_REQUEST, 0, b"n1");
        let ct2 = enc.encrypt(TYPE_REQUEST, 0, b"n2");

        // Deliver 0, then 2 (gap), then the late 1 — all must be accepted.
        dec.decrypt(TYPE_REQUEST, 0, &ct0).unwrap();
        dec.decrypt(TYPE_REQUEST, 0, &ct2).unwrap();
        dec.decrypt(TYPE_REQUEST, 0, &ct1)
            .expect("late in-window nonce must be accepted");

        // Every replay must now be rejected — including ct0, whose nonce was
        // the window edge when the gap opened.
        for ct in [&ct0, &ct1, &ct2] {
            assert!(matches!(
                dec.decrypt(TYPE_REQUEST, 0, ct),
                Err(DecryptError::NonceReuse)
            ));
        }
    }

    #[test]
    fn replay_window_survives_large_gap() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        // Nonces 0..=100
        let cts: Vec<Vec<u8>> = (0..=100u64)
            .map(|i| enc.encrypt(TYPE_REQUEST, 0, format!("n{i}").as_bytes()))
            .collect();

        dec.decrypt(TYPE_REQUEST, 0, &cts[0]).unwrap();
        // Jump the window far ahead (gap > WINDOW_SIZE resets the bitmap)
        dec.decrypt(TYPE_REQUEST, 0, &cts[100]).unwrap();
        // A late nonce inside the new window is accepted…
        dec.decrypt(TYPE_REQUEST, 0, &cts[50]).unwrap();
        // …but replays are rejected: in-window (50, 100) and below-window (0).
        for ct in [&cts[50], &cts[100], &cts[0]] {
            assert!(matches!(
                dec.decrypt(TYPE_REQUEST, 0, ct),
                Err(DecryptError::NonceReuse)
            ));
        }
    }

    #[test]
    fn low_order_peer_key_rejected_in_dh() {
        // The all-zero encoding is a low-order point: DH output is all zeros
        // and derive_shared_secret must refuse it.
        let kp = Keypair::generate();
        let low_order = PublicKey::from([0u8; 32]);
        assert!(kp.derive_shared_secret(&low_order).is_none());

        // The order-8 point (from RFC 7748 / libsodium's blocklist) must
        // also be rejected — this one passes the all-zero pre-check.
        let order8: [u8; 32] = [
            0xe0, 0xeb, 0x7a, 0x7c, 0x3b, 0x41, 0xb8, 0xae,
            0x16, 0x56, 0xe3, 0xfa, 0xf1, 0x9f, 0xc4, 0x6a,
            0xda, 0x09, 0x8d, 0xeb, 0x9c, 0x32, 0xb1, 0xfd,
            0x86, 0x62, 0x05, 0x16, 0x5f, 0x49, 0xb8, 0x00,
        ];
        assert!(Keypair::validate_public_key(&order8), "pre-check alone cannot catch this point");
        assert!(kp.derive_shared_secret(&PublicKey::from(order8)).is_none());
    }

    #[test]
    fn build_encrypted_frame_roundtrip() {
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
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
        let plaintext = dec.decrypt(TYPE_REQUEST, 0, parsed.payload).unwrap();
        assert_eq!(plaintext, b"{\"method\":\"tools/list\"}");
    }

    #[test]
    fn encrypted_len_roundtrip() {
        assert_eq!(encrypted_len(100), NONCE_SIZE + 100 + TAG_SIZE);
        assert_eq!(plaintext_len(encrypted_len(100)), Some(100));
        assert_eq!(plaintext_len(10), None); // too short
    }

    #[test]
    fn aad_type_mismatch_detected() {
        // Verify that AAD protects frame type: changing type fails decrypt
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let ct = enc.encrypt(TYPE_REQUEST, 0, b"data");
        // Try to decrypt with wrong type → must fail
        assert!(matches!(
            dec.decrypt(crate::frame::TYPE_RESPONSE, 0, &ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }

    #[test]
    fn aad_flags_mismatch_detected() {
        // Verify that AAD protects flags: changing flags fails decrypt
        let shared = Keypair::generate().derive_shared_secret(&Keypair::generate().public).unwrap();
        let mut enc = Cipher::new(&shared, Role::Initiator);
        let mut dec = Cipher::new(&shared, Role::Responder);

        let ct = enc.encrypt(TYPE_REQUEST, 0, b"data");
        // Try to decrypt with wrong flags → must fail
        assert!(matches!(
            dec.decrypt(TYPE_REQUEST, crate::frame::FLAG_COMPRESSED, &ct),
            Err(DecryptError::AuthenticationFailed)
        ));
    }
}
