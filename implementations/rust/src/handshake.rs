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
    let mut buf = [0u8; 4096];
    let n = stream.read(&mut buf)?;
    let frame = match frame::parse(&buf[..n]) {
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
    let mut buf = [0u8; 4096];
    let n = stream.read(&mut buf)?;
    let ack_frame = match frame::parse(&buf[..n]) {
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
