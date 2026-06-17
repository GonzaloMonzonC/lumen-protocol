//! LUMEN Transport Abstraction (LTA).
//!
//! ## Transport levels
//!
//! | Level | Name       | Requirements                          |
//! |-------|------------|---------------------------------------|
//! | 1     | Stream     | Ordered, lossless, full-duplex        |
//! | 2     | Zero-Copy  | Level 1 + shared memory (mmap)        |
//! | 3     | Datagram   | Unordered, best-effort (experimental) |
//!
//! ## Design
//!
//! LUMEN frames are self-delimiting via Hyb128, so they work over any
//! reliable byte stream without additional framing layers (no HTTP,
//! no WebSocket framing required — though WebSocket can be used as
//! a transport if needed).
//!
//! ## Recommended profiles
//!
//! - **Local-first (IPC)**: Unix Domain Sockets / named pipes + optional mmap.
//! - **Web / Edge**: WebSocket binary frames.
//! - **Embedded**: stdio pipes (same as MCP today).

use std::io;

/// Minimal transport trait that any LUMEN transport must implement.
///
/// This is deliberately simple — the protocol handles its own framing.
pub trait Transport: Send + Sync {
    /// Read bytes into `buf`. Returns number of bytes read.
    /// Returns `Ok(0)` on clean EOF.
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize>;

    /// Write all of `buf` to the transport.
    fn write_all(&mut self, buf: &[u8]) -> io::Result<()>;

    /// Flush any buffered writes.
    fn flush(&mut self) -> io::Result<()>;
}

// ── Built-in transports ─────────────────────────────────────────────────────

/// Stdio transport (stdin + stdout) — same as MCP's default transport.
pub struct StdioTransport;

impl Transport for StdioTransport {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        use std::io::Read;
        std::io::stdin().read(buf)
    }

    fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
        use std::io::Write;
        std::io::stdout().write_all(buf)
    }

    fn flush(&mut self) -> io::Result<()> {
        use std::io::Write;
        std::io::stdout().flush()
    }
}

// ── Level 2: Shared Memory Transport ────────────────────────────────────────

/// Zero-copy shared memory transport (LTA Level 2).
///
/// Uses two unidirectional ring buffers in a single shared memory region:
/// - Write ring: this side writes frames (length-prefixed)
/// - Read ring: this side reads frames (length-prefixed)
///
/// Each `write_all` call writes exactly one frame with a 4-byte LE length
/// prefix. Each `read` call reads bytes from the current buffered frame
/// (or pulls the next frame from the ring if the buffer is exhausted).
///
/// Owns a per-connection [`SessionDict`] for session-dictionary compression.
pub struct ShmTransport {
    /// Ring we write to
    write_ring: crate::shm::ShmRingBuffer,
    /// Ring we read from
    read_ring: crate::shm::ShmRingBuffer,
    /// Buffered frame being read (data + current position)
    read_buf: Vec<u8>,
    read_pos: usize,
    /// Per-connection session dictionary for compression
    pub session_dict: crate::dict::SessionDict,
}

impl ShmTransport {
    /// Create a new shared memory transport.
    ///
    /// `write_ring` is the ring this side writes into (Ring A for client,
    /// Ring B for server). `read_ring` is the ring this side reads from.
    pub fn new(write_ring: crate::shm::ShmRingBuffer, read_ring: crate::shm::ShmRingBuffer) -> Self {
        Self {
            write_ring,
            read_ring,
            read_buf: Vec::new(),
            read_pos: 0,
            session_dict: crate::dict::SessionDict::new(),
        }
    }

    /// Check if there's data available without blocking.
    pub fn has_data(&self) -> bool {
        self.read_pos < self.read_buf.len() || self.read_ring.available() > 0
    }
}

impl Transport for ShmTransport {
    fn read(&mut self, buf: &mut [u8]) -> io::Result<usize> {
        // Serve from buffered frame first
        if self.read_pos < self.read_buf.len() {
            let remaining = &self.read_buf[self.read_pos..];
            let n = remaining.len().min(buf.len());
            buf[..n].copy_from_slice(&remaining[..n]);
            self.read_pos += n;
            return Ok(n);
        }

        // Pull next frame from the ring
        let mut frame = Vec::new();
        match self.read_ring.read_frame(&mut frame) {
            Ok(_len) => {
                self.read_buf = frame;
                self.read_pos = 0;
                let n = self.read_buf.len().min(buf.len());
                buf[..n].copy_from_slice(&self.read_buf[..n]);
                self.read_pos = n;
                Ok(n)
            }
            Err(e) => {
                // Timeout or no frame available
                Err(io::Error::from(e))
            }
        }
    }

    fn write_all(&mut self, buf: &[u8]) -> io::Result<()> {
        self.write_ring.write_frame(buf).map_err(io::Error::from)
    }

    fn flush(&mut self) -> io::Result<()> {
        // Ring buffer writes are immediate — no userspace buffering
        Ok(())
    }
}
