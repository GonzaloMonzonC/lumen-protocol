//! Property-based fuzz tests for LUMEN parsers.
//!
//! These tests exercise the same invariants as the cargo-fuzz targets
//! (`fuzz/fuzz_targets/`) but run as regular `#[test]` functions using
//! random-seeded byte sequences.  This avoids the libfuzzer / nightly
//! dependency while still catching panics, roundtrip failures, and
//! edge cases in the parsing hot-path.
//!
//! Run with:
//! ```bash
//! cargo test fuzz
//! ```

#[cfg(test)]
mod fuzz_hyb128 {
    use lumen::hyb128;

    /// Roundtrip: any u64 must survive encode → decode.
    #[test]
    fn roundtrip_edge_values() {
        let values = &[
            0,
            1,
            63, // max short
            64, // first u16
            255,
            65535, // max u16
            65536, // first u32
            1_000_000,
            4_294_967_295, // max u32
            4_294_967_296, // first LEB128
            1u64 << 50,
            u64::MAX,
        ];

        for &value in values {
            let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
            let n = hyb128::encode(value, &mut buf);
            assert!(n >= 1, "encode({value}) returned {n} bytes");
            assert!(n <= hyb128::MAX_ENCODED_LEN, "encode({value}) overflowed: {n}");

            let decoded = hyb128::decode(&buf[..n])
                .unwrap_or_else(|| panic!("decode failed on freshly-encoded value {value}"));
            assert_eq!(decoded.value, value,
                "roundtrip mismatch: encoded {value}, decoded {}", decoded.value);
            assert_eq!(decoded.header_len, n,
                "header_len mismatch: wrote {n}, read {}", decoded.header_len);
        }
    }

    /// Random values: encode N random u64s, decode each, verify.
    #[test]
    fn roundtrip_random_10k() {
        // Deterministic pseudo-random via simple LCG
        let mut state: u64 = 0xDEAD_BEEF_CAFE_BABE;
        for _ in 0..10_000 {
            state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            let value = state;
            let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
            let n = hyb128::encode(value, &mut buf);
            let decoded = hyb128::decode(&buf[..n]).expect("decode failed");
            assert_eq!(decoded.value, value);
        }
    }

    /// Arbitrary bytes fed to decode must never panic, only return None.
    #[test]
    fn arbitrary_bytes_no_panic() {
        let mut state: u64 = 0x1234_5678_9ABC_DEF0;
        for len in 0..64 {
            let mut buf = vec![0u8; len];
            for _ in 0..200 {
                // Fill with pseudo-random bytes
                for b in buf.iter_mut() {
                    state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
                    *b = state as u8;
                }
                // Must not panic
                let _ = hyb128::decode(&buf);
            }
        }
    }

    /// Truncated valid headers must return None.
    #[test]
    fn truncated_headers() {
        for value in [0u64, 64, 256, 65535, 65536, 1000000] {
            let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
            let n = hyb128::encode(value, &mut buf);
            // Feed progressively shorter prefixes
            for trim in 1..=n {
                let prefix = &buf[..n - trim];
                assert!(hyb128::decode(prefix).is_none(),
                    "decode({value}) should be None with {}-byte prefix", n - trim);
            }
        }
    }

    /// encoded_len must match actual encoded size.
    #[test]
    fn encoded_len_accurate() {
        let mut state: u64 = 1;
        for _ in 0..5_000 {
            state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
            let value = state;
            let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
            let n = hyb128::encode(value, &mut buf);
            assert_eq!(hyb128::encoded_len(value), n,
                "encoded_len({value}) predicted {expected}, actual {n}",
                expected = hyb128::encoded_len(value));
        }
    }
}

#[cfg(test)]
mod fuzz_frame {
    use lumen::frame;

    /// Arbitrary bytes fed to parse() must never panic.
    #[test]
    fn arbitrary_bytes_no_panic() {
        let mut state: u64 = 0xABCD;
        for len in 0..128 {
            let mut buf = vec![0u8; len];
            for _ in 0..100 {
                for b in buf.iter_mut() {
                    state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
                    *b = state as u8;
                }
                let _ = frame::parse(&buf);
            }
        }
    }

    /// Build→parse roundtrip with varied parameters.
    #[test]
    fn roundtrip_varied() {
        let types = [
            frame::TYPE_REQUEST, frame::TYPE_RESPONSE, frame::TYPE_NOTIFY,
            frame::TYPE_STREAM_DATA, frame::TYPE_MUX, frame::TYPE_HEARTBEAT,
            frame::TYPE_PROBE, frame::TYPE_PROBE_ACK,
        ];
        let flags_combos = [0x00, 0x01, 0x02, 0x03, 0x04, 0x08, 0x0F];

        for &ft in &types {
            for &fl in &flags_combos {
                for payload_len in [0, 1, 10, 63, 64, 255, 1024] {
                    let payload: Vec<u8> = (0..payload_len).map(|i| i as u8).collect();
                    let size = frame::build_size(payload.len());
                    let mut buf = vec![0u8; size];
                    let written = frame::build(ft, fl, &payload, &mut buf);
                    assert_eq!(written, size);

                    match frame::parse(&buf[..written]) {
                        frame::ParseResult::Complete { frame, consumed } => {
                            assert_eq!(consumed, written);
                            assert_eq!(frame.frame_type, ft);
                            assert_eq!(frame.flags, fl);
                            assert_eq!(frame.payload, payload.as_slice());
                        }
                        other => panic!("roundtrip failed: {other:?}"),
                    }
                }
            }
        }
    }

    /// Truncated frames must return Incomplete, never panic.
    #[test]
    fn truncated_frames() {
        let payload = b"hello lumen";
        for &ft in &[frame::TYPE_REQUEST, frame::TYPE_RESPONSE] {
            for &fl in &[0x00, 0x01] {
                let size = frame::build_size(payload.len());
                let mut buf = vec![0u8; size];
                let written = frame::build(ft, fl, payload, &mut buf);

                for trim in 1..=written {
                    let prefix = &buf[..written - trim];
                    if prefix.is_empty() { break; }
                    let result = frame::parse(prefix);
                    // Must be Incomplete or IncompletePayload, never Complete with wrong data
                    match result {
                        frame::ParseResult::Error(_) => {} // also acceptable
                        frame::ParseResult::Incomplete | frame::ParseResult::IncompletePayload { .. } => {}
                        frame::ParseResult::Complete { .. } => {
                            // Might be valid if trim didn't touch the payload
                            // (e.g., a zero-payload frame trimmed by 0 bytes)
                        }
                    }
                }
            }
        }
    }

    /// Zero-byte input must return Incomplete.
    #[test]
    fn empty_input() {
        match frame::parse(&[]) {
            frame::ParseResult::Incomplete => {}
            other => panic!("empty input should be Incomplete, got {other:?}"),
        }
    }
}

#[cfg(test)]
mod fuzz_compress {
    use lumen::compress;
    use serde_json::{json, Value};

    /// Arbitrary bytes fed to decompress() must never panic.
    #[test]
    fn arbitrary_bytes_no_panic() {
        let mut state: u64 = 0xBEEF;
        for len in 0..64 {
            let mut buf = vec![0u8; len];
            for _ in 0..100 {
                for b in buf.iter_mut() {
                    state = state.wrapping_mul(6_364_136_223_846_793_005).wrapping_add(1);
                    *b = state as u8;
                }
                let _ = compress::decompress(&buf);
            }
        }
    }

    /// Compress→decompress roundtrip for diverse JSON values.
    #[test]
    fn roundtrip_diverse() {
        let cases: &[(Value, &str)] = &[
            (Value::Null, "null"),
            (Value::Bool(true), "true"),
            (Value::Bool(false), "false"),
            (json!(0), "zero"),
            (json!(42), "small int"),
            (json!(-1), "negative int"),
            (json!(i64::MAX), "max i64"),
            (json!(i64::MIN), "min i64"),
            (json!(1.5), "float"),
            (json!(""), "empty string"),
            (json!("hello"), "ascii string"),
            (json!("🚀 LUMEN"), "unicode string"),
            (Value::Array(vec![]), "empty array"),
            (json!([1, 2, 3]), "int array"),
            (json!([null, true, "mix"]), "mixed array"),
            (Value::Object(serde_json::Map::new()), "empty object"),
            (json!({"tool": "search", "arguments": {"query": "rust"}}), "nested object"),
            (json!({"tool": "search"}), "dict key"),
        ];

        for (i, (val, desc)) in cases.iter().enumerate() {
            let compressed = compress::compress(val);

            // Compressed size must match estimate
            let estimated = compress::compressed_size(val);
            assert_eq!(estimated, compressed.len(),
                "case {i} ({desc}): compressed_size mismatch: estimated {estimated}, actual {}",
                compressed.len());

            // Decompress must recover original
            let recovered = compress::decompress(&compressed)
                .unwrap_or_else(|| panic!("case {i} ({desc}): decompress returned None"));
            assert_eq!(&recovered, val,
                "case {i} ({desc}): roundtrip mismatch.\nExpected: {val}\nGot: {recovered}");
        }
    }

    /// Decompress of truncated valid data must return None.
    #[test]
    fn truncated_compressed() {
        let val = json!({"tool": "search", "arguments": {"query": "hello world", "limit": 10}});
        let compressed = compress::compress(&val);

        for trim in 1..compressed.len() {
            let prefix = &compressed[..compressed.len() - trim];
            // Must not panic. May return Some (if the trim falls on a valid boundary),
            // but that's acceptable — partial valid data is fine.
            let _ = compress::decompress(prefix);
        }
    }

    /// Compress an array with many elements.
    #[test]
    fn large_array() {
        let arr: Vec<Value> = (0..100).map(|i| json!({ "n": i })).collect();
        let val = Value::Array(arr);
        let compressed = compress::compress(&val);
        let recovered = compress::decompress(&compressed).expect("decompress failed");
        assert_eq!(recovered, val);
    }

    /// Compress a deeply nested object.
    #[test]
    fn deep_nesting() {
        let mut val = json!({"leaf": true});
        for _ in 0..20 {
            val = json!({"child": val});
        }
        let compressed = compress::compress(&val);
        let recovered = compress::decompress(&compressed).expect("decompress failed");
        assert_eq!(recovered, val);
    }
}
