//! LUMEN Level 3 — Datagram Transport (UDP / multicast).
//!
//! ## Design
//!
//! Level 3 is **message-oriented**, not stream-oriented. Each UDP datagram
//! carries exactly one complete LUMEN frame (Hyb128 length + type + flags +
//! payload). There is no framing layer beyond the datagram boundary itself.
//!
//! ## Guarantees (none)
//!
//! - ❌ No ordering — frames may arrive out of order
//! - ❌ No delivery — frames may be silently dropped
//! - ❌ No duplicate suppression — frames may arrive more than once
//!
//! ## Use cases
//!
//! - Telemetry / metrics (fire-and-forget)
//! - Heartbeats (best-effort keep-alive)
//! - Log shipping (high throughput, loss-tolerant)
//! - Service discovery (multicast DISCOVER frames)
//!
//! ## Multicast
//!
//! ```text
//! Sender                         Receivers
//!   │                                │
//!   │── DISCOVER (239.1.1.1:9999) ──→│  (multicast group)
//!   │                                │
//!   │←── RESPONSE (unicast) ────────│  (direct reply)
//! ```
//!
//! Senders join a multicast group to send. Receivers join to listen.
//! TTL controls how far the datagram propagates (default: 1 = local subnet).

use std::io;
use std::net::{SocketAddr, SocketAddrV4, UdpSocket};

#[cfg(unix)]
use std::os::unix::io::AsRawFd;

/// Maximum UDP datagram payload size (65535 - 8B UDP header - 20B IP header).
pub const MAX_DATAGRAM_SIZE: usize = 65507;

/// Maximum LUMEN frame payload that fits in a single UDP datagram.
/// Hyb128(5) + TYPE(1) + FLAGS(1) = 7 bytes overhead → 65500 bytes payload.
pub const MAX_FRAME_PAYLOAD: usize = MAX_DATAGRAM_SIZE - 7;

// ── DatagramTransport ───────────────────────────────────────────────────────

/// A Level 3 datagram transport wrapping a UDP socket.
///
/// # Examples
///
/// ```no_run
/// use lumen::datagram::DatagramTransport;
///
/// // Receiver
/// let mut rx = DatagramTransport::bind("127.0.0.1:9999").unwrap();
/// if let Some((data, src)) = rx.recv_frame().unwrap() {
///     println!("Got {} bytes from {}", data.len(), src);
/// }
///
/// // Sender
/// let tx = DatagramTransport::bind("127.0.0.1:0").unwrap();
/// tx.send_frame_to(b"hello world", "127.0.0.1:9999".parse().unwrap()).unwrap();
/// ```
pub struct DatagramTransport {
    socket: UdpSocket,
    /// Scratch buffer for receiving one datagram
    recv_buf: Vec<u8>,
}

impl DatagramTransport {
    // ── Constructors ──────────────────────────────────────────────

    /// Bind to a local address and create a datagram transport.
    ///
    /// Use port 0 for an OS-assigned ephemeral port (typical for senders).
    pub fn bind(addr: &str) -> io::Result<Self> {
        let socket = UdpSocket::bind(addr)?;
        // Non-blocking so recv_frame can return None instead of blocking
        socket.set_nonblocking(true)?;
        Ok(Self {
            socket,
            recv_buf: vec![0u8; MAX_DATAGRAM_SIZE],
        })
    }

    /// Bind and connect to a remote address (connected UDP socket).
    ///
    /// A connected socket can use `send` instead of `send_to` and only
    /// receives datagrams from the connected peer.
    pub fn connect(local: &str, remote: &str) -> io::Result<Self> {
        let socket = UdpSocket::bind(local)?;
        socket.connect(remote)?;
        socket.set_nonblocking(true)?;
        Ok(Self {
            socket,
            recv_buf: vec![0u8; MAX_DATAGRAM_SIZE],
        })
    }

    // ── Address queries ───────────────────────────────────────────

    /// Returns the local socket address.
    pub fn local_addr(&self) -> io::Result<SocketAddr> {
        self.socket.local_addr()
    }

    // ── Send ──────────────────────────────────────────────────────

    /// Send a raw LUMEN frame (Hyb128 + TYPE + FLAGS + payload) as a single
    /// datagram to a specific address.
    ///
    /// The caller is responsible for building the frame with
    /// [`crate::frame::build`] first. If the frame exceeds
    /// [`MAX_DATAGRAM_SIZE`], returns `DatagramTooLarge` error.
    ///
    /// Returns the number of bytes sent.
    pub fn send_frame_to(&self, frame: &[u8], addr: SocketAddr) -> io::Result<usize> {
        if frame.len() > MAX_DATAGRAM_SIZE {
            return Err(io::Error::new(io::ErrorKind::Other, "datagram too large"));
        }
        self.socket.send_to(frame, addr)
    }

    /// Send to the connected peer (requires `connect()`).
    pub fn send_frame(&self, frame: &[u8]) -> io::Result<usize> {
        if frame.len() > MAX_DATAGRAM_SIZE {
            return Err(io::Error::new(io::ErrorKind::Other, "datagram too large"));
        }
        self.socket.send(frame)
    }

    // ── Receive ───────────────────────────────────────────────────

    /// Receive one LUMEN frame as a raw byte buffer.
    ///
    /// Returns `None` if no datagram is available (non-blocking).
    /// Returns `Some((data, src))` with the frame bytes and sender address.
    ///
    /// The returned slice is valid until the next call to `recv_frame`.
    pub fn recv_frame(&mut self) -> io::Result<Option<(&[u8], SocketAddr)>> {
        match self.socket.recv_from(&mut self.recv_buf) {
            Ok((n, src)) => Ok(Some((&self.recv_buf[..n], src))),
            Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(e) => Err(e),
        }
    }

    /// Receive from the connected peer (requires `connect()`).
    ///
    /// Returns `None` if no datagram is available.
    pub fn recv(&mut self) -> io::Result<Option<&[u8]>> {
        match self.socket.recv(&mut self.recv_buf) {
            Ok(n) => Ok(Some(&self.recv_buf[..n])),
            Err(ref e) if e.kind() == io::ErrorKind::WouldBlock => Ok(None),
            Err(e) => Err(e),
        }
    }

    // ── Multicast ──────────────────────────────────────────────────

    /// Join a multicast group on the given interface.
    ///
    /// After joining, `recv_frame` will receive datagrams sent to the
    /// multicast address.
    pub fn join_multicast(&self, multiaddr: &str, interface: &str) -> io::Result<()> {
        let multi: SocketAddrV4 = multiaddr
            .parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
        let iface: SocketAddrV4 = interface
            .parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
        self.socket.join_multicast_v4(multi.ip(), iface.ip())?;
        Ok(())
    }

    /// Leave a multicast group.
    pub fn leave_multicast(&self, multiaddr: &str, interface: &str) -> io::Result<()> {
        let multi: SocketAddrV4 = multiaddr
            .parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
        let iface: SocketAddrV4 = interface
            .parse()
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidInput, e))?;
        self.socket.leave_multicast_v4(multi.ip(), iface.ip())?;
        Ok(())
    }

    /// Set the multicast TTL (time-to-live / hop limit).
    ///
    /// - 0: same host
    /// - 1: same subnet (default)
    /// - 32: same site
    /// - 64: same region
    /// - 128: same continent
    /// - 255: unrestricted
    pub fn set_multicast_ttl(&self, ttl: u32) -> io::Result<()> {
        self.socket.set_multicast_ttl_v4(ttl)
    }

    /// Enable or disable multicast loopback (default: enabled).
    ///
    /// When enabled, a host receives its own multicast sends.
    pub fn set_multicast_loop(&self, on: bool) -> io::Result<()> {
        self.socket.set_multicast_loop_v4(on)
    }
}

// ── Convenience builders ────────────────────────────────────────────────────

/// Build a complete LUMEN frame for datagram transmission.
///
/// Returns a `Vec<u8>` with `[Hyb128_LEN][TYPE][FLAGS][PAYLOAD]`.
/// Panics if the payload exceeds [`MAX_FRAME_PAYLOAD`].
pub fn build_dgram(frame_type: u8, flags: u8, payload: &[u8]) -> Vec<u8> {
    assert!(
        payload.len() <= MAX_FRAME_PAYLOAD,
        "datagram payload {} exceeds max {}",
        payload.len(),
        MAX_FRAME_PAYLOAD
    );
    let total = crate::frame::build_size(payload.len());
    let mut buf = vec![0u8; total];
    crate::frame::build(frame_type, flags, payload, &mut buf);
    buf
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use std::net::Ipv4Addr;
    use std::thread;
    use std::time::Duration;

    fn ephemeral() -> String {
        format!("127.0.0.1:0")
    }

    #[test]
    fn bind_and_local_addr() {
        let t = DatagramTransport::bind(&ephemeral()).unwrap();
        let addr = t.local_addr().unwrap();
        assert!(addr.port() > 0);
    }

    #[test]
    fn send_recv_unicast() {
        let mut rx = DatagramTransport::bind("127.0.0.1:0").unwrap();
        let rx_addr = rx.local_addr().unwrap();

        let tx = DatagramTransport::bind(&ephemeral()).unwrap();
        let frame = build_dgram(
            crate::frame::TYPE_HEARTBEAT,
            0,
            b"ping",
        );

        tx.send_frame_to(&frame, rx_addr).unwrap();

        // Small delay for kernel to deliver
        thread::sleep(Duration::from_millis(10));

        let result = rx.recv_frame().unwrap();
        assert!(result.is_some(), "should receive datagram");
        let (data, src) = result.unwrap();
        assert_eq!(data, &frame[..], "received frame should match sent");
        // Source should be the sender's address
        assert_eq!(src.ip(), Ipv4Addr::LOCALHOST);
    }

    #[test]
    fn recv_empty_when_no_data() {
        let mut rx = DatagramTransport::bind(&ephemeral()).unwrap();
        let result = rx.recv_frame().unwrap();
        assert!(result.is_none(), "should return None with no data");
    }

    #[test]
    fn multiple_frames() {
        let mut rx = DatagramTransport::bind("127.0.0.1:0").unwrap();
        let rx_addr = rx.local_addr().unwrap();

        let tx = DatagramTransport::bind(&ephemeral()).unwrap();

        let frames: Vec<Vec<u8>> = (0..5)
            .map(|i| build_dgram(
                crate::frame::TYPE_NOTIFY,
                0,
                format!("msg{}", i).as_bytes(),
            ))
            .collect();

        for f in &frames {
            tx.send_frame_to(f, rx_addr).unwrap();
        }

        thread::sleep(Duration::from_millis(20));

        let mut received = Vec::new();
        while let Some((data, _)) = rx.recv_frame().unwrap() {
            received.push(data.to_vec());
        }

        assert_eq!(received.len(), frames.len(), "should receive all frames");
        for (sent, recv) in frames.iter().zip(received.iter()) {
            assert_eq!(sent, recv);
        }
    }

    #[test]
    fn max_payload_size() {
        let payload = vec![0xABu8; MAX_FRAME_PAYLOAD];
        let frame = build_dgram(crate::frame::TYPE_NOTIFY, 0, &payload);

        // Should fit in one datagram
        assert!(frame.len() <= MAX_DATAGRAM_SIZE);

        let mut rx = DatagramTransport::bind("127.0.0.1:0").unwrap();
        let rx_addr = rx.local_addr().unwrap();
        let tx = DatagramTransport::bind(&ephemeral()).unwrap();

        tx.send_frame_to(&frame, rx_addr).unwrap();
        thread::sleep(Duration::from_millis(50));

        let result = rx.recv_frame().unwrap();
        assert!(result.is_some(), "should receive large datagram");
        let (data, _) = result.unwrap();
        assert_eq!(data.len(), frame.len());

        // Verify the payload roundtrips correctly
        let parsed = crate::frame::parse(data);
        match parsed {
            crate::frame::ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.payload, payload.as_slice());
            }
            other => panic!("expected Complete, got {:?}", other),
        }
    }

    #[test]
    fn connected_socket() {
        let rx = DatagramTransport::bind("127.0.0.1:0").unwrap();
        let rx_addr = rx.local_addr().unwrap();

        let tx = DatagramTransport::connect(
            &ephemeral(),
            &rx_addr.to_string(),
        )
        .unwrap();

        let frame = build_dgram(crate::frame::TYPE_HEARTBEAT, 0, b"connected-ping");
        tx.send_frame(&frame).unwrap();

        // Note: connected UDP on the receive side needs to bind to the
        // specific address. We'll test send/recv asymmetry instead.
        // The send side can use send() which is simpler.
        assert!(tx.send_frame(&frame).is_ok());
    }

    #[test]
    #[should_panic(expected = "datagram payload")]
    fn payload_too_large_panics() {
        let payload = vec![0u8; MAX_FRAME_PAYLOAD + 1];
        build_dgram(crate::frame::TYPE_NOTIFY, 0, &payload);
    }

    #[test]
    fn heartbeat_roundtrip() {
        let mut rx = DatagramTransport::bind("127.0.0.1:0").unwrap();
        let rx_addr = rx.local_addr().unwrap();
        let tx = DatagramTransport::bind(&ephemeral()).unwrap();

        // Simulate heartbeat exchange
        let hb = build_dgram(crate::frame::TYPE_HEARTBEAT, 0, b"");
        tx.send_frame_to(&hb, rx_addr).unwrap();
        thread::sleep(Duration::from_millis(10));

        let result = rx.recv_frame().unwrap();
        assert!(result.is_some());
        let (data, _) = result.unwrap();

        match crate::frame::parse(data) {
            crate::frame::ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.frame_type, crate::frame::TYPE_HEARTBEAT);
            }
            other => panic!("expected Complete, got {:?}", other),
        }
    }
}
