//! LUMEN frame types, constants, and parsing.
//!
//! ## Frame layout
//!
//! ```text
//! ┌──────────────────────────────────────────────────────┐
//! │ [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]     │
//! └──────────────────────────────────────────────────────┘
//! ```
//!
//! Overhead: 3-7 bytes (Hyb128 length + 2 fixed bytes).

use crate::hyb128::{self, Decoded};

// ── Frame type constants ────────────────────────────────────────────────────

/// Request: client asks server to perform an operation.
pub const TYPE_REQUEST: u8 = 0x01;
/// Response: server replies to a request.
pub const TYPE_RESPONSE: u8 = 0x02;
/// Notification: fire-and-forget message (no response expected).
pub const TYPE_NOTIFY: u8 = 0x03;
/// Stream data chunk (after STREAM_INIT).
pub const TYPE_STREAM_DATA: u8 = 0x04;
/// Schema delta update (add/remove tools, resources, prompts).
pub const TYPE_SCHEMA_PATCH: u8 = 0x05;
/// Initialize a token/element stream.
pub const TYPE_STREAM_INIT: u8 = 0x06;
/// Dictionary synchronization frame.
pub const TYPE_DICT_SYNC: u8 = 0x07;
/// Dynamic discovery / introspection request.
pub const TYPE_DISCOVER: u8 = 0x08;
/// Multiplex wrapper (carries another frame on a logical channel).
pub const TYPE_MUX: u8 = 0x09;
/// Heartbeat / keep-alive.
pub const TYPE_HEARTBEAT: u8 = 0x0A;

// ── Transport negotiation (LTA Level 2) ─────────────────────────────────────

/// Transport capability negotiation init (client → server).
pub const TYPE_TRANSPORT_INIT: u8 = 0x0B;
/// Transport capability negotiation ack (server → client).
pub const TYPE_TRANSPORT_ACK: u8 = 0x0C;

// ── Flag constants ──────────────────────────────────────────────────────────

pub const FLAG_COMPRESSED: u8 = 0x01;
pub const FLAG_ENCRYPTED: u8 = 0x02;
pub const FLAG_PRIORITY: u8 = 0x04;
pub const FLAG_FRAGMENTED: u8 = 0x08;

// ── Frame struct ────────────────────────────────────────────────────────────

/// A parsed LUMEN frame header + payload reference.
///
/// The payload is borrowed from the original buffer for zero-copy operation.
#[derive(Debug, Clone)]
pub struct Frame<'a> {
    /// Frame type (see `TYPE_*` constants).
    pub frame_type: u8,
    /// Bitmask of `FLAG_*`.
    pub flags: u8,
    /// Payload slice pointing into the original buffer.
    pub payload: &'a [u8],
}

// ── Builder ─────────────────────────────────────────────────────────────────

/// Builds a LUMEN frame into a byte buffer.
///
/// Returns the number of bytes written. Panics if the buffer is too small.
pub fn build(frame_type: u8, flags: u8, payload: &[u8], buf: &mut [u8]) -> usize {
    let header_len = hyb128::encoded_len(payload.len() as u64);
    let total = header_len + 2 + payload.len();

    let n = hyb128::encode(payload.len() as u64, buf);
    buf[n] = frame_type;
    buf[n + 1] = flags;
    buf[n + 2..n + 2 + payload.len()].copy_from_slice(payload);

    total
}

/// Returns the total buffer size needed for `build()` with these parameters.
pub fn build_size(payload_len: usize) -> usize {
    hyb128::encoded_len(payload_len as u64) + 2 + payload_len
}

// ── Parser ──────────────────────────────────────────────────────────────────

/// Result of attempting to parse one frame from a byte buffer.
#[derive(Debug)]
pub enum ParseResult<'a> {
    /// A complete frame was parsed.
    Complete {
        /// The parsed frame.
        frame: Frame<'a>,
        /// Number of bytes consumed from the input.
        consumed: usize,
    },
    /// More bytes are needed to complete the frame header.
    Incomplete,
    /// Frame header parsed but payload is incomplete (need more data).
    IncompletePayload {
        /// Expected total frame size in bytes.
        expected: usize,
        /// How many bytes we have so far.
        available: usize,
    },
    /// The frame data is malformed.
    Error(&'static str),
}

/// Attempts to parse one LUMEN frame from `bytes`.
///
/// On success, returns `ParseResult::Complete` with the frame and how many
/// bytes were consumed. The remaining bytes (if any) can be fed back on the
/// next call — this enables streaming parsing over TCP/UDS/stdio.
pub fn parse(bytes: &[u8]) -> ParseResult<'_> {
    if bytes.is_empty() {
        return ParseResult::Incomplete;
    }

    // 1. Decode the Hyb128 length
    let Decoded {
        value: payload_len,
        header_len: len_header,
    } = match hyb128::decode(bytes) {
        Some(d) => d,
        None => return ParseResult::Incomplete,
    };

    // 2. Read TYPE and FLAGS
    let type_offset = len_header;
    let flags_offset = len_header + 1;
    let payload_offset = len_header + 2;

    if bytes.len() <= flags_offset {
        return ParseResult::Incomplete;
    }

    let frame_type = bytes[type_offset];
    let flags = bytes[flags_offset];

    // 3. Verify payload length
    let payload_len = payload_len as usize;
    let total_len = payload_offset + payload_len;

    if bytes.len() < total_len {
        return ParseResult::IncompletePayload {
            expected: total_len,
            available: bytes.len(),
        };
    }

    // 4. Extract payload (zero-copy slice)
    let payload = &bytes[payload_offset..total_len];

    ParseResult::Complete {
        frame: Frame {
            frame_type,
            flags,
            payload,
        },
        consumed: total_len,
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

impl<'a> Frame<'a> {
    /// Returns a human-readable name for this frame's type.
    pub fn type_name(&self) -> &'static str {
        match self.frame_type {
            TYPE_REQUEST => "REQUEST",
            TYPE_RESPONSE => "RESPONSE",
            TYPE_NOTIFY => "NOTIFY",
            TYPE_STREAM_DATA => "STREAM_DATA",
            TYPE_SCHEMA_PATCH => "SCHEMA_PATCH",
            TYPE_STREAM_INIT => "STREAM_INIT",
            TYPE_DICT_SYNC => "DICT_SYNC",
            TYPE_DISCOVER => "DISCOVER",
            TYPE_MUX => "MUX",
            TYPE_HEARTBEAT => "HEARTBEAT",
            TYPE_TRANSPORT_INIT => "TRANSPORT_INIT",
            TYPE_TRANSPORT_ACK => "TRANSPORT_ACK",
            _ => "UNKNOWN",
        }
    }

    pub fn is_compressed(&self) -> bool {
        self.flags & FLAG_COMPRESSED != 0
    }

    pub fn is_encrypted(&self) -> bool {
        self.flags & FLAG_ENCRYPTED != 0
    }

    pub fn is_priority(&self) -> bool {
        self.flags & FLAG_PRIORITY != 0
    }

    pub fn is_fragmented(&self) -> bool {
        self.flags & FLAG_FRAGMENTED != 0
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn build_and_parse_roundtrip() {
        let payload = b"{\"method\":\"tools/list\"}";
        let mut buf = vec![0u8; build_size(payload.len())];

        let n = build(TYPE_REQUEST, FLAG_PRIORITY, payload, &mut buf);

        match parse(&buf[..n]) {
            ParseResult::Complete { frame, consumed } => {
                assert_eq!(consumed, n);
                assert_eq!(frame.frame_type, TYPE_REQUEST);
                assert!(frame.is_priority());
                assert!(!frame.is_compressed());
                assert_eq!(frame.payload, payload);
                assert_eq!(frame.type_name(), "REQUEST");
            }
            other => panic!("unexpected parse result: {:?}", other),
        }
    }

    #[test]
    fn parse_empty() {
        assert!(matches!(parse(&[]), ParseResult::Incomplete));
    }

    #[test]
    fn parse_smallest_valid_frame() {
        // Empty payload, mode 00
        let mut buf = [0u8; 3];
        let n = build(TYPE_HEARTBEAT, 0, b"", &mut buf);
        assert_eq!(n, 3); // 1 (hyb128) + 1 (type) + 1 (flags)
        assert!(matches!(parse(&buf[..n]), ParseResult::Complete { .. }));
    }

    #[test]
    fn parse_incomplete_payload() {
        let payload = vec![0xAA; 200];
        let mut buf = vec![0u8; build_size(payload.len())];
        let n = build(TYPE_STREAM_DATA, 0, &payload, &mut buf);

        // Feed only half the frame
        match parse(&buf[..n / 2]) {
            ParseResult::IncompletePayload { expected, .. } => {
                assert_eq!(expected, n);
            }
            other => panic!("expected IncompletePayload, got {:?}", other),
        }
    }

    #[test]
    fn stream_parsing_multiple_frames() {
        let mut buf = Vec::new();
        let mut tmp = vec![0u8; 1024];

        // Build 3 frames back-to-back
        for i in 0u8..3 {
            let payload = vec![i; 50];
            let size = build_size(payload.len());
            tmp.resize(size, 0);
            let n = build(TYPE_NOTIFY, 0, &payload, &mut tmp);
            buf.extend_from_slice(&tmp[..n]);
        }

        // Parse them sequentially
        let mut offset = 0;
        let mut count = 0;
        while offset < buf.len() {
            match parse(&buf[offset..]) {
                ParseResult::Complete { frame, consumed } => {
                    assert_eq!(frame.frame_type, TYPE_NOTIFY);
                    assert_eq!(frame.payload.len(), 50);
                    assert_eq!(frame.payload[0], count);
                    offset += consumed;
                    count += 1;
                }
                other => panic!("unexpected: {:?}", other),
            }
        }
        assert_eq!(count, 3);
    }

    #[test]
    fn frame_overhead_small_payload() {
        // Payload <= 63 bytes → 1 byte Hyb128 + 2 fixed = 3 bytes overhead
        let overhead = build_size(42) - 42;
        assert_eq!(overhead, 3);
    }

    #[test]
    fn build_size_consistency() {
        for pl in [0, 1, 63, 64, 1000, 65535, 65536] {
            let payload = vec![0xCC; pl];
            let mut buf = vec![0u8; build_size(pl)];
            let n = build(TYPE_RESPONSE, 0, &payload, &mut buf);
            assert_eq!(n, build_size(pl));
        }
    }
}
