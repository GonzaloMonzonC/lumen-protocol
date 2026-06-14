/// Fuzz target: Hyb128 encode → decode roundtrip + arbitrary byte resilience.
///
/// Runs two strategies:
/// 1. **Roundtrip**: decode arbitrary u64 from fuzz data, encode, decode again, verify.
/// 2. **Panic-safety**: feed arbitrary bytes to `hyb128::decode()` — must never panic.

use libfuzzer_sys::fuzz_target;
use lumen::hyb128;

fuzz_target!(|data: &[u8]| {
    // ── Strategy 1: roundtrip via u64 ──────────────────────────────────
    if data.len() >= 8 {
        let value = u64::from_le_bytes(data[..8].try_into().unwrap());
        let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
        let n = hyb128::encode(value, &mut buf);
        assert!(n >= 1 && n <= hyb128::MAX_ENCODED_LEN, "encode returned invalid length {n}");

        // Decode what we just encoded
        if let Some(decoded) = hyb128::decode(&buf[..n]) {
            assert_eq!(
                decoded.value, value,
                "roundtrip mismatch: encoded {value}, decoded {}",
                decoded.value
            );
            assert_eq!(
                decoded.header_len, n,
                "header_len mismatch: wrote {n}, read {}",
                decoded.header_len
            );
        } else {
            panic!("decode failed on freshly-encoded value {value}");
        }
    }

    // ── Strategy 2: panic-safety on arbitrary bytes ────────────────────
    //
    // `hyb128::decode()` must return `None` for any malformed input,
    // and must NEVER panic regardless of input.
    let _ = hyb128::decode(data);

    // Also exercise encoded_len (const fn, but validate its bound)
    if data.len() >= 8 {
        let value = u64::from_le_bytes(data[..8].try_into().unwrap());
        let elen = hyb128::encoded_len(value);
        assert!(elen >= 1 && elen <= hyb128::MAX_ENCODED_LEN);
    }
});
