/// Fuzz target: compress → decompress roundtrip + panic-safety on arbitrary bytes.
///
/// Two strategies:
/// 1. Feed arbitrary bytes to `decompress()` — must never panic, just return `None`.
/// 2. Build a valid JSON value from fuzz data, compress it, decompress it, verify
///    the roundtrip preserves equality.

use libfuzzer_sys::fuzz_target;
use lumen::compress;
use serde_json::{json, Value};

fuzz_target!(|data: &[u8]| {
    // ── Strategy 1: panic-safety on arbitrary bytes ────────────────────
    let _ = compress::decompress(data);

    // ── Strategy 2: build JSON from fuzz data, compress→decompress ─────
    if data.len() >= 2 {
        let json_val = build_json_from_bytes(data);
        let compressed = compress::compress(&json_val);

        // Decompress must recover the original value
        match compress::decompress(&compressed) {
            Some(recovered) => {
                assert_eq!(
                    recovered, json_val,
                    "compress→decompress roundtrip mismatch.\nOriginal: {json_val}\nRecovered: {recovered}"
                );
            }
            None => {
                panic!(
                    "decompress failed on freshly-compressed data.\nOriginal JSON: {json_val}\nCompressed bytes: {compressed:?}"
                );
            }
        }

        // compressed_size must match actual compressed length
        let estimated = compress::compressed_size(&json_val);
        assert_eq!(
            estimated, compressed.len(),
            "compressed_size mismatch: estimated {estimated}, actual {}",
            compressed.len()
        );
    }
});

/// Build a deterministic but varied JSON value from arbitrary bytes.
///
/// Uses the first byte to choose the value type and the rest as content.
fn build_json_from_bytes(data: &[u8]) -> Value {
    if data.is_empty() {
        return Value::Null;
    }

    match data[0] % 24 {
        0 => Value::Null,
        1 => Value::Bool(data[0] & 1 == 0),
        2 => {
            // f64 from bytes
            let mut arr = [0u8; 8];
            let len = data.len().min(9) - 1;
            arr[..len].copy_from_slice(&data[1..1 + len]);
            let f = f64::from_le_bytes(arr);
            json!(f)
        }
        3 => {
            // i64 from bytes
            let mut arr = [0u8; 8];
            let len = data.len().min(9) - 1;
            arr[..len].copy_from_slice(&data[1..1 + len]);
            json!(i64::from_le_bytes(arr))
        }
        4 => {
            // String from bytes (sanitized to valid UTF-8)
            let raw = &data[1..];
            let s = String::from_utf8_lossy(raw).into_owned();
            Value::String(s)
        }
        5 => {
            // Array with 0-5 elements
            let count = (data[0] as usize % 6).min(data.len().saturating_sub(1));
            let mut arr = Vec::with_capacity(count);
            let chunk = data[1..].len() / count.max(1);
            for i in 0..count {
                let start = 1 + i * chunk;
                let end = (start + chunk).min(data.len());
                if start < data.len() {
                    arr.push(build_json_from_bytes(&data[start..end]));
                }
            }
            if arr.is_empty() {
                arr.push(Value::Bool(true)); // avoid empty array from edge case
            }
            Value::Array(arr)
        }
        6 => {
            // Object with 1-3 entries
            let count = ((data[0] as usize % 3) + 1).min(data.len().saturating_sub(1));
            let mut map = serde_json::Map::with_capacity(count);
            let chunk = data[1..].len() / (count * 2).max(1);
            for i in 0..count {
                let key_start = 1 + i * 2 * chunk;
                let key_end = (key_start + chunk).min(data.len());
                let val_start = key_end;
                let val_end = (val_start + chunk).min(data.len());

                let key = if key_start < data.len() {
                    sanitize_key(&String::from_utf8_lossy(&data[key_start..key_end]))
                } else {
                    format!("k{i}")
                };

                let val = if val_start < data.len() {
                    build_json_from_bytes(&data[val_start..val_end])
                } else {
                    Value::Null
                };

                map.insert(key, val);
            }
            Value::Object(map)
        }
        // 7-23: mix of the above, distribute evenly
        n => {
            // Alternate between string, integer, and small object
            match n % 6 {
                0 => Value::Null,
                1 => Value::Bool(true),
                2 => json!(data[0] as i64),
                3 => {
                    let s = String::from_utf8_lossy(&data[1..]).into_owned();
                    Value::String(s)
                }
                _ => {
                    let mut map = serde_json::Map::new();
                    map.insert("k".to_string(), json!(data[0] as i64));
                    Value::Object(map)
                }
            }
        }
    }
}

/// Ensure the key is valid for the dict (no empty, reasonable length).
fn sanitize_key(raw: &str) -> String {
    let s = raw.chars().take(64).collect::<String>();
    if s.is_empty() { "key".to_string() } else { s }
}
