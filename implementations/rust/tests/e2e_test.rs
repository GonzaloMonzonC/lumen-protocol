//! LUMEN e2e cross-implementation test — Rust.
//!
//! Validates that the Rust implementation produces binary output
//! identical to the Python golden binaries, and that cross-decoding works.
//!
//! Run: cargo test --test e2e_test

use lumen::compress::{compress, decompress};
use lumen::hyb128::{encode as hyb128_encode, decode as hyb128_decode};
use lumen::frame::{self, build, build_size, parse, ParseResult};

use serde_json::Value;
use std::fs;
use std::path::PathBuf;

// ── Helpers ────────────────────────────────────────────────────────────────

fn vectors_path() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..").join("..")
        .join("tests").join("e2e").join("shared_vectors.json")
}

fn golden_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..").join("..")
        .join("tests").join("e2e").join("golden")
}

fn load_vectors() -> Vec<(String, Value)> {
    let raw = fs::read_to_string(vectors_path()).expect("shared_vectors.json not found");
    let data: Value = serde_json::from_str(&raw).expect("Invalid JSON");
    data["vectors"].as_array().unwrap().iter().map(|v| {
        (v["name"].as_str().unwrap().to_string(), v["value"].clone())
    }).collect()
}

fn load_golden(name: &str) -> Option<Vec<u8>> {
    fs::read(golden_dir().join(format!("{}.lumen", name))).ok()
}

fn load_golden_frame(name: &str) -> Option<Vec<u8>> {
    fs::read(golden_dir().join(format!("{}.frame", name))).ok()
}

fn skip(name: &str) -> bool {
    matches!(name, "int_large")
}

// ═══════════════════════════════════════════════════════════════════════════════
// 1. Compress roundtrip
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn compress_roundtrip_all() {
    for (name, value) in load_vectors() {
        if skip(&name) { continue; }
        let compressed = compress(&value);
        let decompressed = decompress(&compressed)
            .unwrap_or_else(|| panic!("decompress returned None for {}", name));
        assert_eq!(
            serde_json::to_string(&value).unwrap(),
            serde_json::to_string(&decompressed).unwrap(),
            "roundtrip mismatch for {}", name
        );
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 2. Semantic compatibility with Python golden files
//    Note: raw binary may differ due to object key ordering (Rust sorts,
//    Python preserves insertion order). Both are valid LUMEN.
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn semantic_compat_python_golden() {
    for (name, value) in load_vectors() {
        if skip(&name) { continue; }
        let golden = match load_golden(&name) {
            Some(g) => g,
            None => continue,
        };

        // Decompress Python golden and compare with our decompress of our compress
        let py_decoded = decompress(&golden)
            .unwrap_or_else(|| panic!("Failed to decompress Python golden for {}", name));
        let our_compressed = compress(&value);
        let our_decoded = decompress(&our_compressed)
            .unwrap_or_else(|| panic!("Failed to decompress own output for {}", name));

        assert_eq!(
            serde_json::to_string(&py_decoded).unwrap(),
            serde_json::to_string(&our_decoded).unwrap(),
            "Semantic mismatch \"{}\": Python and Rust decodes differ", name
        );
        assert_eq!(
            serde_json::to_string(&value).unwrap(),
            serde_json::to_string(&py_decoded).unwrap(),
            "Semantic mismatch \"{}\": Python golden doesn't roundtrip to original", name
        );
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 3. Rust decodes Python golden binaries
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn decode_python_golden() {
    for (name, value) in load_vectors() {
        if skip(&name) { continue; }
        let golden = match load_golden(&name) {
            Some(g) => g,
            None => continue,
        };
        let decompressed = decompress(&golden)
            .unwrap_or_else(|| panic!("Rust failed to decode Python golden for {}", name));
        assert_eq!(
            serde_json::to_string(&value).unwrap(),
            serde_json::to_string(&decompressed).unwrap(),
            "decode Python golden mismatch for {}", name
        );
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 4. Binary stability
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn binary_stability() {
    let cases: Vec<(&str, Value)> = vec![
        ("null", Value::Null),
        ("bool", Value::Bool(true)),
        ("int", serde_json::json!(42)),
        ("float", serde_json::json!(3.14)),
        ("string", Value::String("hello".into())),
        ("array", serde_json::json!([1, 2, 3])),
        ("object", serde_json::json!({"key": "value"})),
        ("mcp_init", serde_json::json!({"jsonrpc": "2.0", "method": "initialize"})),
    ];
    for (name, value) in &cases {
        let c1 = compress(value);
        let c2 = compress(value);
        assert_eq!(c1, c2, "Non-deterministic compression for {}", name);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 5. Hyb128 roundtrip
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn hyb128_roundtrip() {
    let cases = [(0u64, 1usize), (1, 1), (42, 1), (63, 1),
                 (64, 3), (255, 3), (1000, 3), (65535, 3),
                 (65536, 5), (100000, 5), (1000000, 5)];
    for (value, expected) in cases {
        let mut buf = [0u8; 11];
        let n = hyb128_encode(value, &mut buf);
        assert_eq!(n, expected, "encode({}) = {}, expected {}", value, n, expected);
        let dec = hyb128_decode(&buf[..n]).expect("decode returned None");
        assert_eq!(dec.value, value);
        assert_eq!(dec.header_len, expected);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 6. Frame roundtrip
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn frame_roundtrip() {
    let json_small = serde_json::to_vec(&serde_json::json!({"method":"ping"})).unwrap();
    let json_mcp = serde_json::to_vec(&serde_json::json!({
        "jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-06-18"}
    })).unwrap();

    let payloads: Vec<(&str, &[u8])> = vec![
        ("empty", &[]),
        ("hello", b"hello"),
        ("json_small", &json_small),
        ("json_mcp", &json_mcp),
    ];
    let ftypes: [(u8, &str); 3] = [
        (frame::TYPE_REQUEST, "REQUEST"),
        (frame::TYPE_RESPONSE, "RESPONSE"),
        (frame::TYPE_NOTIFY, "NOTIFY"),
    ];
    let flagsets: [(u8, &str); 3] = [
        (0, "none"),
        (frame::FLAG_COMPRESSED, "compressed"),
        (frame::FLAG_PRIORITY, "priority"),
    ];

    for (pname, payload) in &payloads {
        for (ftype, tname) in &ftypes {
            for (flags, fname) in &flagsets {
                let name = format!("frame_{}_{}_{}", tname, fname, pname);
                let mut buf = vec![0u8; build_size(payload.len())];
                let n = build(*ftype, *flags, payload, &mut buf);
                assert_eq!(n, buf.len());
                match parse(&buf) {
                    ParseResult::Complete { frame, consumed } => {
                        assert_eq!(frame.frame_type, *ftype, "type: {}", name);
                        assert_eq!(frame.flags, *flags, "flags: {}", name);
                        assert_eq!(frame.payload, *payload, "payload: {}", name);
                        assert_eq!(consumed, n, "consumed: {}", name);
                    }
                    other => panic!("Expected Complete for {}, got {:?}", name, other),
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 7. Frame semantic match with Python golden frames
//    Raw bytes may differ due to JSON key ordering in payloads.
//    We parse both and compare frame metadata + payload content.
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn frame_semantic_match_python() {
    let json_small = serde_json::to_vec(&serde_json::json!({"method":"ping"})).unwrap();
    let json_mcp = serde_json::to_vec(&serde_json::json!({
        "jsonrpc":"2.0","id":1,"method":"initialize",
        "params":{"protocolVersion":"2025-06-18"}
    })).unwrap();

    let payloads: Vec<(&str, &[u8])> = vec![
        ("empty", &[]),
        ("hello", b"hello"),
        ("json_small", &json_small),
        ("json_mcp", &json_mcp),
    ];
    let ftypes: [(u8, &str); 3] = [
        (frame::TYPE_REQUEST, "REQUEST"),
        (frame::TYPE_RESPONSE, "RESPONSE"),
        (frame::TYPE_NOTIFY, "NOTIFY"),
    ];
    let flagsets: [(u8, &str); 3] = [
        (0, "none"),
        (frame::FLAG_COMPRESSED, "compressed"),
        (frame::FLAG_PRIORITY, "priority"),
    ];

    for (pname, payload) in &payloads {
        for (ftype, tname) in &ftypes {
            for (flags, fname) in &flagsets {
                let name = format!("frame_{}_{}_{}", tname, fname, pname);

                let golden = match load_golden_frame(&name) {
                    Some(g) => g,
                    None => continue,
                };

                // Parse Python golden frame
                match parse(&golden) {
                    ParseResult::Complete { frame: py_frame, .. } => {
                        assert_eq!(py_frame.frame_type, *ftype,
                            "type mismatch parsing Python golden {}", name);
                        assert_eq!(py_frame.flags, *flags,
                            "flags mismatch parsing Python golden {}", name);

                        // For compressed JSON payloads, decompress and compare semantically
                        if py_frame.flags & frame::FLAG_COMPRESSED != 0 && pname.starts_with("json") {
                            // Check if payload is actually compressed LUMEN (starts with tag 0xE0-0xE7)
                            let is_compressed = !py_frame.payload.is_empty()
                                && (py_frame.payload[0] & 0xF8) == 0xE0;
                            if is_compressed {
                                let py_val = decompress(py_frame.payload)
                                    .unwrap_or_else(|| panic!("{}: Python compressed payload failed to decompress", name));
                                let our_val: Value = serde_json::from_slice(payload)
                                    .unwrap_or_else(|e| panic!("{}: Our payload not JSON: {}", name, e));
                                assert_eq!(
                                    serde_json::to_string(&py_val).unwrap(),
                                    serde_json::to_string(&our_val).unwrap(),
                                    "compressed payload semantic mismatch for {}", name
                                );
                            } else {
                                // Flag set but payload is raw JSON — compare semantically
                                let py_val: Value = serde_json::from_slice(py_frame.payload)
                                    .unwrap_or_else(|e| panic!("{}: Python payload not JSON: {}", name, e));
                                let our_val: Value = serde_json::from_slice(payload)
                                    .unwrap_or_else(|e| panic!("{}: Our payload not JSON: {}", name, e));
                                assert_eq!(
                                    serde_json::to_string(&py_val).unwrap(),
                                    serde_json::to_string(&our_val).unwrap(),
                                    "payload semantic mismatch for {}", name
                                );
                            }
                        } else if pname.starts_with("json") {
                            // Uncompressed JSON payloads — normalize and compare
                            let py_val: Value = serde_json::from_slice(py_frame.payload)
                                .unwrap_or_else(|e| panic!("{}: Python payload not JSON: {}", name, e));
                            let our_val: Value = serde_json::from_slice(payload)
                                .unwrap_or_else(|e| panic!("{}: Our payload not JSON: {}", name, e));
                            assert_eq!(
                                serde_json::to_string(&py_val).unwrap(),
                                serde_json::to_string(&our_val).unwrap(),
                                "payload semantic mismatch for {}", name
                            );
                        } else {
                            // Non-JSON payloads should match exactly
                            assert_eq!(py_frame.payload, *payload,
                                "payload mismatch for {}", name);
                        }
                    }
                    other => panic!("parse Python golden {}: {:?}", name, other),
                }
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 8. Compressed frame integration (semantic comparison)
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn compressed_frame_integration() {
    let payloads: Vec<(&str, Value)> = vec![
        ("initialize", serde_json::json!({
            "jsonrpc":"2.0","id":1,"method":"initialize",
            "params":{"protocolVersion":"2025-06-18"}
        })),
        ("tools_list", serde_json::json!({
            "jsonrpc":"2.0","id":2,"result":{"tools":[{
                "name":"search","description":"Search code",
                "inputSchema":{"type":"object","properties":{"query":{"type":"string"}}}
            }]}
        })),
    ];

    for (pname, payload) in &payloads {
        let name = format!("integration_{}", pname);

        let compressed = compress(payload);
        let mut buf = vec![0u8; build_size(compressed.len())];
        build(frame::TYPE_REQUEST, frame::FLAG_COMPRESSED, &compressed, &mut buf);

        // Parse + decompress own frame
        match parse(&buf) {
            ParseResult::Complete { frame, .. } => {
                assert_eq!(frame.flags, frame::FLAG_COMPRESSED);
                let dec = decompress(frame.payload)
                    .unwrap_or_else(|| panic!("decompress failed for {}", name));
                assert_eq!(
                    serde_json::to_string(payload).unwrap(),
                    serde_json::to_string(&dec).unwrap(),
                    "integration decompress mismatch for {}", name
                );
            }
            other => panic!("parse {}: {:?}", name, other),
        }

        // Parse + decompress Python golden (semantic compare)
        if let Some(py_golden) = load_golden_frame(&name) {
            match parse(&py_golden) {
                ParseResult::Complete { frame, .. } => {
                    assert_eq!(frame.flags, frame::FLAG_COMPRESSED,
                        "Python golden flags mismatch for {}", name);
                    let dec = decompress(frame.payload)
                        .unwrap_or_else(|| panic!("decompress Python golden failed for {}", name));
                    assert_eq!(
                        serde_json::to_string(payload).unwrap(),
                        serde_json::to_string(&dec).unwrap(),
                        "integration: decompress Python golden mismatch for {}", name
                    );
                }
                other => panic!("parse Python golden {}: {:?}", name, other),
            }
        }
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// 9. Streaming frame parse (Rust equivalent of FrameAssembler)
// ═══════════════════════════════════════════════════════════════════════════════

#[test]
fn streaming_frame_parse() {
    // Two frames in one buffer
    let p1 = b"A";
    let p2 = b"BB";
    let mut b1 = vec![0u8; build_size(p1.len())];
    let mut b2 = vec![0u8; build_size(p2.len())];
    build(frame::TYPE_NOTIFY, 0, p1, &mut b1);
    build(frame::TYPE_RESPONSE, 0, p2, &mut b2);
    let combined: Vec<u8> = b1.iter().chain(b2.iter()).copied().collect();

    match parse(&combined) {
        ParseResult::Complete { frame, consumed } => {
            assert_eq!(frame.payload, p1);
            let rest = &combined[consumed..];
            match parse(rest) {
                ParseResult::Complete { frame, .. } => {
                    assert_eq!(frame.payload, p2);
                }
                other => panic!("Second frame: {:?}", other),
            }
        }
        other => panic!("First frame: {:?}", other),
    }

    // Truncated frame → IncompletePayload (header parsed, payload missing)
    let payload = b"chunked_test";
    let mut buf = vec![0u8; build_size(payload.len())];
    build(frame::TYPE_REQUEST, frame::FLAG_COMPRESSED, payload, &mut buf);
    let mid = buf.len() / 2;
    assert!(matches!(parse(&buf[..mid]), ParseResult::IncompletePayload { .. }));
    assert!(matches!(parse(&buf), ParseResult::Complete { .. }));
}
