//! LUMEN vs JSON-RPC Shootout — Standalone Benchmark Binary
//!
//! Five real-world MCP scenarios, head-to-head.
//! Measures: wire size (bytes), serialize time, parse time.
//!
//! Run: `cargo run --bin shootout`

use lumen::compress;
use lumen::fixtures;
use lumen::frame;
use serde_json;
use std::time::Instant;

// ── Helpers ─────────────────────────────────────────────────────────────────

fn json_serialize(v: &serde_json::Value) -> Vec<u8> {
    serde_json::to_vec(v).expect("JSON serialization failed")
}

fn json_parse(data: &[u8]) -> serde_json::Value {
    serde_json::from_slice(data).expect("JSON parse failed")
}

/// LUMEN serialize: compress JSON → frame.
fn lumen_serialize(frame_type: u8, flags: u8, payload_value: &serde_json::Value) -> Vec<u8> {
    let compressed = compress::compress(payload_value);
    let mut buf = vec![0u8; frame::build_size(compressed.len())];
    let n = frame::build(frame_type, flags, &compressed, &mut buf);
    buf.truncate(n);
    buf
}

/// LUMEN parse: parse frame → decompress → JSON.
fn lumen_parse(data: &[u8]) -> (u8, u8, serde_json::Value) {
    match frame::parse(data) {
        frame::ParseResult::Complete { frame, .. } => {
            let value = compress::decompress(frame.payload)
                .expect("LUMEN decompress failed");
            (frame.frame_type, frame.flags, value)
        }
        _ => panic!("LUMEN parse failed"),
    }
}

// ── Timing helper ───────────────────────────────────────────────────────────

#[allow(dead_code)]
struct ResultRow {
    scenario: &'static str,
    json_wire: usize,
    lumen_wire: usize,
    json_ser_ns: f64,
    lumen_ser_ns: f64,
    json_deser_ns: f64,
    lumen_deser_ns: f64,
}

const WARMUP: u32 = 20;
const ITERS: u32 = 200;

fn time<F, R>(label: &str, iterations: u32, mut f: F) -> (f64, R)
where
    F: FnMut() -> R,
{
    // Warmup
    for _ in 0..WARMUP {
        let _ = f();
    }
    let start = Instant::now();
    let mut last = None;
    for _ in 0..iterations {
        last = Some(f());
    }
    let elapsed = start.elapsed();
    let ns_per = elapsed.as_nanos() as f64 / iterations as f64;
    println!("  {label}: {ns_per:.0} ns/op  (×{iterations} iters, {elapsed:.2?} total)");
    (ns_per, last.unwrap())
}

fn wire(label: &str, bytes: usize) {
    if bytes >= 1024 * 1024 {
        println!("  {label}: {} bytes ({:.2} MB)", bytes, bytes as f64 / (1024.0 * 1024.0));
    } else {
        println!("  {label}: {} bytes ({:.2} KB)", bytes, bytes as f64 / 1024.0);
    }
}

fn fmt_bytes(b: usize) -> String {
    if b >= 1024 * 1024 {
        format!("{:.2} MB", b as f64 / (1024.0 * 1024.0))
    } else if b >= 1024 {
        format!("{:.2} KB", b as f64 / 1024.0)
    } else {
        format!("{} B", b)
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 1: tools/list — 1000 tool definitions
// ═══════════════════════════════════════════════════════════════════════════════

fn run_s1() -> ResultRow {
    println!("\n═══ S1: tools/list — 1000 tool definitions ═══");
    let tools = fixtures::generate_tools(1000);
    let response = fixtures::build_tools_list_response(&tools);

    println!("--- JSON-RPC ---");
    let (json_ser_ns, json_data) = time("serialize", ITERS, || json_serialize(&response));
    wire("wire size", json_data.len());
    let json_wire = json_data.len();
    let (json_deser_ns, _) = time("parse    ", ITERS, || json_parse(&json_data));

    println!("--- LUMEN ---");
    let (lumen_ser_ns, lumen_data) = time(
        "serialize",
        ITERS,
        || lumen_serialize(frame::TYPE_RESPONSE, frame::FLAG_COMPRESSED, &response),
    );
    wire("wire size", lumen_data.len());
    let lumen_wire = lumen_data.len();
    let (lumen_deser_ns, _) = time("parse    ", ITERS, || lumen_parse(&lumen_data));

    ResultRow {
        scenario: "S1: tools/list (1000 tools)",
        json_wire,
        lumen_wire,
        json_ser_ns,
        lumen_ser_ns,
        json_deser_ns,
        lumen_deser_ns,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 2: file_context — 50 files × 100KB = 5MB
// ═══════════════════════════════════════════════════════════════════════════════

fn run_s2() -> ResultRow {
    println!("\n═══ S2: file_context — 50 files × 100KB (5MB) ═══");
    let files: Vec<_> = (0..50)
        .map(|i| {
            (
                format!("/home/user/project/src/module_{}/lib.rs", i),
                fixtures::generate_source_code("rust", 100),
            )
        })
        .collect();
    let payload = fixtures::build_file_context_payload(&files);

    let n = ITERS / 10;

    println!("--- JSON-RPC ---");
    let (json_ser_ns, json_data) = time("serialize", n, || json_serialize(&payload));
    wire("wire size", json_data.len());
    let json_wire = json_data.len();
    let (json_deser_ns, _) = time("parse    ", n, || json_parse(&json_data));

    println!("--- LUMEN ---");
    let (lumen_ser_ns, lumen_data) = time(
        "serialize",
        n,
        || lumen_serialize(frame::TYPE_RESPONSE, frame::FLAG_COMPRESSED, &payload),
    );
    wire("wire size", lumen_data.len());
    let lumen_wire = lumen_data.len();
    let (lumen_deser_ns, _) = time("parse    ", n, || lumen_parse(&lumen_data));

    ResultRow {
        scenario: "S2: file_context (5 MB)",
        json_wire,
        lumen_wire,
        json_ser_ns,
        lumen_ser_ns,
        json_deser_ns,
        lumen_deser_ns,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 3: token_stream — 10K tokens
// ═══════════════════════════════════════════════════════════════════════════════

fn run_s3() -> ResultRow {
    println!("\n═══ S3: token_stream — 10K tokens streamed ═══");
    let tokens = fixtures::generate_llm_tokens(10_000);
    let n = tokens.len();

    println!("--- JSON-RPC (batched 10K) ---");
    let start = Instant::now();
    let mut json_wire = 0usize;
    for token in &tokens {
        let frame = serde_json::json!({
            "jsonrpc": "2.0",
            "method": "notifications/token",
            "params": { "token": token }
        });
        let data = json_serialize(&frame);
        json_wire += data.len();
    }
    let elapsed = start.elapsed();
    let json_ser_ns = elapsed.as_nanos() as f64 / n as f64;
    println!("  serialize: {json_ser_ns:.0} ns/op  (×{n} iters, {elapsed:.2?} total)");
    wire("total wire", json_wire);
    wire("avg wire  ", json_wire / n);

    println!("--- LUMEN (batched 10K) ---");
    let start = Instant::now();
    let mut lumen_wire = 0usize;
    for token in &tokens {
        let data = lumen_serialize(
            frame::TYPE_STREAM_DATA,
            0,
            &serde_json::json!({ "token": token }),
        );
        lumen_wire += data.len();
    }
    let elapsed = start.elapsed();
    let lumen_ser_ns = elapsed.as_nanos() as f64 / n as f64;
    println!("  serialize: {lumen_ser_ns:.0} ns/op  (×{n} iters, {elapsed:.2?} total)");
    wire("total wire", lumen_wire);
    wire("avg wire  ", lumen_wire / n);

    ResultRow {
        scenario: "S3: token_stream (10K tokens)",
        json_wire,
        lumen_wire,
        json_ser_ns,
        lumen_ser_ns,
        json_deser_ns: 0.0,
        lumen_deser_ns: 0.0,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 4: multi_agent — 10 agents × 100 requests = 1000
// ═══════════════════════════════════════════════════════════════════════════════

fn run_s4() -> ResultRow {
    println!("\n═══ S4: multi_agent — 10 agents × 100 requests (1000 total) ═══");
    let requests = fixtures::generate_agent_requests(10, 100);
    let n = requests.len();

    println!("--- JSON-RPC ---");
    let start = Instant::now();
    let mut json_wire = 0usize;
    for req in &requests {
        json_wire += json_serialize(req).len();
    }
    let elapsed = start.elapsed();
    let json_ser_ns = elapsed.as_nanos() as f64 / n as f64;
    println!("  serialize: {json_ser_ns:.0} ns/op  (×{n} iters, {elapsed:.2?} total)");
    wire("total wire", json_wire);

    println!("--- LUMEN ---");
    let start = Instant::now();
    let mut lumen_wire = 0usize;
    for req in &requests {
        lumen_wire += lumen_serialize(frame::TYPE_REQUEST, frame::FLAG_COMPRESSED, req).len();
    }
    let elapsed = start.elapsed();
    let lumen_ser_ns = elapsed.as_nanos() as f64 / n as f64;
    println!("  serialize: {lumen_ser_ns:.0} ns/op  (×{n} iters, {elapsed:.2?} total)");
    wire("total wire", lumen_wire);

    ResultRow {
        scenario: "S4: multi_agent (1K reqs)",
        json_wire,
        lumen_wire,
        json_ser_ns,
        lumen_ser_ns,
        json_deser_ns: 0.0,
        lumen_deser_ns: 0.0,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 5: heartbeat — 100K heartbeats (minimal overhead)
// ═══════════════════════════════════════════════════════════════════════════════

fn run_s5() -> ResultRow {
    println!("\n═══ S5: heartbeat — 100K heartbeats ═══");
    let heartbeat = fixtures::build_heartbeat();
    let n = 100_000u64;

    println!("--- JSON-RPC ---");
    let start = Instant::now();
    for _ in 0..n {
        let data = json_serialize(&heartbeat);
        let _ = data;
    }
    let elapsed = start.elapsed();
    let json_ser_ns = elapsed.as_nanos() as f64 / n as f64;
    println!("  serialize: {json_ser_ns:.0} ns/op  (×{n} iters, {elapsed:.2?} total)");

    let json_one = json_serialize(&heartbeat).len();
    wire("wire size (1)", json_one);
    wire("wire size (×1M)", json_one * 1_000_000);

    println!("--- LUMEN ---");
    let start = Instant::now();
    for _ in 0..n {
        let data = lumen_serialize(frame::TYPE_HEARTBEAT, frame::FLAG_PRIORITY, &heartbeat);
        let _ = data;
    }
    let elapsed = start.elapsed();
    let lumen_ser_ns = elapsed.as_nanos() as f64 / n as f64;
    println!("  serialize: {lumen_ser_ns:.0} ns/op  (×{n} iters, {elapsed:.2?} total)");

    let lumen_one = lumen_serialize(frame::TYPE_HEARTBEAT, frame::FLAG_PRIORITY, &heartbeat).len();
    wire("wire size (1)", lumen_one);
    wire("wire size (×1M)", lumen_one * 1_000_000);

    ResultRow {
        scenario: "S5: heartbeat (100K)",
        json_wire: json_one,
        lumen_wire: lumen_one,
        json_ser_ns,
        lumen_ser_ns,
        json_deser_ns: 0.0,
        lumen_deser_ns: 0.0,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// Summary table
// ═══════════════════════════════════════════════════════════════════════════════

fn print_summary(rows: &[ResultRow]) {
    println!("\n\n╔══════════════════════════════════════════════════════════════════════════════════════╗");
    println!("║                         LUMEN vs JSON-RPC — RESULTS SUMMARY                        ║");
    println!("╠════════════════════════════════════════╤═══════════╤═══════════╤══════════╤═════════╣");
    println!("║ Scenario                               │ JSON wire │ LUMEN wire│ Sav%     │ Speedup ║");
    println!("╠════════════════════════════════════════╪═══════════╪═══════════╪══════════╪═════════╣");

    for row in rows {
        let wire_sav = if row.json_wire > 0 {
            (1.0 - row.lumen_wire as f64 / row.json_wire as f64) * 100.0
        } else {
            0.0
        };
        let speedup = if row.lumen_ser_ns > 0.0 && row.json_ser_ns > 0.0 {
            row.json_ser_ns / row.lumen_ser_ns
        } else {
            0.0
        };
        println!(
            "║ {:<42} │ {:>8}  │ {:>8}  │ {:>5.1}%  │ {:>5.2}×  ║",
            row.scenario,
            fmt_bytes(row.json_wire),
            fmt_bytes(row.lumen_wire),
            wire_sav,
            speedup,
        );
    }
    println!("╚════════════════════════════════════════╧═══════════╧═══════════╧══════════╧═════════╝");
}

// ── Main ────────────────────────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════════════════════╗");
    println!("║   LUMEN vs JSON-RPC  —  Protocol Shootout Benchmark  ║");
    println!("║   WARMUP={WARMUP} iters,  MEASURE={ITERS} iters                 ║");
    println!("╚══════════════════════════════════════════════════════╝");

    let mut rows = Vec::new();
    rows.push(run_s1());
    rows.push(run_s2());
    rows.push(run_s3());
    rows.push(run_s4());
    rows.push(run_s5());
    print_summary(&rows);
}
