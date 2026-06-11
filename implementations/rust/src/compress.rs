//! Payload compression: JSON → compact binary using the static dictionary.
//!
//! ## Encoding format
//!
//! ```text
//! Value:
//!   Null:    0xE0
//!   Bool:    0xE1 <0|1:1B>
//!   Number:  0xE2 <f64 LE:8B>
//!   String:  [dict] 0xE3 <id:1B>
//!            [raw]  0xE4 <len:Hyb128> <utf8>
//!   Array:   0xE5 <count:Hyb128> value*
//!   Object:  0xE6 <count:Hyb128> (key value)*
//!
//! Key (inside Object):
//!   [dict] <id:1B>     where id ∈ 0x00..0xFE
//!   [raw]  0xFF <len:Hyb128> <utf8>
//! ```
//!
//! Total tags: 7 value types + 1 key sentinel = 8.
//! Tags chosen so that:
//! - 0xE0..0xE6 = value types (Nil→Obj)
//! - 0x00..0xFE = dict key IDs
//! - 0xFF = raw key sentinel

use crate::dict;
use crate::hyb128;
use serde_json::{Number, Value};

// ── Value tags ──────────────────────────────────────────────────────────────

const TAG_NULL: u8 = 0xE0;
const TAG_BOOL: u8 = 0xE1;
const TAG_FLOAT: u8 = 0xE2;
const TAG_INT: u8 = 0xE3;
const TAG_STR_DICT: u8 = 0xE4;
const TAG_STR_RAW: u8 = 0xE5;
const TAG_ARRAY: u8 = 0xE6;
const TAG_OBJECT: u8 = 0xE7;

// ── Public API ──────────────────────────────────────────────────────────────

/// Compress a `serde_json::Value` into LUMEN compact binary.
///
/// Returns the compressed byte vector.  Decompression with
/// [`decompress`] recovers the original `Value` losslessly.
pub fn compress(value: &Value) -> Vec<u8> {
    let mut buf = Vec::new();
    encode_value(value, &mut buf);
    buf
}

/// Compress a `serde_json::Value` into an existing buffer (zero-alloc encode).
///
/// Appends the compressed bytes to `buf`.  If `buf` has sufficient spare
/// capacity this path performs **no heap allocations**.
pub fn compress_into(value: &Value, buf: &mut Vec<u8>) {
    encode_value(value, buf);
}

/// Decompress a LUMEN compact binary back to `serde_json::Value`.
///
/// Returns `None` if the input is malformed.
pub fn decompress(data: &[u8]) -> Option<Value> {
    let mut pos = 0;
    decode_value(data, &mut pos)
}

/// Estimate (quickly, without full encode) the compressed size.
///
/// Useful for buffer pre-allocation.
pub fn compressed_size(value: &Value) -> usize {
    match value {
        Value::Null => 1,
        Value::Bool(_) => 2,
        Value::Number(n) => {
            if let Some(i) = n.as_i64() {
                if serde_json::Number::from(i) == *n {
                    // TAG_INT + variable LEB128
                    return 1 + i64_leb128_len(i);
                }
            }
            9 // TAG_FLOAT + f64
        }
        Value::String(s) => {
            if dict::lookup_fast(s).is_some() { 2 } else { 1 + 1 + hyb128::encoded_len(s.len() as u64) + s.len() }
        }
        Value::Array(arr) => {
            let mut sz = 1 + hyb128::encoded_len(arr.len() as u64); // TAG + count
            for v in arr {
                sz += compressed_size(v);
            }
            sz
        }
        Value::Object(map) => {
            let mut sz = 1 + hyb128::encoded_len(map.len() as u64); // TAG + count
            for (k, v) in map {
                sz += key_size(k);
                sz += compressed_size(v);
            }
            sz
        }
    }
}

fn key_size(key: &str) -> usize {
    if dict::lookup_fast(key).is_some() { 1 } else { 1 + 1 + hyb128::encoded_len(key.len() as u64) + key.len() }
}

/// Estimate LEB128 byte count for an i64 (zigzag-encoded).
fn i64_leb128_len(v: i64) -> usize {
    let u = ((v >> 63) as u64) ^ ((v as u64) << 1);
    let mut len = 0;
    let mut n = u;
    loop {
        len += 1;
        n >>= 7;
        if n == 0 { break; }
    }
    len
}

// ── Encoder ─────────────────────────────────────────────────────────────────

fn encode_value(value: &Value, buf: &mut Vec<u8>) {
    match value {
        Value::Null => buf.push(TAG_NULL),

        Value::Bool(b) => {
            buf.push(TAG_BOOL);
            buf.push(if *b { 1 } else { 0 });
        }

        Value::Number(n) => {
            // Preserve integer vs float distinction
            if let Some(i) = n.as_i64() {
                if serde_json::Number::from(i) == *n {
                    buf.push(TAG_INT);
                    encode_i64_leb128(i, buf);
                    return;
                }
            }
            // Fallback: encode as f64
            buf.push(TAG_FLOAT);
            let f = n.as_f64().unwrap_or(0.0);
            buf.extend_from_slice(&f64::to_le_bytes(f));
        }

        Value::String(s) => {
            if let Some(id) = dict::lookup_fast(s) {
                buf.push(TAG_STR_DICT);
                buf.push(id);
            } else {
                buf.push(TAG_STR_RAW);
                encode_hyb128_bytes(s.as_bytes(), buf);
            }
        }

        Value::Array(arr) => {
            buf.push(TAG_ARRAY);
            encode_hyb128_len(arr.len(), buf);
            for v in arr {
                encode_value(v, buf);
            }
        }

        Value::Object(map) => {
            buf.push(TAG_OBJECT);
            encode_hyb128_len(map.len(), buf);
            for (k, v) in map {
                encode_key(k, buf);
                encode_value(v, buf);
            }
        }
    }
}

fn encode_key(key: &str, buf: &mut Vec<u8>) {
    if let Some(id) = dict::lookup_fast(key) {
        buf.push(id);
    } else {
        buf.push(dict::ID_RAW);
        encode_hyb128_bytes(key.as_bytes(), buf);
    }
}

fn encode_hyb128_len(n: usize, buf: &mut Vec<u8>) {
    let mut len_buf = [0u8; hyb128::MAX_ENCODED_LEN];
    let encoded = hyb128::encode(n as u64, &mut len_buf);
    buf.extend_from_slice(&len_buf[..encoded]);
}

fn encode_hyb128_bytes(data: &[u8], buf: &mut Vec<u8>) {
    encode_hyb128_len(data.len(), buf);
    buf.extend_from_slice(data);
}

/// Encode i64 as signed LEB128 (zigzag style: sign bit as LSB).
fn encode_i64_leb128(v: i64, buf: &mut Vec<u8>) {
    // Zigzag encode: map signed to unsigned
    let mut u = ((v >> 63) as u64) ^ ((v as u64) << 1);
    loop {
        let mut byte = (u & 0x7F) as u8;
        u >>= 7;
        if u != 0 {
            byte |= 0x80;
        }
        buf.push(byte);
        if u == 0 {
            break;
        }
    }
}

/// Decode signed LEB128 from bytes starting at `pos`. Advances `pos`.
fn decode_i64_leb128(data: &[u8], pos: &mut usize) -> Option<i64> {
    let mut u: u64 = 0;
    let mut shift = 0u32;
    loop {
        if *pos >= data.len() {
            return None;
        }
        let byte = data[*pos];
        *pos += 1;
        u |= ((byte & 0x7F) as u64) << shift;
        if byte & 0x80 == 0 {
            break;
        }
        shift += 7;
        if shift >= 64 {
            return None; // overflow
        }
    }
    // Zigzag decode
    let v = (u >> 1) as i64 ^ -((u & 1) as i64);
    Some(v)
}

// ── Decoder ─────────────────────────────────────────────────────────────────

fn decode_value(data: &[u8], pos: &mut usize) -> Option<Value> {
    if *pos >= data.len() {
        return None;
    }
    let tag = data[*pos];
    *pos += 1;

    match tag {
        TAG_NULL => Some(Value::Null),

        TAG_BOOL => {
            if *pos >= data.len() { return None; }
            let b = data[*pos] != 0;
            *pos += 1;
            Some(Value::Bool(b))
        }

        TAG_FLOAT => {
            if *pos + 8 > data.len() { return None; }
            let bytes: [u8; 8] = data[*pos..*pos + 8].try_into().ok()?;
            *pos += 8;
            let f = f64::from_le_bytes(bytes);
            Number::from_f64(f).map(Value::Number)
        }

        TAG_INT => {
            let i = decode_i64_leb128(data, pos)?;
            Some(Value::Number(Number::from(i)))
        }

        TAG_STR_DICT => {
            if *pos >= data.len() { return None; }
            let id = data[*pos];
            *pos += 1;
            dict::resolve(id).map(|s| Value::String(s.to_owned()))
        }

        TAG_STR_RAW => {
            let len = hyb128::decode(&data[*pos..])?;
            *pos += len.header_len;
            let v = len.value as usize;
            if *pos + v > data.len() { return None; }
            let bytes = &data[*pos..*pos + v];
            *pos += v;
            let s = String::from_utf8(bytes.to_vec()).ok()?;
            Some(Value::String(s))
        }

        TAG_ARRAY => {
            let len = hyb128::decode(&data[*pos..])?;
            *pos += len.header_len;
            let mut arr = Vec::with_capacity((len.value as usize).min(1024));
            for _ in 0..len.value {
                arr.push(decode_value(data, pos)?);
            }
            Some(Value::Array(arr))
        }

        TAG_OBJECT => {
            let len = hyb128::decode(&data[*pos..])?;
            *pos += len.header_len;
            let mut map = serde_json::Map::with_capacity((len.value as usize).min(1024));
            for _ in 0..len.value {
                let key = decode_key(data, pos)?;
                let val = decode_value(data, pos)?;
                map.insert(key, val);
            }
            Some(Value::Object(map))
        }

        _ => {
            // Unknown tag or key ID in value position — malformed
            None
        }
    }
}

fn decode_key(data: &[u8], pos: &mut usize) -> Option<String> {
    if *pos >= data.len() {
        return None;
    }
    let first = data[*pos];
    *pos += 1;

    if first == dict::ID_RAW {
        let len = hyb128::decode(&data[*pos..])?;
        *pos += len.header_len;
        let v = len.value as usize;
        if *pos + v > data.len() { return None; }
        let bytes = &data[*pos..*pos + v];
        *pos += v;
        String::from_utf8(bytes.to_vec()).ok()
    } else if first < dict::STATIC_MAX {
        dict::resolve(first).map(|s| s.to_owned())
    } else {
        // Session-range IDs not yet supported; treat as malformed for now.
        // In the future, look up in the session dictionary.
        None
    }
}

// ── Tests ───────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn roundtrip(v: Value) {
        let comp = compress(&v);
        let decomp = decompress(&comp);
        assert_eq!(Some(v.clone()), decomp, "roundtrip failed for {v:?}");
    }

    fn compressed_lt_json(v: Value, expected_sav_pct: f64) {
        let json_bytes = serde_json::to_vec(&v).unwrap();
        let comp_bytes = compress(&v);
        let ratio = comp_bytes.len() as f64 / json_bytes.len() as f64;
        println!(
            "  JSON={}  LUMEN={}  ratio={:.1}%  (target <{:.0}%)",
            json_bytes.len(),
            comp_bytes.len(),
            ratio * 100.0,
            (1.0 - expected_sav_pct) * 100.0,
        );
        assert!(
            ratio <= (1.0 - expected_sav_pct),
            "expected ≤{}% but got {:.1}%",
            (1.0 - expected_sav_pct) * 100.0,
            ratio * 100.0,
        );
    }

    #[test]
    fn roundtrip_null() {
        roundtrip(Value::Null);
    }

    #[test]
    fn roundtrip_bool() {
        roundtrip(Value::Bool(true));
        roundtrip(Value::Bool(false));
    }

    #[test]
    fn roundtrip_number() {
        roundtrip(json!(42));
        roundtrip(json!(-3.14));
        roundtrip(json!(0));
    }

    #[test]
    fn roundtrip_small_object() {
        roundtrip(json!({"tool": "search", "arguments": {"query": "test"}}));
    }

    #[test]
    fn roundtrip_array() {
        roundtrip(json!(["one", "two", "three"]));
    }

    #[test]
    fn roundtrip_nested() {
        roundtrip(json!({
            "tools": [
                {"name": "search", "description": "search the web"},
                {"name": "fetch", "description": "fetch a URL"}
            ],
            "count": 2
        }));
    }

    #[test]
    fn compression_beats_json_for_known_keys() {
        let v = json!({
            "tool": "search",
            "arguments": {"query": "hello world", "limit": 10}
        });
        // JSON: ~80 bytes, LUMEN compact: keys are 1-byte each → much smaller
        compressed_lt_json(v, 0.30); // at least 30% savings
    }

    #[test]
    fn compression_on_tools_list() {
        let tools: Vec<Value> = (0..100).map(|i| {
            json!({
                "name": format!("tool_{i}"),
                "description": format!("Tool number {i} for doing things"),
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The search query"
                        },
                        "limit": {
                            "type": "integer",
                            "default": 20
                        }
                    },
                    "required": ["query"]
                }
            })
        }).collect();
        let response = json!({
            "tools": tools,
            "total": 100
        });
        let json_bytes = serde_json::to_vec(&response).unwrap();
        let comp_bytes = compress(&response);
        let ratio = comp_bytes.len() as f64 / json_bytes.len() as f64;
        println!(
            "  tools_list(100): JSON={}  LUMEN={}  ratio={:.1}%",
            json_bytes.len(),
            comp_bytes.len(),
            ratio * 100.0,
        );
        assert!(ratio < 0.70, "Expected <70% but got {:.1}%", ratio * 100.0);
    }

    #[test]
    fn decompress_truncated_is_none() {
        let comp = compress(&json!({"tool": "search"}));
        // Truncate to half
        assert_eq!(decompress(&comp[..comp.len() / 2]), None);
    }

    #[test]
    fn decompress_garbage_is_none() {
        assert_eq!(decompress(&[0xFF, 0xFF, 0xFF, 0xFF]), None);
    }

    #[test]
    fn dict_strings_value_position() {
        // Strings used as values that happen to be in the dict
        // "tool" = 0x00 as key AND as value → TAG_STR_DICT(0x00)
        roundtrip(json!({"result": "tool"}));
    }

    #[test]
    fn raw_keys_roundtrip() {
        // Keys NOT in the dictionary must roundtrip via ID_RAW path
        roundtrip(json!({"customThing": 42, "anotherOne": "hello"}));
    }
}
