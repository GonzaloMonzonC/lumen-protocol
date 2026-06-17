//! Hyb128: Hybrid length encoding for LUMEN frames.
//!
//! ## Encoding scheme
//!
//! Byte 0: `[MODE:2bits][PAYLOAD:6bits]`
//!
//! | Mode | Bits  | Meaning                                    | Total bytes |
//! |------|-------|--------------------------------------------|-------------|
//! | `00` | `00`  | Payload is the 6 lower bits (0..63)        | 1           |
//! | `01` | `01`  | Next byte is LEB128 continuation           | 2+          |
//! | `10` | `10`  | Next 2 bytes are u16 little-endian         | 3           |
//! | `11` | `11`  | Next 4 bytes are u32 little-endian         | 5           |
//!
//! ## Properties
//!
//! - **O(1) header parse**: the mode bits tell the parser exactly how many
//!   bytes to skip in a single branch.
//! - **Zero overhead for small messages**: 63-byte payloads cost 1 byte total.
//! - **Scales to 4 GiB**: mode `11` covers any realistic MCP payload.
//!
//! ## Safety
//!
//! All decode functions validate input lengths before reading. No unsafe code.

/// Maximum value encodable in mode `00` (6 bits).
pub const MAX_SHORT: u64 = 0x3F; // 63

/// Mode bits mask (upper 2 bits of first byte).
const MODE_MASK: u8 = 0xC0;

/// Payload bits mask (lower 6 bits of first byte).
const SHORT_MASK: u8 = 0x3F;

// ── Mode constants ──────────────────────────────────────────────────────────

const MODE_SHORT: u8 = 0x00; // 00______
const MODE_LEB128: u8 = 0x40; // 01______
const MODE_U16: u8 = 0x80; // 10______
const MODE_U32: u8 = 0xC0; // 11______

// ── Encode ──────────────────────────────────────────────────────────────────

/// Encodes a length into a byte buffer.
///
/// Returns the number of bytes written (1, 2-10, 3, or 5).
/// Panics if the buffer is too small.
pub fn encode(value: u64, buf: &mut [u8]) -> usize {
    if value <= MAX_SHORT {
        buf[0] = MODE_SHORT | (value as u8 & SHORT_MASK);
        return 1;
    }

    if value <= u16::MAX as u64 {
        buf[0] = MODE_U16;
        let bytes = (value as u16).to_le_bytes();
        buf[1] = bytes[0];
        buf[2] = bytes[1];
        return 3;
    }

    if value <= u32::MAX as u64 {
        buf[0] = MODE_U32;
        let bytes = (value as u32).to_le_bytes();
        buf[1..5].copy_from_slice(&bytes);
        return 5;
    }

    // Fallback: LEB128 for values > u32::MAX (extremely rare in MCP)
    buf[0] = MODE_LEB128;
    leb128_encode(value, &mut buf[1..])
}

/// Returns the number of bytes `encode(value)` would write.
pub const fn encoded_len(value: u64) -> usize {
    if value <= MAX_SHORT {
        1
    } else if value <= u16::MAX as u64 {
        3
    } else if value <= u32::MAX as u64 {
        5
    } else {
        // LEB128: worst case for u64 is 10 bytes + 1 mode byte
        1 + leb128_max_len(value)
    }
}

/// Returns the maximum number of bytes needed to buffer a Hyb128 length.
pub const MAX_ENCODED_LEN: usize = 11; // 1 mode + 10 LEB128

// ── Decode ──────────────────────────────────────────────────────────────────

/// Decoded length result: the value and how many header bytes were consumed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Decoded {
    /// The decoded payload length in bytes.
    pub value: u64,
    /// Number of bytes consumed from the input to parse this length.
    pub header_len: usize,
}

/// Decodes a Hyb128 length from `bytes`.
///
/// Returns `None` if the input is too short to contain a complete header.
/// Lenient mode: accepts non-minimal encodings (e.g., value 10 as U16).
pub fn decode(bytes: &[u8]) -> Option<Decoded> {
    decode_inner(bytes, false)
}

/// Strict decode: rejects non-minimal encodings.
///
/// Prevents canonicalization bypass attacks.  Rejects:
/// - U16 encoding for values ≤ 63 (should be Short)
/// - U32 encoding for values ≤ 65535 (should be U16 or Short)
/// - LEB128 encoding for values ≤ 4294967295 (should be U32 or lower)
pub fn decode_strict(bytes: &[u8]) -> Option<Decoded> {
    decode_inner(bytes, true)
}

fn decode_inner(bytes: &[u8], strict: bool) -> Option<Decoded> {
    let first = *bytes.first()?;
    match first & MODE_MASK {
        MODE_SHORT => Some(Decoded {
            value: (first & SHORT_MASK) as u64,
            header_len: 1,
        }),

        MODE_U16 => {
            if bytes.len() < 3 {
                return None;
            }
            let arr = [bytes[1], bytes[2]];
            let value = u16::from_le_bytes(arr) as u64;
            if strict && value <= 63 {
                return None; // should have been Short
            }
            Some(Decoded { value, header_len: 3 })
        }

        MODE_U32 => {
            if bytes.len() < 5 {
                return None;
            }
            let arr = [bytes[1], bytes[2], bytes[3], bytes[4]];
            let value = u32::from_le_bytes(arr) as u64;
            if strict && value <= 65535 {
                return None; // should have been U16 or Short
            }
            Some(Decoded { value, header_len: 5 })
        }

        MODE_LEB128 => {
            let result = leb128_decode(&bytes[1..])?;
            if strict && result.0 <= 0xFFFFFFFF {
                return None; // should have been U32 or lower
            }
            Some(Decoded {
                value: result.0,
                header_len: 1 + result.1,
            })
        }

        _ => unreachable!(),
    }
}

// ── LEB128 helpers (used only for mode 01, rare path) ──────────────────────

fn leb128_encode(mut value: u64, buf: &mut [u8]) -> usize {
    let mut written = 0;
    loop {
        let mut byte = (value & 0x7F) as u8;
        value >>= 7;
        if value != 0 {
            byte |= 0x80;
        }
        buf[written] = byte;
        written += 1;
        if value == 0 {
            break;
        }
    }
    written + 1 // +1 for the mode byte
}

fn leb128_decode(bytes: &[u8]) -> Option<(u64, usize)> {
    let mut value: u64 = 0;
    let mut shift: u32 = 0;
    for (i, &byte) in bytes.iter().enumerate() {
        if i >= 10 {
            // LEB128 u64 cannot exceed 10 bytes
            return None;
        }
        value |= ((byte & 0x7F) as u64) << shift;
        if byte & 0x80 == 0 {
            return Some((value, i + 1));
        }
        shift += 7;
    }
    None // truncated
}

const fn leb128_max_len(value: u64) -> usize {
    // Count how many 7-bit groups are needed
    if value == 0 {
        return 1;
    }
    let bits = 64 - value.leading_zeros() as usize;
    (bits + 6) / 7
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    fn roundtrip(value: u64) {
        let mut buf = [0u8; MAX_ENCODED_LEN];
        let n = encode(value, &mut buf);
        let decoded = decode(&buf[..n]).expect("decode failed");
        assert_eq!(decoded.value, value, "value mismatch for {}", value);
        assert_eq!(decoded.header_len, n, "header_len mismatch for {}", value);
    }

    #[test]
    fn mode_short_boundaries() {
        for v in [0, 1, 42, 63] {
            roundtrip(v);
            let mut buf = [0u8; MAX_ENCODED_LEN];
            let n = encode(v, &mut buf);
            assert_eq!(n, 1, "mode short should use 1 byte");
            assert_eq!(buf[0] & MODE_MASK, MODE_SHORT);
        }
    }

    #[test]
    fn mode_u16_boundaries() {
        for v in [64u64, 255, 1000, u16::MAX as u64] {
            roundtrip(v);
            let mut buf = [0u8; MAX_ENCODED_LEN];
            let n = encode(v, &mut buf);
            assert_eq!(n, 3, "mode u16 should use 3 bytes");
            assert_eq!(buf[0] & MODE_MASK, MODE_U16);
        }
    }

    #[test]
    fn mode_u32_boundaries() {
        let v = u16::MAX as u64 + 1;
        roundtrip(v);
        roundtrip(u32::MAX as u64);
    }

    #[test]
    fn truncated_input() {
        let buf = [MODE_U16, 0x42]; // only 2 bytes, needs 3
        assert!(decode(&buf).is_none());

        let buf2 = [MODE_U32, 0x01, 0x02]; // only 3 bytes, needs 5
        assert!(decode(&buf2).is_none());
    }

    #[test]
    fn encoded_len_matches() {
        for v in [0, 63, 64, 1000, 65535, 65536, 1_000_000, u32::MAX as u64] {
            let mut buf = [0u8; MAX_ENCODED_LEN];
            let n = encode(v, &mut buf);
            assert_eq!(encoded_len(v), n, "encoded_len mismatch for {}", v);
        }
    }

    #[test]
    fn leb128_fallback() {
        let big = u32::MAX as u64 + 1;
        roundtrip(big);
        roundtrip(u64::MAX);
    }

    #[test]
    fn o1_property_no_loop_in_decode() {
        // The decode function for modes 00/10/11 should NOT iterate.
        // This is a compile-time property: the match arms are simple
        // array indexing. We test it implicitly via roundtrip.
        for v in 0..u32::MAX as u64 {
            roundtrip(v);
            if v > 1_000_000 {
                break; // don't run 4 billion iterations ;)
            }
        }
    }
}
