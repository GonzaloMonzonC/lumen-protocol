/// Fuzz target: frame::parse() panic-safety + frame build → parse roundtrip.
///
/// Two strategies:
/// 1. Feed arbitrary bytes to `frame::parse()` — it must never panic, only return
///    `Incomplete`, `IncompletePayload`, `Error`, or `Complete`.
/// 2. Build a valid frame with fuzz-derived parameters, then parse it back.

use libfuzzer_sys::fuzz_target;
use lumen::frame;

fuzz_target!(|data: &[u8]| {
    // ── Strategy 1: panic-safety on arbitrary bytes ────────────────────
    let result = frame::parse(data);
    // The result is just a value — existence of any variant is fine.
    // We just need to ensure this call never panics.
    let _ = result;

    // ── Strategy 2: roundtrip with fuzz-derived parameters ─────────────
    if data.len() >= 3 {
        let frame_type = data[0];
        let flags = data[1];

        // Use up to 4KB of fuzz data as payload (keep sizes reasonable)
        let payload_len = (data[2] as usize).min(data.len().saturating_sub(3)).min(4096);
        let payload = &data[3..3 + payload_len];

        // Build a frame
        let size = frame::build_size(payload.len());
        let mut buf = vec![0u8; size];
        let written = frame::build(frame_type, flags, payload, &mut buf);
        assert_eq!(written, size, "build returned {written}, expected {size}");

        // Parse it back
        match frame::parse(&buf[..written]) {
            frame::ParseResult::Complete { frame, consumed } => {
                assert_eq!(consumed, written, "parse consumed {consumed}, expected {written}");
                assert_eq!(frame.frame_type, frame_type,
                    "type mismatch: sent {frame_type}, got {}", frame.frame_type);
                assert_eq!(frame.flags, flags,
                    "flags mismatch: sent {flags}, got {}", frame.flags);
                assert_eq!(frame.payload, payload,
                    "payload mismatch: len {} vs {}", frame.payload.len(), payload.len());
            }
            other => {
                panic!("parse failed on freshly-built frame: {other:?}");
            }
        }
    }

    // ── Strategy 3: truncated frame resilience ─────────────────────────
    //
    // Take the first N bytes of a valid frame and feed them to parse.
    // This must never panic and should return Incomplete/IncompletePayload.
    if data.len() >= 6 {
        let frame_type = data[0];
        let flags = data[1];
        let payload = b"fuzz";
        let size = frame::build_size(payload.len());
        let mut buf = vec![0u8; size];
        let written = frame::build(frame_type, flags, payload, &mut buf);

        // Feed progressively shorter prefixes
        for trim in 1..=written {
            let prefix = &buf[..written.saturating_sub(trim)];
            if prefix.is_empty() { break; }
            let _ = frame::parse(prefix);
        }
    }
});
