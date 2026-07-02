//! Integration tests for LUMEN Level 2 (Shared Memory Transport).

use lumen::shm::{RingSide, ShmRegion};
use lumen::transport::{ShmTransport, Transport};

// ── Round-trip test (same process, two sides) ───────────────────────────────

#[test]
fn shm_roundtrip_single_frame() {
    // Server creates the region
    let server_region =
        ShmRegion::create(Some("test-roundtrip-1"), None).expect("create shm region");
    server_region.init_header();

    // Client opens the same region
    let client_region = ShmRegion::open("test-roundtrip-1", None).expect("open shm region");
    assert!(client_region.validate());

    // Server: writes on Ring B, reads from Ring A
    let mut server = ShmTransport::new(
        server_region.ring_buffer(RingSide::B), // write ring
        server_region.ring_buffer(RingSide::A), // read ring
    );

    // Client: writes on Ring A, reads from Ring B
    let mut client = ShmTransport::new(
        client_region.ring_buffer(RingSide::A), // write ring
        client_region.ring_buffer(RingSide::B), // read ring
    );

    // Client writes a frame
    let msg = b"hello world from client";
    client.write_all(msg).expect("client write");
    client.flush().expect("client flush");

    // Server reads the frame
    let mut buf = [0u8; 256];
    let n = server.read(&mut buf).expect("server read");
    assert_eq!(&buf[..n], msg);

    // Server writes a response
    let resp = b"ack from server";
    server.write_all(resp).expect("server write");
    server.flush().expect("server flush");

    // Client reads the response
    let mut buf2 = [0u8; 256];
    let n2 = client.read(&mut buf2).expect("client read");
    assert_eq!(&buf2[..n2], resp);

    // Regions drop AFTER the transports (reverse declaration order), so the
    // mapping outlives every ring-buffer pointer and the server-side Drop
    // runs shm_unlink — leaking the object would break the next test run
    // with EEXIST (POSIX shm persists until unlink or reboot).
}

// ── Multiple frames ─────────────────────────────────────────────────────────

#[test]
fn shm_multiple_frames() {
    let server_region = ShmRegion::create(Some("test-multi"), None).expect("create");
    server_region.init_header();
    let client_region = ShmRegion::open("test-multi", None).expect("open");

    let mut server = ShmTransport::new(
        server_region.ring_buffer(RingSide::B),
        server_region.ring_buffer(RingSide::A),
    );
    let mut client = ShmTransport::new(
        client_region.ring_buffer(RingSide::A),
        client_region.ring_buffer(RingSide::B),
    );

    let messages: Vec<Vec<u8>> = (0..10)
        .map(|i| format!("frame {}", i).into_bytes())
        .collect();

    // Interleave writes and reads — avoids ring-full deadlocks
    // and tests the real streaming use case.
    let mut buf = [0u8; 256];
    for expected in &messages {
        client.write_all(expected).expect("write");
        client.flush().expect("flush");
        let n = server.read(&mut buf).expect("read");
        assert_eq!(&buf[..n], expected.as_slice());
    }

    // Verify no extra data — read_frame returns Err when ring empty.
    assert!(server.read(&mut buf).is_err());
}

// ── Large frame (bigger than ring capacity would allow in one shot) ─────────

#[test]
fn shm_large_frame() {
    let server_region = ShmRegion::create(Some("test-large"), None).expect("create");
    server_region.init_header();
    let client_region = ShmRegion::open("test-large", None).expect("open");

    let mut server = ShmTransport::new(
        server_region.ring_buffer(RingSide::B),
        server_region.ring_buffer(RingSide::A),
    );
    let mut client = ShmTransport::new(
        client_region.ring_buffer(RingSide::A),
        client_region.ring_buffer(RingSide::B),
    );

    // Ring A capacity is ~256 KiB, send a 64 KiB frame (well within capacity)
    let large_msg = vec![0xABu8; 64 * 1024]; // 64 KiB
    client.write_all(&large_msg).expect("write");
    client.flush().expect("flush");

    let mut buf = vec![0u8; 128 * 1024];
    let n = server.read(&mut buf).expect("read");
    assert_eq!(n, large_msg.len());
    assert_eq!(&buf[..n], &large_msg[..]);
}

// ── Handshake test ──────────────────────────────────────────────────────────

/// Verifies the transport-negotiation frame types.
///
/// A full handshake integration test would need separate processes; the
/// protocol serialization itself is covered by the handshake unit tests.
#[test]
fn handshake_mmap_negotiation() {
    assert_eq!(lumen::frame::TYPE_TRANSPORT_INIT, 0x0B);
    assert_eq!(lumen::frame::TYPE_TRANSPORT_ACK, 0x0C);
}
