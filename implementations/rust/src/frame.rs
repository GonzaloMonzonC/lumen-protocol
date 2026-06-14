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

// ── Batching (vectored I/O) ─────────────────────────────────────────────────

/// Batch frame: carries multiple independent LUMEN frames in a single syscall.
///
/// ## Batch payload layout
///
/// ```text
/// [COUNT:2B LE] [FRAME_1: complete LUMEN frame] [FRAME_2: ...] ...
/// ```
///
/// Reduces syscall overhead for high-throughput scenarios (concurrent agents,
/// token bursts). The outer batch frame can itself carry FLAG_COMPRESSED or
/// FLAG_ENCRYPTED — in that case the *entire* batch payload (COUNT + inner
/// frames) is compressed/encrypted as a single blob.
pub const TYPE_BATCH: u8 = 0x0D;

/// Maximum number of frames in a single batch (u16::MAX).
pub const MAX_BATCH_FRAMES: usize = 65535;

/// Size of the batch count header in bytes (2-byte u16 LE).
const BATCH_COUNT_SIZE: usize = 2;

// ── Flow control (backpressure) ─────────────────────────────────────────────

/// Flow-control frame: pause or resume data flow on a stream or globally.
///
/// Uses `FLAG_FLOW_PAUSE` (0x01) to distinguish pause (set) from resume
/// (clear).  The frame type alone identifies this as flow-control, so the
/// flag overlap with `FLAG_COMPRESSED` is harmless — flow-control frames
/// are never compressed.
///
/// ## Payload layout
///
/// ```text
/// [STREAM_ID: 2B LE] [WINDOW: 4B LE]
/// ```
///
/// - `STREAM_ID = 0` → global (all streams).
/// - `STREAM_ID = 1..65535` → specific multiplexed stream.
/// - PAUSE: `WINDOW = 0` means "stop sending entirely".
/// - RESUME: `WINDOW = N` grants N bytes of credit.
pub const TYPE_FLOW_CTL: u8 = 0x0E;

/// Flag: when set on a `TYPE_FLOW_CTL` frame, it's a pause (stop/reduce
/// sending).  When clear, it's a resume (grant credit).
pub const FLAG_FLOW_PAUSE: u8 = 0x01;

/// Size of the flow-control payload in bytes (stream_id:2 + window:4).
const FLOW_CTL_PAYLOAD_SIZE: usize = 6;

/// Parsed flow-control payload.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct FlowCtl {
    /// `0` = global, `1..=65535` = specific stream.
    pub stream_id: u16,
    /// For pause: 0 = hard stop. For resume: new credit window in bytes.
    pub window: u32,
    /// `true` if this is a pause, `false` if resume.
    pub is_pause: bool,
}

// ── Protocol negotiation (handshake with optional key exchange) ─────────────

/// Protocol probe (negotiation handshake, may carry X25519 public key).
pub const TYPE_PROBE: u8 = 0x0F;
/// Protocol probe acknowledgement (may carry X25519 public key).
pub const TYPE_PROBE_ACK: u8 = 0x10;

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

// ── Batch builder ───────────────────────────────────────────────────────────

/// Calculates the total byte size of a batch payload containing `frames`.
///
/// Each `frame` must be a complete, valid LUMEN frame (as returned by
/// [`build`]). The returned size is the payload that goes inside the
/// outer batch frame, i.e. `BATCH_COUNT_SIZE + sum(frame.len())`.
pub fn batch_payload_size(frames: &[&[u8]]) -> usize {
    BATCH_COUNT_SIZE + frames.iter().map(|f| f.len()).sum::<usize>()
}

/// Builds a TYPE_BATCH frame carrying multiple inner frames.
///
/// Each inner frame must already be a complete LUMEN frame. The batch
/// overhead is 2 bytes (u16 LE count) plus the outer Hyb128+TYPE+FLAGS.
///
/// Returns the number of bytes written. Panics if `buf` is too small or
/// if `frames.len()` exceeds [`MAX_BATCH_FRAMES`].
pub fn build_batch(frames: &[&[u8]], flags: u8, buf: &mut [u8]) -> usize {
    assert!(
        frames.len() <= MAX_BATCH_FRAMES,
        "batch frame count {} exceeds MAX_BATCH_FRAMES ({})",
        frames.len(),
        MAX_BATCH_FRAMES
    );

    let payload_len = batch_payload_size(frames);
    let header_len = hyb128::encoded_len(payload_len as u64);
    let total = header_len + 2 + payload_len;
    assert!(buf.len() >= total, "buffer too small: need {total}, have {}", buf.len());

    // Write Hyb128 length header
    let n = hyb128::encode(payload_len as u64, buf);
    // Write TYPE + FLAGS
    buf[n] = TYPE_BATCH;
    buf[n + 1] = flags;

    // Write batch payload: COUNT (u16 LE) + inner frames
    let mut pos = n + 2;
    let count = frames.len() as u16;
    buf[pos] = count as u8;
    buf[pos + 1] = (count >> 8) as u8;
    pos += BATCH_COUNT_SIZE;

    for frame in frames {
        buf[pos..pos + frame.len()].copy_from_slice(frame);
        pos += frame.len();
    }

    total
}

// ── Batch parser ────────────────────────────────────────────────────────────

/// Parsed batch inner frames — zero-copy views into the batch payload.
#[derive(Debug, Clone)]
pub struct BatchFrames<'a> {
    /// The number of inner frames declared in the batch header.
    pub declared_count: u16,
    /// Parsed inner frames. May be fewer than `declared_count` if the
    /// payload was truncated (caller should validate).
    pub frames: Vec<Frame<'a>>,
    /// Whether the payload appeared truncated.
    pub truncated: bool,
}

/// Parse the payload of a TYPE_BATCH frame into individual inner frames.
///
/// The `payload` slice should be the raw payload of a frame whose
/// `frame_type == TYPE_BATCH`. Returns zero-copy [`Frame`] views.
pub fn parse_batch_payload(payload: &[u8]) -> Option<BatchFrames<'_>> {
    if payload.len() < BATCH_COUNT_SIZE {
        return None;
    }

    let count = u16::from_le_bytes([payload[0], payload[1]]) as usize;
    let mut pos = BATCH_COUNT_SIZE;
    let mut frames = Vec::with_capacity(count.min(256));
    let mut truncated = false;

    for _ in 0..count {
        if pos >= payload.len() {
            truncated = true;
            break;
        }

        match parse(&payload[pos..]) {
            ParseResult::Complete { frame, consumed } => {
                frames.push(frame);
                pos += consumed;
            }
            ParseResult::Incomplete | ParseResult::IncompletePayload { .. } => {
                truncated = true;
                break;
            }
            ParseResult::Error(_) => {
                // Malformed inner frame — stop parsing
                truncated = true;
                break;
            }
        }
    }

    Some(BatchFrames {
        declared_count: count as u16,
        frames,
        truncated,
    })
}

// ── Parser ──────────────────────────────────────────────────────────────────

// ── Flow control builder ────────────────────────────────────────────────────

/// Build a `TYPE_FLOW_CTL` frame for pausing a stream.
///
/// `stream_id = 0` means global (all streams). `window = 0` means
/// "stop sending entirely". Returns bytes written.
pub fn build_flow_pause(stream_id: u16, window: u32, buf: &mut [u8]) -> usize {
    let mut payload = [0u8; FLOW_CTL_PAYLOAD_SIZE];
    payload[0] = stream_id as u8;
    payload[1] = (stream_id >> 8) as u8;
    payload[2] = window as u8;
    payload[3] = (window >> 8) as u8;
    payload[4] = (window >> 16) as u8;
    payload[5] = (window >> 24) as u8;
    build(TYPE_FLOW_CTL, FLAG_FLOW_PAUSE, &payload, buf)
}

/// Build a `TYPE_FLOW_CTL` frame for resuming a stream with credit.
///
/// `window` is the number of bytes the sender may now transmit.
pub fn build_flow_resume(stream_id: u16, window: u32, buf: &mut [u8]) -> usize {
    let mut payload = [0u8; FLOW_CTL_PAYLOAD_SIZE];
    payload[0] = stream_id as u8;
    payload[1] = (stream_id >> 8) as u8;
    payload[2] = window as u8;
    payload[3] = (window >> 8) as u8;
    payload[4] = (window >> 16) as u8;
    payload[5] = (window >> 24) as u8;
    build(TYPE_FLOW_CTL, 0, &payload, buf)
}

/// Compute the total buffer size needed for a flow-control frame.
pub fn flow_ctl_size() -> usize {
    build_size(FLOW_CTL_PAYLOAD_SIZE)
}

// ── Flow control parser ─────────────────────────────────────────────────────

/// Parse the payload of a `TYPE_FLOW_CTL` frame into a [`FlowCtl`].
///
/// Returns `None` if the payload is malformed (wrong length).
pub fn parse_flow_ctl(frame: &Frame<'_>) -> Option<FlowCtl> {
    if frame.frame_type != TYPE_FLOW_CTL {
        return None;
    }
    if frame.payload.len() < FLOW_CTL_PAYLOAD_SIZE {
        return None;
    }
    let payload = frame.payload;
    let stream_id = u16::from_le_bytes([payload[0], payload[1]]);
    let window = u32::from_le_bytes([payload[2], payload[3], payload[4], payload[5]]);
    let is_pause = frame.flags & FLAG_FLOW_PAUSE != 0;
    Some(FlowCtl { stream_id, window, is_pause })
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
            TYPE_BATCH => "BATCH",
            TYPE_FLOW_CTL => "FLOW_CTL",
            TYPE_PROBE => "PROBE",
            TYPE_PROBE_ACK => "PROBE_ACK",
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

    // ── Batch tests ─────────────────────────────────────────────────────

    #[test]
    fn batch_single_frame_roundtrip() {
        let payload = b"hello batch";
        let mut inner_buf = vec![0u8; build_size(payload.len())];
        let inner_n = build(TYPE_REQUEST, 0, payload, &mut inner_buf);
        let inner = &inner_buf[..inner_n];

        let batch_payload_sz = batch_payload_size(&[inner]);
        let mut batch_buf = vec![0u8; build_size(batch_payload_sz)];
        let batch_n = build_batch(&[inner], 0, &mut batch_buf);

        match parse(&batch_buf[..batch_n]) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.frame_type, TYPE_BATCH);
                let batch = parse_batch_payload(frame.payload).unwrap();
                assert_eq!(batch.declared_count, 1);
                assert!(!batch.truncated);
                assert_eq!(batch.frames.len(), 1);
                assert_eq!(batch.frames[0].payload, payload);
                assert_eq!(batch.frames[0].frame_type, TYPE_REQUEST);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn batch_multiple_frames() {
        let payloads: &[&[u8]] = &[b"frame_A", b"frame_BB", b"frame_CCC"];
        let mut inners = Vec::new();
        let mut buf_pool = vec![0u8; 1024];

        for p in payloads {
            let sz = build_size(p.len());
            buf_pool.resize(sz, 0);
            let n = build(TYPE_NOTIFY, FLAG_PRIORITY, p, &mut buf_pool);
            inners.push(buf_pool[..n].to_vec());
        }

        let inner_refs: Vec<&[u8]> = inners.iter().map(|v| v.as_slice()).collect();
        let batch_payload_sz = batch_payload_size(&inner_refs);
        let mut batch_buf = vec![0u8; build_size(batch_payload_sz)];
        let batch_n = build_batch(&inner_refs, FLAG_COMPRESSED, &mut batch_buf);

        match parse(&batch_buf[..batch_n]) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.frame_type, TYPE_BATCH);
                assert!(frame.is_compressed());
                let batch = parse_batch_payload(frame.payload).unwrap();
                assert_eq!(batch.declared_count, payloads.len() as u16);
                assert!(!batch.truncated);
                assert_eq!(batch.frames.len(), 3);

                for (i, f) in batch.frames.iter().enumerate() {
                    assert_eq!(f.payload, payloads[i], "frame {i} payload mismatch");
                    assert_eq!(f.frame_type, TYPE_NOTIFY);
                    assert!(f.is_priority());
                }
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn batch_empty_allowed() {
        let inner_refs: &[&[u8]] = &[];
        let batch_payload_sz = batch_payload_size(inner_refs);
        assert_eq!(batch_payload_sz, BATCH_COUNT_SIZE); // just the 2-byte count

        let mut batch_buf = vec![0u8; build_size(batch_payload_sz)];
        let batch_n = build_batch(inner_refs, 0, &mut batch_buf);

        match parse(&batch_buf[..batch_n]) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.frame_type, TYPE_BATCH);
                let batch = parse_batch_payload(frame.payload).unwrap();
                assert_eq!(batch.declared_count, 0);
                assert!(batch.frames.is_empty());
                assert!(!batch.truncated);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn batch_truncated_payload() {
        // Build 5 frames, then truncate the batch payload
        let payloads: Vec<Vec<u8>> = (0..5).map(|i| vec![i; 20]).collect();
        let mut inners = Vec::new();
        let mut buf_pool = vec![0u8; 1024];

        for p in &payloads {
            let sz = build_size(p.len());
            buf_pool.resize(sz, 0);
            let n = build(TYPE_NOTIFY, 0, p, &mut buf_pool);
            inners.push(buf_pool[..n].to_vec());
        }

        let inner_refs: Vec<&[u8]> = inners.iter().map(|v| v.as_slice()).collect();
        let batch_payload_sz = batch_payload_size(&inner_refs);
        let mut batch_buf = vec![0u8; build_size(batch_payload_sz)];
        let batch_n = build_batch(&inner_refs, 0, &mut batch_buf);

        // Parse the full batch first
        let full = match parse(&batch_buf[..batch_n]) {
            ParseResult::Complete { frame, .. } => frame,
            other => panic!("unexpected: {:?}", other),
        };
        let batch = parse_batch_payload(full.payload).unwrap();
        assert_eq!(batch.frames.len(), 5);
        assert!(!batch.truncated);

        // Truncate the payload: feed only enough for 2 complete inner frames
        // Each inner frame for a 20-byte payload: 1 Hyb128 + 2 TYPE+FLAGS + 20 = 23 bytes
        let inner_frame_len = build_size(20); // 23
        let trunc_at = BATCH_COUNT_SIZE + (inner_frame_len * 2) + 5; // 2 frames + 5 bytes into 3rd
        assert!(trunc_at < full.payload.len());
        let truncated_payload = &full.payload[..trunc_at];

        let batch = parse_batch_payload(truncated_payload).unwrap();
        assert!(batch.truncated, "should be truncated");
        // Should have parsed at most 2 complete frames (the 3rd is incomplete)
        assert!(batch.frames.len() <= 2,
            "expected <=2 frames, got {} [trunc_at={}, inner_frame_len={inner_frame_len}]",
            batch.frames.len(), trunc_at);
    }

    #[test]
    fn batch_large_count() {
        // Build 100 tiny frames (1-byte payload each)
        let mut inners = Vec::new();
        for i in 0..100u8 {
            let payload = [i; 1];
            let mut buf = vec![0u8; build_size(1)];
            let n = build(TYPE_HEARTBEAT, 0, &payload, &mut buf);
            inners.push(buf[..n].to_vec());
        }

        let inner_refs: Vec<&[u8]> = inners.iter().map(|v| v.as_slice()).collect();
        let batch_payload_sz = batch_payload_size(&inner_refs);
        let mut batch_buf = vec![0u8; build_size(batch_payload_sz)];
        let batch_n = build_batch(&inner_refs, 0, &mut batch_buf);

        match parse(&batch_buf[..batch_n]) {
            ParseResult::Complete { frame, .. } => {
                let batch = parse_batch_payload(frame.payload).unwrap();
                assert_eq!(batch.declared_count, 100);
                assert!(!batch.truncated);
                assert_eq!(batch.frames.len(), 100);
                for (i, f) in batch.frames.iter().enumerate() {
                    assert_eq!(f.frame_type, TYPE_HEARTBEAT);
                    assert_eq!(f.payload, &[i as u8]);
                }
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn batch_type_name() {
        let payload = batch_payload_size(&[]);
        let mut buf = vec![0u8; build_size(payload)];
        build_batch(&[], 0, &mut buf);
        match parse(&buf) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.type_name(), "BATCH");
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    // ── Flow control tests ──────────────────────────────────────────────

    #[test]
    fn flow_pause_build_and_parse() {
        let mut buf = vec![0u8; flow_ctl_size()];
        let n = build_flow_pause(42, 0, &mut buf);

        match parse(&buf[..n]) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.frame_type, TYPE_FLOW_CTL);
                assert_eq!(frame.type_name(), "FLOW_CTL");
                let fc = parse_flow_ctl(&frame).unwrap();
                assert!(fc.is_pause);
                assert_eq!(fc.stream_id, 42);
                assert_eq!(fc.window, 0);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn flow_resume_build_and_parse() {
        let mut buf = vec![0u8; flow_ctl_size()];
        let n = build_flow_resume(7, 65536, &mut buf);

        match parse(&buf[..n]) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.frame_type, TYPE_FLOW_CTL);
                let fc = parse_flow_ctl(&frame).unwrap();
                assert!(!fc.is_pause);
                assert_eq!(fc.stream_id, 7);
                assert_eq!(fc.window, 65536);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn flow_global_stream() {
        let mut buf = vec![0u8; flow_ctl_size()];
        // Global pause: stream_id=0, window=0
        let n = build_flow_pause(0, 0, &mut buf);

        match parse(&buf[..n]) {
            ParseResult::Complete { frame, .. } => {
                let fc = parse_flow_ctl(&frame).unwrap();
                assert!(fc.is_pause);
                assert_eq!(fc.stream_id, 0);
                assert_eq!(fc.window, 0);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn flow_resume_large_window() {
        let mut buf = vec![0u8; flow_ctl_size()];
        let n = build_flow_resume(1, u32::MAX, &mut buf);

        match parse(&buf[..n]) {
            ParseResult::Complete { frame, .. } => {
                let fc = parse_flow_ctl(&frame).unwrap();
                assert!(!fc.is_pause);
                assert_eq!(fc.stream_id, 1);
                assert_eq!(fc.window, u32::MAX);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn flow_ctl_reject_wrong_type() {
        // parse_flow_ctl on a non-FLOW_CTL frame should return None
        let mut buf = vec![0u8; build_size(0)];
        build(TYPE_HEARTBEAT, 0, &[], &mut buf);
        match parse(&buf) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(parse_flow_ctl(&frame), None);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn flow_ctl_reject_short_payload() {
        // Manually craft a FLOW_CTL frame with too-short payload
        let short_payload = [0xAA]; // 1 byte instead of 6
        let mut buf = vec![0u8; build_size(short_payload.len())];
        let n = build(TYPE_FLOW_CTL, FLAG_FLOW_PAUSE, &short_payload, &mut buf);

        match parse(&buf[..n]) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(parse_flow_ctl(&frame), None);
            }
            other => panic!("unexpected: {:?}", other),
        }
    }

    #[test]
    fn flow_ctl_size_constant() {
        assert_eq!(flow_ctl_size(), build_size(FLOW_CTL_PAYLOAD_SIZE));
    }
}
