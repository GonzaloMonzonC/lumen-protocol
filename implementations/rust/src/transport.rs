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
