//! Native token streaming — STREAM_INIT / STREAM_DATA payload builders.
//!
//! ## Wire format (little-endian)
//!
//! **STREAM_INIT** (frame type 0x06):
//! ```
//! [stream_id: u32 LE][max_tokens: u32 LE][temperature: f32 LE]
//! [model_len: u8][model: UTF-8]
//! ```
//!
//! **STREAM_DATA** (frame type 0x04):
//! ```
//! [stream_id: u32 LE][token_seq: u32 LE][token_type: u8]
//! [token_data: variable UTF-8 or raw bytes]
//! ```
//!
//! **Token types:**
//! - `0x00` — text token (UTF-8)
//! - `0x01` — binary token (raw bytes)
//! - `0x02` — end-of-stream (no data; receiver MUST close the stream)
//!
//! ## Stream lifecycle
//!
//! ```text
//! Client                              Server
//!   │                                   │
//!   │── STREAM_INIT(id=1, model="gpt")─►│  register stream
//!   │                                   │
//!   │◄── STREAM_DATA(id=1, seq=0, "He")─│  first token
//!   │◄── STREAM_DATA(id=1, seq=1, "llo")│
//!   │◄── STREAM_DATA(id=1, seq=2, END)──│  stream complete
//!   │                                   │
//! ```

use std::collections::HashMap;

// ── Token type constants ────────────────────────────────────────────────────

/// Text token (UTF-8 encoded).
pub const TOKEN_TEXT: u8 = 0x00;
/// Raw binary token.
pub const TOKEN_BINARY: u8 = 0x01;
/// End-of-stream sentinel (no token_data).
pub const TOKEN_END: u8 = 0x02;

// ── STREAM_INIT ─────────────────────────────────────────────────────────────

/// Find the largest valid UTF-8 boundary at or below `max_bytes` in `data`.
///
/// Returns the index such that `&data[..idx]` is valid UTF-8 (no partial
/// characters) and `idx <= max_bytes`.
fn utf8_truncate(data: &[u8], max_bytes: usize) -> usize {
    if max_bytes >= data.len() {
        return data.len();
    }
    // Walk backwards from max_bytes to find the END of a complete UTF-8
    // character. A character ends just before the next character-start byte
    // or at the end of data.
    // UTF-8 character start bytes are: 0x00-0x7F (ASCII), or 0xC0-0xFF
    // Continuation bytes are: 0x80-0xBF
    let mut boundary = max_bytes;
    // Walk back while we're inside a multi-byte character
    while boundary > 0 {
        boundary -= 1;
        let b = data[boundary];
        if b < 0x80 || b >= 0xC0 {
            // This is a character start byte.
            // Check if the full character fits within max_bytes
            let char_len = if b < 0x80 {
                1
            } else if b < 0xE0 {
                2
            } else if b < 0xF0 {
                3
            } else {
                4
            };
            if boundary + char_len <= max_bytes {
                // Full character fits → return end of this character
                return boundary + char_len;
            }
            // Character doesn't fit → continue walking back
        }
    }
    // Nothing fits at all (shouldn't happen for valid UTF-8, but handle)
    0
}

/// Payload for a STREAM_INIT frame (0x06).
///
/// Sent by the client to initiate a token stream.  The server responds
/// with STREAM_DATA frames carrying tokens as they are generated.
#[derive(Debug, Clone)]
pub struct StreamInit {
    /// Unique stream identifier for this connection.
    pub stream_id: u32,
    /// Maximum number of tokens to generate (0 = unlimited).
    pub max_tokens: u32,
    /// Sampling temperature (0.0–2.0).
    pub temperature: f32,
    /// Model identifier (e.g., "gpt-4", "claude-3").
    pub model: String,
}

impl StreamInit {
    /// Encode into the binary payload for a STREAM_INIT frame.
    pub fn encode(&self) -> Vec<u8> {
        let model_bytes = self.model.as_bytes();
        let truncate_at = utf8_truncate(model_bytes, 255);
        let truncated = &model_bytes[..truncate_at];
        let cap = 13 + truncated.len();
        let mut buf = Vec::with_capacity(cap);

        buf.extend_from_slice(&self.stream_id.to_le_bytes());
        buf.extend_from_slice(&self.max_tokens.to_le_bytes());
        buf.extend_from_slice(&self.temperature.to_le_bytes());
        buf.push(truncated.len() as u8);
        buf.extend_from_slice(truncated);

        buf
    }

    /// Decode a STREAM_INIT payload. Returns `None` if the data is too short
    /// or the model_len field exceeds available bytes.
    pub fn decode(data: &[u8]) -> Option<Self> {
        if data.len() < 13 {
            return None; // minimum: 4+4+4+1 = 13 bytes
        }

        let stream_id = u32::from_le_bytes(data[0..4].try_into().ok()?);
        let max_tokens = u32::from_le_bytes(data[4..8].try_into().ok()?);
        let temperature = f32::from_le_bytes(data[8..12].try_into().ok()?);
        let model_len = data[12] as usize;

        if data.len() < 13 + model_len {
            return None; // truncated model name
        }

        let model = String::from_utf8(data[13..13 + model_len].to_vec()).ok()?;

        Some(Self {
            stream_id,
            max_tokens,
            temperature,
            model,
        })
    }

    /// Size of the encoded payload in bytes.
    pub fn encoded_len(&self) -> usize {
        13 + utf8_truncate(self.model.as_bytes(), 255)
    }
}

// ── STREAM_DATA ─────────────────────────────────────────────────────────────

/// Payload for a STREAM_DATA frame (0x04).
///
/// Carries a single token in a streaming response.  When `token_type` is
/// `TOKEN_END`, the stream is complete and the receiver SHOULD close it.
#[derive(Debug, Clone)]
pub struct StreamData {
    /// Stream identifier (must match a previously sent STREAM_INIT).
    pub stream_id: u32,
    /// Monotonically increasing sequence number (starts at 0).
    pub token_seq: u32,
    /// Token type (`TOKEN_TEXT`, `TOKEN_BINARY`, or `TOKEN_END`).
    pub token_type: u8,
    /// Token payload (UTF-8 for text, raw bytes for binary, empty for END).
    pub token_data: Vec<u8>,
}

impl StreamData {
    /// Encode into the binary payload for a STREAM_DATA frame.
    pub fn encode(&self) -> Vec<u8> {
        let cap = 4 + 4 + 1 + self.token_data.len();
        let mut buf = Vec::with_capacity(cap);

        buf.extend_from_slice(&self.stream_id.to_le_bytes());
        buf.extend_from_slice(&self.token_seq.to_le_bytes());
        buf.push(self.token_type);
        buf.extend_from_slice(&self.token_data);

        buf
    }

    /// Decode a STREAM_DATA payload. Returns `None` if the data is too short.
    pub fn decode(data: &[u8]) -> Option<Self> {
        if data.len() < 9 {
            return None; // minimum: 4+4+1 = 9 bytes
        }

        let stream_id = u32::from_le_bytes(data[0..4].try_into().ok()?);
        let token_seq = u32::from_le_bytes(data[4..8].try_into().ok()?);
        let token_type = data[8];
        let token_data = data[9..].to_vec();

        Some(Self {
            stream_id,
            token_seq,
            token_type,
            token_data,
        })
    }

    /// Returns `true` if this is an end-of-stream token.
    pub fn is_end(&self) -> bool {
        self.token_type == TOKEN_END
    }

    /// Returns the token as a UTF-8 string if it is a text token.
    pub fn as_text(&self) -> Option<&str> {
        if self.token_type == TOKEN_TEXT {
            std::str::from_utf8(&self.token_data).ok()
        } else {
            None
        }
    }

    /// Size of the encoded payload in bytes.
    pub fn encoded_len(&self) -> usize {
        9 + self.token_data.len()
    }
}

// ── Stream Registry ─────────────────────────────────────────────────────────

/// Error returned by [`StreamRegistry`] operations.
#[derive(Debug, PartialEq, Eq)]
pub enum StreamError {
    /// STREAM_DATA received for an unknown stream_id.
    UnknownStream(u32),
    /// token_seq is not monotonically increasing.
    SequenceGap { expected: u32, received: u32 },
    /// STREAM_INIT received for an already-active stream_id.
    DuplicateStream(u32),
    /// max_tokens limit exceeded.
    TokenLimitExceeded { limit: u32, count: u32 },
}

impl std::fmt::Display for StreamError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::UnknownStream(id) => write!(f, "unknown stream {id}"),
            Self::SequenceGap { expected, received } => {
                write!(f, "sequence gap: expected {expected}, got {received}")
            }
            Self::DuplicateStream(id) => write!(f, "duplicate stream {id}"),
            Self::TokenLimitExceeded { limit, count } => {
                write!(f, "token limit {limit} exceeded ({count})")
            }
        }
    }
}

impl std::error::Error for StreamError {}

/// Tracks active token streams within a connection.
///
/// Validates that STREAM_DATA frames belong to a known stream, token
/// sequences are monotonic, and max_tokens limits are honoured.
#[derive(Debug, Default)]
pub struct StreamRegistry {
    streams: HashMap<u32, StreamState>,
}

#[derive(Debug)]
struct StreamState {
    model: String,
    max_tokens: u32,
    #[allow(dead_code)]
    temperature: f32,
    next_seq: u32,
    token_count: u32,
}

impl StreamRegistry {
    /// Create a new empty registry.
    pub fn new() -> Self {
        Self {
            streams: HashMap::new(),
        }
    }

    /// Register a new stream from a STREAM_INIT.
    ///
    /// Returns an error if the stream_id is already active.
    pub fn register(&mut self, init: &StreamInit) -> Result<(), StreamError> {
        if self.streams.contains_key(&init.stream_id) {
            return Err(StreamError::DuplicateStream(init.stream_id));
        }

        self.streams.insert(
            init.stream_id,
            StreamState {
                model: init.model.clone(),
                max_tokens: init.max_tokens,
                temperature: init.temperature,
                next_seq: 0,
                token_count: 0,
            },
        );

        Ok(())
    }

    /// Process an incoming STREAM_DATA token.
    ///
    /// Validates the stream_id exists, the token_seq is correct, and the
    /// max_tokens limit is not exceeded.  Returns `Ok(true)` if this is
    /// the end-of-stream token (caller should remove the stream).
    pub fn accept(&mut self, data: &StreamData) -> Result<bool, StreamError> {
        let state = self
            .streams
            .get_mut(&data.stream_id)
            .ok_or(StreamError::UnknownStream(data.stream_id))?;

        // Validate sequence
        if data.token_seq != state.next_seq {
            return Err(StreamError::SequenceGap {
                expected: state.next_seq,
                received: data.token_seq,
            });
        }

        state.next_seq += 1;

        if data.is_end() {
            // NOTE: The caller MUST call remove() after receiving Ok(true).
            // If the caller forgets, the stream stays registered and any
            // subsequent STREAM_DATA for this stream_id will be rejected
            // (sequence gap) and re-registration will fail (duplicate).
            return Ok(true);
        }

        state.token_count += 1;

        // Check token limit
        if state.max_tokens > 0 && state.token_count > state.max_tokens {
            return Err(StreamError::TokenLimitExceeded {
                limit: state.max_tokens,
                count: state.token_count,
            });
        }

        Ok(false)
    }

    /// Remove a completed stream.
    pub fn remove(&mut self, stream_id: u32) -> Option<StreamState> {
        self.streams.remove(&stream_id)
    }

    /// Number of active streams.
    pub fn len(&self) -> usize {
        self.streams.len()
    }

    /// Returns `true` if there are no active streams.
    pub fn is_empty(&self) -> bool {
        self.streams.is_empty()
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn utf8_truncate_boundary() {
        // "abc" = 3 bytes, all ASCII
        assert_eq!(utf8_truncate(b"abc", 3), 3);
        assert_eq!(utf8_truncate(b"abc", 1), 1); // 'a' is 1 byte
        // "ñ" = 2 bytes (0xC3, 0xB1)
        assert_eq!(utf8_truncate("ñ".as_bytes(), 2), 2);
        assert_eq!(utf8_truncate("ñ".as_bytes(), 1), 0); // can't split
        // empty
        assert_eq!(utf8_truncate(b"", 0), 0);
    }

    // ── StreamInit encode/decode ─────────────────────────────────────────

    #[test]
    fn stream_init_roundtrip() {
        let init = StreamInit {
            stream_id: 42,
            max_tokens: 2048,
            temperature: 0.7f32,
            model: "gpt-4".into(),
        };

        let encoded = init.encode();
        let decoded = StreamInit::decode(&encoded).unwrap();

        assert_eq!(decoded.stream_id, 42);
        assert_eq!(decoded.max_tokens, 2048);
        assert!((decoded.temperature - 0.7f32).abs() < 0.001);
        assert_eq!(decoded.model, "gpt-4");
    }

    #[test]
    fn stream_init_decode_too_short() {
        assert!(StreamInit::decode(&[0u8; 12]).is_none()); // less than 13 bytes
    }

    #[test]
    fn stream_init_truncated_model() {
        let mut buf = vec![0u8; 13];
        buf[12] = 10; // model_len = 10, but no model bytes follow
        assert!(StreamInit::decode(&buf).is_none());
    }

    #[test]
    fn stream_init_long_model_truncated() {
        let init = StreamInit {
            stream_id: 1,
            max_tokens: 100,
            temperature: 0.0,
            model: "a".repeat(300), // longer than u8::MAX
        };
        let encoded = init.encode();
        let decoded = StreamInit::decode(&encoded).unwrap();
        assert_eq!(decoded.model.len(), 255); // capped at u8::MAX
    }

    #[test]
    fn stream_init_empty_model() {
        let init = StreamInit {
            stream_id: 1,
            max_tokens: 0,
            temperature: 0.0,
            model: String::new(),
        };
        let encoded = init.encode();
        assert_eq!(encoded.len(), 13); // just the header, model_len=0
        let decoded = StreamInit::decode(&encoded).unwrap();
        assert_eq!(decoded.model, "");
    }

    #[test]
    fn stream_init_utf8_boundary() {
        // 128 × "ñ" = 256 bytes. Truncated at 255-byte cap.
        // utf8_truncate should step back to the nearest character boundary:
        // 254 bytes = 127 complete "ñ"s.
        let long = "ñ".repeat(128); // 256 bytes
        let init = StreamInit {
            stream_id: 1,
            max_tokens: 0,
            temperature: 0.0,
            model: long,
        };
        let encoded = init.encode();
        let decoded = StreamInit::decode(&encoded).unwrap();
        assert_eq!(decoded.model.len(), 254); // 127 chars × 2 bytes = 254
        assert_eq!(decoded.model.chars().count(), 127);
    }

    // ── StreamData encode/decode ─────────────────────────────────────────

    #[test]
    fn stream_data_text_roundtrip() {
        let data = StreamData {
            stream_id: 7,
            token_seq: 3,
            token_type: TOKEN_TEXT,
            token_data: b"hello".to_vec(),
        };

        let encoded = data.encode();
        let decoded = StreamData::decode(&encoded).unwrap();

        assert_eq!(decoded.stream_id, 7);
        assert_eq!(decoded.token_seq, 3);
        assert_eq!(decoded.token_type, TOKEN_TEXT);
        assert_eq!(decoded.token_data, b"hello");
        assert!(!decoded.is_end());
        assert_eq!(decoded.as_text(), Some("hello"));
    }

    #[test]
    fn stream_data_end_marker() {
        let data = StreamData {
            stream_id: 1,
            token_seq: 99,
            token_type: TOKEN_END,
            token_data: vec![],
        };

        assert!(data.is_end());
        assert!(data.as_text().is_none()); // END has no text

        let encoded = data.encode();
        let decoded = StreamData::decode(&encoded).unwrap();
        assert!(decoded.is_end());
        assert_eq!(decoded.token_seq, 99);
    }

    #[test]
    fn stream_data_decode_too_short() {
        assert!(StreamData::decode(&[0u8; 8]).is_none());
    }

    #[test]
    fn stream_data_binary_roundtrip() {
        let data = StreamData {
            stream_id: 0,
            token_seq: 0,
            token_type: TOKEN_BINARY,
            token_data: vec![0xDE, 0xAD, 0xBE, 0xEF],
        };

        let encoded = data.encode();
        let decoded = StreamData::decode(&encoded).unwrap();
        assert_eq!(decoded.token_type, TOKEN_BINARY);
        assert_eq!(decoded.token_data, vec![0xDE, 0xAD, 0xBE, 0xEF]);
        assert!(decoded.as_text().is_none()); // binary is not text
    }

    // ── StreamRegistry ───────────────────────────────────────────────────

    #[test]
    fn registry_lifecycle() {
        let mut reg = StreamRegistry::new();
        assert!(reg.is_empty());

        // Register a stream
        let init = StreamInit {
            stream_id: 1,
            max_tokens: 3,
            temperature: 0.5,
            model: "test".into(),
        };
        reg.register(&init).unwrap();
        assert_eq!(reg.len(), 1);

        // Duplicate registration fails
        assert!(matches!(
            reg.register(&init),
            Err(StreamError::DuplicateStream(1))
        ));

        // Accept tokens in sequence
        for seq in 0..3 {
            let token = StreamData {
                stream_id: 1,
                token_seq: seq,
                token_type: TOKEN_TEXT,
                token_data: format!("tok{seq}").into_bytes(),
            };
            assert!(!reg.accept(&token).unwrap()); // not end
        }

        // End-of-stream
        let end = StreamData {
            stream_id: 1,
            token_seq: 3,
            token_type: TOKEN_END,
            token_data: vec![],
        };
        assert!(reg.accept(&end).unwrap()); // signals end

        reg.remove(1);
        assert!(reg.is_empty());

        // Re-registration with same stream_id after removal MUST work
        reg.register(&init).unwrap();
        assert_eq!(reg.len(), 1);
    }

    #[test]
    fn registry_unknown_stream() {
        let mut reg = StreamRegistry::new();
        let data = StreamData {
            stream_id: 999,
            token_seq: 0,
            token_type: TOKEN_TEXT,
            token_data: b"x".to_vec(),
        };
        assert!(matches!(
            reg.accept(&data),
            Err(StreamError::UnknownStream(999))
        ));
    }

    #[test]
    fn registry_sequence_gap() {
        let mut reg = StreamRegistry::new();
        reg.register(&StreamInit {
            stream_id: 1,
            max_tokens: 100,
            temperature: 0.0,
            model: "t".into(),
        })
        .unwrap();

        // Skip seq 0, send seq 5
        let data = StreamData {
            stream_id: 1,
            token_seq: 5,
            token_type: TOKEN_TEXT,
            token_data: b"x".to_vec(),
        };
        assert!(matches!(
            reg.accept(&data),
            Err(StreamError::SequenceGap {
                expected: 0,
                received: 5
            })
        ));
    }

    #[test]
    fn registry_token_limit_exceeded() {
        let mut reg = StreamRegistry::new();
        reg.register(&StreamInit {
            stream_id: 1,
            max_tokens: 2,
            temperature: 0.0,
            model: "t".into(),
        })
        .unwrap();

        // Accept 2 tokens
        for seq in 0..2 {
            reg.accept(&StreamData {
                stream_id: 1,
                token_seq: seq,
                token_type: TOKEN_TEXT,
                token_data: b"x".to_vec(),
            })
            .unwrap();
        }

        // 3rd token exceeds limit
        let third = StreamData {
            stream_id: 1,
            token_seq: 2,
            token_type: TOKEN_TEXT,
            token_data: b"x".to_vec(),
        };
        assert!(matches!(
            reg.accept(&third),
            Err(StreamError::TokenLimitExceeded { limit: 2, count: 3 })
        ));
    }

    #[test]
    fn registry_multiple_streams() {
        let mut reg = StreamRegistry::new();

        for id in 0..5u32 {
            reg.register(&StreamInit {
                stream_id: id,
                max_tokens: 10,
                temperature: 0.0,
                model: "m".into(),
            })
            .unwrap();
        }
        assert_eq!(reg.len(), 5);

        // Send one token on each
        for id in 0..5u32 {
            reg.accept(&StreamData {
                stream_id: id,
                token_seq: 0,
                token_type: TOKEN_TEXT,
                token_data: b"x".to_vec(),
            })
            .unwrap();
        }
    }

    #[test]
    fn encoded_len_matches_encode() {
        let init = StreamInit {
            stream_id: 1,
            max_tokens: 100,
            temperature: 0.5,
            model: "gpt-4".into(),
        };
        assert_eq!(init.encode().len(), init.encoded_len());

        let data = StreamData {
            stream_id: 1,
            token_seq: 0,
            token_type: TOKEN_TEXT,
            token_data: b"hello world".to_vec(),
        };
        assert_eq!(data.encode().len(), data.encoded_len());
    }

    // ── Edge cases ──────────────────────────────────────────────────────

    #[test]
    fn stream_data_zero_length_token() {
        // Empty token_data on TEXT type — unusual but valid (empty string)
        let data = StreamData {
            stream_id: 1,
            token_seq: 0,
            token_type: TOKEN_TEXT,
            token_data: vec![],
        };
        assert!(!data.is_end()); // not END, even though empty
        assert_eq!(data.as_text(), Some(""));
        let encoded = data.encode();
        assert_eq!(encoded.len(), 9); // header only, no data
    }

    #[test]
    fn stream_data_unknown_token_type() {
        // Unknown token type should still roundtrip
        let data = StreamData {
            stream_id: 1,
            token_seq: 0,
            token_type: 0xFF,
            token_data: b"raw".to_vec(),
        };
        assert!(!data.is_end());
        assert!(data.as_text().is_none());

        let decoded = StreamData::decode(&data.encode()).unwrap();
        assert_eq!(decoded.token_type, 0xFF);
    }

    #[test]
    fn stream_init_max_values() {
        let init = StreamInit {
            stream_id: u32::MAX,
            max_tokens: u32::MAX,
            temperature: f32::INFINITY,
            model: "gpt".into(),
        };
        let decoded = StreamInit::decode(&init.encode()).unwrap();
        assert_eq!(decoded.stream_id, u32::MAX);
        assert_eq!(decoded.max_tokens, u32::MAX);
        assert!(decoded.temperature.is_infinite());
    }

    #[test]
    fn stream_init_nan_temperature() {
        let init = StreamInit {
            stream_id: 1,
            max_tokens: 0,
            temperature: f32::NAN,
            model: "gpt".into(),
        };
        let decoded = StreamInit::decode(&init.encode()).unwrap();
        assert!(decoded.temperature.is_nan());
    }

    #[test]
    fn registry_unknown_token_type_accepted() {
        let mut reg = StreamRegistry::new();
        reg.register(&StreamInit {
            stream_id: 1,
            max_tokens: 0,
            temperature: 0.0,
            model: "t".into(),
        }).unwrap();

        // Unknown token types are accepted (not validated by registry)
        let data = StreamData {
            stream_id: 1,
            token_seq: 0,
            token_type: 0xFF,
            token_data: vec![],
        };
        assert!(!reg.accept(&data).unwrap());
        assert_eq!(reg.len(), 1);
    }

    #[test]
    fn registry_end_token_does_not_count() {
        let mut reg = StreamRegistry::new();
        reg.register(&StreamInit {
            stream_id: 1,
            max_tokens: 1, // only 1 token allowed
            temperature: 0.0,
            model: "t".into(),
        }).unwrap();

        // Accept 1 data token
        reg.accept(&StreamData {
            stream_id: 1, token_seq: 0, token_type: TOKEN_TEXT,
            token_data: b"x".to_vec(),
        }).unwrap();

        // END token should NOT count against the limit
        let end = StreamData {
            stream_id: 1, token_seq: 1, token_type: TOKEN_END,
            token_data: vec![],
        };
        assert!(reg.accept(&end).unwrap()); // true = END
        reg.remove(1);
    }

    #[test]
    fn registry_data_after_forgotten_remove() {
        // BUG-CATCHER: If caller forgets remove() after END, next_seq was
        // incremented by END, so the next DATA with matching seq PASSES.
        // This is documented behavior — caller MUST remove after END.
        let mut reg = StreamRegistry::new();
        reg.register(&StreamInit {
            stream_id: 1, max_tokens: 0, temperature: 0.0, model: "t".into(),
        }).unwrap();

        let end = StreamData {
            stream_id: 1, token_seq: 0, token_type: TOKEN_END, token_data: vec![],
        };
        assert!(reg.accept(&end).unwrap()); // END, next_seq → 1
        // Caller forgets remove() — stream still registered with next_seq=1

        // seq=1 matches next_seq=1 → ACCEPTED (not rejected!)
        let more = StreamData {
            stream_id: 1, token_seq: 1, token_type: TOKEN_TEXT, token_data: b"x".to_vec(),
        };
        assert!(reg.accept(&more).is_ok()); // passes — caller's responsibility

        // seq=0 is below next_seq=2 → gap
        let backtrack = StreamData {
            stream_id: 1, token_seq: 0, token_type: TOKEN_TEXT, token_data: b"x".to_vec(),
        };
        assert!(matches!(
            reg.accept(&backtrack),
            Err(StreamError::SequenceGap { expected: 2, received: 0 })
        ));

        // Re-registration fails (duplicate)
        assert!(matches!(
            reg.register(&StreamInit {
                stream_id: 1, max_tokens: 0, temperature: 0.0, model: "t".into(),
            }),
            Err(StreamError::DuplicateStream(1))
        ));

        // After explicit remove, re-registration works
        reg.remove(1);
        assert!(reg.register(&StreamInit {
            stream_id: 1, max_tokens: 0, temperature: 0.0, model: "t".into(),
        }).is_ok());
    }
}
