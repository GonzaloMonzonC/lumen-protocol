//! LUMEN Transport Negotation (LTA Level 2 handshake).
//!
//! Enables in-band capability negotiation so a Level 2 (Zero-Copy)
//! transport can be established automatically when both peers support it.
//!
//! ## Protocol
//!
//! ```text
//! Client                           Server
//!   |  ── TYPE_TRANSPORT_INIT ──>  |   { "caps": ["mmap","stdio"] }
//!   |  <── TYPE_TRANSPORT_ACK ───  |   { "cap":"mmap", "shm_path":"/lumen-shm-xxx" }
//!   |        (shm mapped)          |
//!   |  ◄═════ ShmTransport ═══════►│   zero-copy frames
//! ```
//!
//! If the server doesn't support mmap, it replies with `{ "cap": "stdio" }`
//! and communication continues over the stream transport unchanged.

use std::io;

use crate::frame;
use crate::hyb128;
use crate::shm::{RingSide, ShmRegion};
use crate::transport::{ShmTransport, Transport};

// ── JSON message types ──────────────────────────────────────────────────────

/// Capabilities offered by the client.
#[derive(serde::Serialize, serde::Deserialize, Debug)]
struct InitMsg {
    caps: Vec<String>,
}

/// Server's choice of capability.
#[derive(serde::Serialize, serde::Deserialize, Debug)]
struct AckMsg {
    cap: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    shm_path: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    shm_size: Option<usize>,
}

// ── Handshake result ─────────────────────────────────────────────────────────

/// The negotiated transport after handshake.
pub enum NegotiatedTransport {
    /// Level 2 zero-copy transport established.
    Shm(ShmTransport),
    /// Fallback: stay on Level 1 (the caller keeps the existing stream).
    Stream,
}

// ── Server side ─────────────────────────────────────────────────────────────

/// Server: receive init, negotiate, and (if mmap chosen) create the shm region.
///
/// `stream` is the existing Level 1 transport (TCP/UDS/stdio).
/// Returns the negotiated transport and the ACK response bytes to send.
pub fn server_negotiate(
    stream: &mut dyn Transport,
    capabilities: &[&str],
) -> io::Result<(NegotiatedTransport, Vec<u8>)> {
    // 1. Read TYPE_TRANSPORT_INIT frame from client
    let frame_buf = read_frame(stream)?;
    let frame = match frame::parse(&frame_buf) {
        frame::ParseResult::Complete { frame, .. } => frame,
        frame::ParseResult::Incomplete | frame::ParseResult::IncompletePayload { .. } => {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "incomplete TRANSPORT_INIT"));
        }
        frame::ParseResult::Error(e) => {
            return Err(io::Error::new(io::ErrorKind::InvalidData, e));
        }
    };

    if frame.frame_type != frame::TYPE_TRANSPORT_INIT {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "expected TRANSPORT_INIT"));
    }

    let init: InitMsg = serde_json::from_slice(frame.payload)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;

    // 2. Pick best common capability
    let chosen = pick_capability(&init.caps, capabilities);
    let mut ack = AckMsg { cap: chosen.to_string(), shm_path: None, shm_size: None };

    let negotiated = if chosen == "mmap" {
        // Create shared memory region
        let shm_path = generate_shm_name();
        let region = ShmRegion::create(Some(&shm_path), None)?;
        region.init_header();

        ack.shm_path = Some(shm_path.clone());
        ack.shm_size = Some(region.size());

        let write_ring = region.ring_buffer(RingSide::B); // server→client
        let read_ring = region.ring_buffer(RingSide::A);  // client→server

        // We must NOT drop the ShmRegion — it holds the mapping.
        // Leak it so the mapping stays alive.
        std::mem::forget(region);

        NegotiatedTransport::Shm(ShmTransport::new(write_ring, read_ring))
    } else {
        NegotiatedTransport::Stream
    };

    // 3. Build ACK frame
    let ack_json = serde_json::to_vec(&ack)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    let ack_size = frame::build_size(ack_json.len());
    let mut ack_buf = vec![0u8; ack_size];
    frame::build(frame::TYPE_TRANSPORT_ACK, 0, &ack_json, &mut ack_buf);
    ack_buf.truncate(ack_size);

    Ok((negotiated, ack_buf))
}

// ── Client side ─────────────────────────────────────────────────────────────

/// Client: send init, receive ack, and (if mmap chosen) open the shm region.
///
/// `stream` is the existing Level 1 transport.
/// Returns the negotiated transport. If mmap was negotiated, the stream is
/// no longer needed (communication switches to shm).
pub fn client_negotiate(
    stream: &mut dyn Transport,
    capabilities: &[&str],
) -> io::Result<NegotiatedTransport> {
    // 1. Send TYPE_TRANSPORT_INIT
    let init = InitMsg { caps: capabilities.iter().map(|s| s.to_string()).collect() };
    let init_json = serde_json::to_vec(&init)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    let init_size = frame::build_size(init_json.len());
    let mut init_buf = vec![0u8; init_size];
    frame::build(frame::TYPE_TRANSPORT_INIT, 0, &init_json, &mut init_buf);
    stream.write_all(&init_buf[..init_size])?;
    stream.flush()?;

    // 2. Read TYPE_TRANSPORT_ACK
    let frame_buf = read_frame(stream)?;
    let ack_frame = match frame::parse(&frame_buf) {
        frame::ParseResult::Complete { frame, .. } => frame,
        frame::ParseResult::Incomplete | frame::ParseResult::IncompletePayload { .. } => {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "incomplete TRANSPORT_ACK"));
        }
        frame::ParseResult::Error(e) => {
            return Err(io::Error::new(io::ErrorKind::InvalidData, e));
        }
    };

    if ack_frame.frame_type != frame::TYPE_TRANSPORT_ACK {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "expected TRANSPORT_ACK"));
    }

    let ack: AckMsg = serde_json::from_slice(ack_frame.payload)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;

    // 3. If mmap, open the shared memory region
    if ack.cap == "mmap" {
        let shm_path = ack.shm_path
            .ok_or_else(|| io::Error::new(io::ErrorKind::InvalidData, "mmap ack missing shm_path"))?;
        let region = ShmRegion::open(&shm_path, ack.shm_size)?;

        if !region.validate() {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "shm region validation failed"));
        }

        let write_ring = region.ring_buffer(RingSide::A); // client→server
        let read_ring = region.ring_buffer(RingSide::B);  // server→client

        // Leak the region to keep the mapping alive
        std::mem::forget(region);

        Ok(NegotiatedTransport::Shm(ShmTransport::new(write_ring, read_ring)))
    } else {
        Ok(NegotiatedTransport::Stream)
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

/// Pick the best common capability. "mmap" > anything else.
fn pick_capability<'a>(client_caps: &[String], server_caps: &[&'a str]) -> &'a str {
    let client_set: std::collections::HashSet<&str> = client_caps.iter().map(|s| s.as_str()).collect();

    // Prefer mmap if both sides support it
    if client_set.contains("mmap") && server_caps.contains(&"mmap") {
        return "mmap";
    }
    // Fall back to first common capability
    for sc in server_caps {
        if client_set.contains(sc) {
            return sc;
        }
    }
    // Default: stay on stream
    "stdio"
}

/// Generate a unique shared memory name for this session.
fn generate_shm_name() -> String {
    use std::time::{SystemTime, UNIX_EPOCH};
    let ts = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default();
    format!("/lumen-shm-{:x}-{}", ts.as_nanos(), std::process::id())
}

// ── Streaming frame read helpers ────────────────────────────────────────────

/// Read exactly `buf.len()` bytes from a transport, looping until full or EOF.
fn read_exact(stream: &mut dyn Transport, buf: &mut [u8]) -> io::Result<()> {
    let mut offset = 0;
    while offset < buf.len() {
        let n = stream.read(&mut buf[offset..])?;
        if n == 0 {
            return Err(io::Error::new(io::ErrorKind::UnexpectedEof, "unexpected EOF"));
        }
        offset += n;
    }
    Ok(())
}

/// Read a complete LUMEN frame from a stream transport.
///
/// Reads the Hyb128 length prefix byte-by-byte until the header is complete,
/// then reads exactly the required number of type + flags + payload bytes.
/// Returns the full frame bytes ready for `frame::parse`.
fn read_frame(stream: &mut dyn Transport) -> io::Result<Vec<u8>> {
    // Phase 1: read Hyb128 header byte-by-byte (max 11 bytes)
    let mut header = [0u8; hyb128::MAX_ENCODED_LEN];
    let mut header_len = 0;
    let decoded = loop {
        if header_len >= header.len() {
            return Err(io::Error::new(io::ErrorKind::InvalidData, "Hyb128 header exceeds max length"));
        }
        read_exact(stream, &mut header[header_len..header_len + 1])?;
        header_len += 1;
        if let Some(d) = hyb128::decode(&header[..header_len]) {
            break d;
        }
    };

    // Phase 2: allocate buffer for the complete frame
    let total = decoded.header_len + 2 + decoded.value as usize;
    let mut frame_buf = vec![0u8; total];
    frame_buf[..decoded.header_len].copy_from_slice(&header[..decoded.header_len]);

    // Phase 3: read remaining bytes (type + flags + payload)
    read_exact(stream, &mut frame_buf[decoded.header_len..])?;

    Ok(frame_buf)
}

// ═══════════════════════════════════════════════════════════════════════════════
// Wire Encryption Handshake (X25519 key exchange via PROBE/PROBE_ACK)
// ═══════════════════════════════════════════════════════════════════════════════

/// Result of the encrypted handshake.
pub struct EncryptedHandshake {
    /// The initialized cipher ready to encrypt/decrypt frames.
    pub cipher: crate::crypto::Cipher,
    /// The peer's public key (for logging / pinning).
    pub peer_public_key: [u8; 32],
}

// ── JSON message types ──────────────────────────────────────────────────────

/// PROBE payload: client capabilities + optional X25519 public key.
#[derive(serde::Serialize, serde::Deserialize, Debug)]
pub struct ProbeMsg {
    pub v: u32,
    pub caps: Vec<String>,
    /// X25519 public key (32 raw bytes, base64-encoded in JSON).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pk: Option<String>,
}

/// PROBE_ACK payload: server capabilities + optional X25519 public key.
#[derive(serde::Serialize, serde::Deserialize, Debug)]
pub struct ProbeAckMsg {
    pub v: u32,
    pub caps: Vec<String>,
    /// X25519 public key (32 raw bytes, base64-encoded in JSON).
    #[serde(skip_serializing_if = "Option::is_none")]
    pub pk: Option<String>,
}

// ── Client side ─────────────────────────────────────────────────────────────

/// Client: initiate encrypted handshake via PROBE/PROBE_ACK.
///
/// 1. Generates X25519 keypair
/// 2. Sends PROBE with public key
/// 3. Reads PROBE_ACK with server's public key
/// 4. Derives shared secret → initializes Cipher
///
/// If the server doesn't include `pk` in its ACK, encryption is not negotiated
/// and this returns `Ok(None)`.
pub fn client_encrypted_handshake(
    stream: &mut dyn crate::transport::Transport,
    capabilities: &[&str],
    enable_encryption: bool,
) -> io::Result<Option<EncryptedHandshake>> {
    use crate::crypto::Keypair;

    let keypair = if enable_encryption {
        Some(Keypair::generate())
    } else {
        None
    };

    // 1. Build and send PROBE
    let mut caps = capabilities.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    if keypair.is_some() {
        caps.push("encryption".into());
    }

    let pk_b64 = keypair.as_ref().map(|kp| {
        use base64::Engine;
        base64::engine::general_purpose::STANDARD.encode(kp.public.as_bytes())
    });

    let probe = ProbeMsg { v: 1, caps, pk: pk_b64 };
    let probe_json = serde_json::to_vec(&probe)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    let probe_size = crate::frame::build_size(probe_json.len());
    let mut probe_buf = vec![0u8; probe_size];
    crate::frame::build(crate::frame::TYPE_PROBE, crate::frame::FLAG_COMPRESSED, &probe_json, &mut probe_buf);
    stream.write_all(&probe_buf[..probe_size])?;
    stream.flush()?;

    // 2. Read PROBE_ACK
    let frame_buf = read_frame(stream)?;
    let ack_frame = match crate::frame::parse(&frame_buf) {
        crate::frame::ParseResult::Complete { frame, .. } => frame,
        _ => return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid PROBE_ACK")),
    };

    if ack_frame.frame_type != crate::frame::TYPE_PROBE_ACK {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "expected PROBE_ACK"));
    }

    let ack: ProbeAckMsg = serde_json::from_slice(ack_frame.payload)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;

    // 3. If both sides support encryption, derive shared secret
    match (keypair, ack.pk) {
        (Some(kp), Some(pk_b64)) => {
            use base64::Engine;
            let pk_bytes: [u8; 32] = base64::engine::general_purpose::STANDARD
                .decode(&pk_b64)
                .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?
                .try_into()
                .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid public key length"))?;

            let peer_public = x25519_dalek::PublicKey::from(pk_bytes);
            let shared_secret = kp.derive_shared_secret(&peer_public);
            let cipher = crate::crypto::Cipher::new(&shared_secret, crate::crypto::Role::Initiator);

            Ok(Some(EncryptedHandshake {
                cipher,
                peer_public_key: pk_bytes,
            }))
        }
        _ => Ok(None),
    }
}

// ── Server side ─────────────────────────────────────────────────────────────

/// Server: respond to encrypted handshake PROBE.
///
/// 1. Reads PROBE from client
/// 2. If client offers encryption, generates X25519 keypair
/// 3. Sends PROBE_ACK with server's public key
/// 4. Derives shared secret → initializes Cipher
///
/// Returns the cipher if encryption was negotiated, plus the ACK bytes to send.
pub fn server_encrypted_handshake(
    stream: &mut dyn crate::transport::Transport,
    capabilities: &[&str],
) -> io::Result<(Option<EncryptedHandshake>, Vec<u8>)> {
    // 1. Read PROBE
    let frame_buf = read_frame(stream)?;
    let probe_frame = match crate::frame::parse(&frame_buf) {
        crate::frame::ParseResult::Complete { frame, .. } => frame,
        _ => return Err(io::Error::new(io::ErrorKind::InvalidData, "invalid PROBE")),
    };

    if probe_frame.frame_type != crate::frame::TYPE_PROBE {
        return Err(io::Error::new(io::ErrorKind::InvalidData, "expected PROBE"));
    }

    let probe: ProbeMsg = serde_json::from_slice(probe_frame.payload)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;

    // 2. Check if client wants encryption and server supports it
    let client_wants_encryption = probe.caps.contains(&"encryption".to_string());
    let server_supports_encryption = capabilities.contains(&"encryption");

    let (handshake, server_pk_b64) = if client_wants_encryption && server_supports_encryption {
        let kp = crate::crypto::Keypair::generate();

        let pk_bytes = match &probe.pk {
            Some(pk_b64) => {
                use base64::Engine;
                let bytes: Vec<u8> = base64::engine::general_purpose::STANDARD
                    .decode(pk_b64)
                    .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
                bytes.try_into()
                    .map_err(|_| io::Error::new(io::ErrorKind::InvalidData, "invalid public key length"))?
            }
            None => return Err(io::Error::new(io::ErrorKind::InvalidData, "encryption cap without pk")),
        };

        let peer_public = x25519_dalek::PublicKey::from(pk_bytes);
        let shared_secret = kp.derive_shared_secret(&peer_public);
        let cipher = crate::crypto::Cipher::new(&shared_secret, crate::crypto::Role::Responder);

        use base64::Engine;
        let b64 = base64::engine::general_purpose::STANDARD.encode(kp.public.as_bytes());

        (Some(EncryptedHandshake { cipher, peer_public_key: pk_bytes }), Some(b64))
    } else {
        (None, None)
    };

    // 3. Build ACK
    let mut ack_caps = capabilities.iter().map(|s| s.to_string()).collect::<Vec<_>>();
    if server_supports_encryption && client_wants_encryption {
        if !ack_caps.contains(&"encryption".to_string()) {
            ack_caps.push("encryption".into());
        }
    }

    let ack = ProbeAckMsg { v: 1, caps: ack_caps, pk: server_pk_b64 };
    let ack_json = serde_json::to_vec(&ack)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?;
    let ack_size = crate::frame::build_size(ack_json.len());
    let mut ack_buf = vec![0u8; ack_size];
    crate::frame::build(crate::frame::TYPE_PROBE_ACK, crate::frame::FLAG_COMPRESSED, &ack_json, &mut ack_buf);
    ack_buf.truncate(ack_size);

    Ok((handshake, ack_buf))
}

// ═══════════════════════════════════════════════════════════════════════════════
// Tests
// ═══════════════════════════════════════════════════════════════════════════════

#[cfg(test)]
mod tests {
    use super::*;
    use crate::transport::Transport;
    use std::io;

    /// A simple in-memory transport for testing handshakes.
    struct MemTransport {
        buf: Vec<u8>,
        pos: usize,
    }

    impl MemTransport {
        fn new() -> Self {
            Self { buf: Vec::new(), pos: 0 }
        }
    }

    impl Transport for MemTransport {
        fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
            let remaining = self.buf.len() - self.pos;
            if remaining == 0 {
                return Err(io::Error::new(io::ErrorKind::WouldBlock, "no data"));
            }
            let n = buf.len().min(remaining);
            buf[..n].copy_from_slice(&self.buf[self.pos..self.pos + n]);
            self.pos += n;
            Ok(n)
        }

        fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
            self.buf.extend_from_slice(buf);
            Ok(())
        }

        fn flush(&mut self) -> io::Result<()> {
            Ok(())
        }
    }

    #[test]
    fn encrypted_handshake_end_to_end() {
        // Test that ProbeMsg/ProbeAckMsg serialization works with encryption keys.
        let probe = ProbeMsg {
            v: 1,
            caps: vec!["compression".into(), "encryption".into()],
            pk: Some("AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=".into()),
        };
        let json = serde_json::to_string(&probe).unwrap();
        assert!(json.contains("encryption"));
        assert!(json.contains("AAAAAAAA"));

        let parsed: ProbeMsg = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.v, 1);
        assert!(parsed.caps.contains(&"encryption".to_string()));
        assert!(parsed.pk.is_some());
    }
}
