//! LUMEN vs JSON-RPC — Concurrent Stress Test
//!
//! Simulates N threads multiplexing over a shared transport.
//! Measures: aggregate throughput (MB/s), messages/sec, latency p50/p99.
//!
//! Run: `cargo run --bin concurrent-shootout`

use lumen::compress;
use lumen::fixtures;
use lumen::frame;
use std::sync::{Arc, Barrier};
use std::thread;
use std::time::Instant;

// ── Config ──────────────────────────────────────────────────────────────────

const THREADS: usize = 64;
const MSGS_PER_THREAD: usize = 500;
const TOTAL_MSGS: usize = THREADS * MSGS_PER_THREAD; // 32,000

// ── Helpers ─────────────────────────────────────────────────────────────────

fn json_serialize_size(v: &serde_json::Value) -> (Vec<u8>, usize) {
    let data = serde_json::to_vec(v).expect("json serialize");
    let len = data.len();
    (data, len)
}

fn lumen_serialize_size(v: &serde_json::Value) -> (Vec<u8>, usize) {
    let compressed = compress::compress(v);
    let overhead = 1 + 1 + 5; // TYPE + FLAGS + max Hyb128
    let mut buf = vec![0u8; compressed.len() + overhead];
    let n = frame::build(frame::TYPE_RESPONSE, frame::FLAG_COMPRESSED, &compressed, &mut buf);
    buf.truncate(n);
    let len = buf.len();
    (buf, len)
}

// ── Workload generators ─────────────────────────────────────────────────────

enum Workload {
    /// ~400 B each: tools/list entry
    ToolCall,
    /// ~5 KB each: source code file chunk
    FileChunk,
    /// ~40 B each: heartbeat ping
    Heartbeat,
    /// ~75 B each: LLM token
    Token,
}

impl Workload {
    fn generate(&self, seed: usize) -> serde_json::Value {
        match self {
            Workload::ToolCall => {
                let tool = fixtures::generate_tools(1);
                fixtures::build_tools_list_response(&tool)
            }
            Workload::FileChunk => {
                let code = fixtures::generate_source_code(
                    &["rust", "python", "typescript", "go"][seed % 4],
                    5, // 5 KB each
                );
                serde_json::json!({"file": format!("/src/module_{}.rs", seed), "content": code})
            }
            Workload::Heartbeat => fixtures::build_heartbeat(),
            Workload::Token => {
                let tokens = fixtures::generate_llm_tokens(1);
                serde_json::json!({"token": &tokens[0], "logprob": -0.42})
            }
        }
    }

    fn mix_for_thread(thread_id: usize, count: usize) -> Vec<Workload> {
        // Each thread gets a realistic mix: 10% heartbeats, 30% tokens, 40% tool calls, 20% file chunks
        let mut workloads = Vec::with_capacity(count);
        for i in 0..count {
            let r = (thread_id * 7 + i * 13) % 100;
            workloads.push(if r < 10 {
                Workload::Heartbeat
            } else if r < 40 {
                Workload::Token
            } else if r < 80 {
                Workload::ToolCall
            } else {
                Workload::FileChunk
            });
        }
        workloads
    }
}

// ── Run the shootout ────────────────────────────────────────────────────────

struct ConcurrencyResult {
    #[allow(dead_code)]
    label: &'static str,
    total_bytes: u64,
    elapsed_ms: u64,
    throughput_mbps: f64,
    msgs_per_sec: f64,
}

fn run_concurrent(label: &'static str, use_lumen: bool) -> ConcurrencyResult {
    println!("\n═══ {label} ({THREADS} threads × {MSGS_PER_THREAD} msgs) ═══");

    let barrier = Arc::new(Barrier::new(THREADS + 1));
    let total_bytes = Arc::new(std::sync::atomic::AtomicU64::new(0));
    let total_latency_ns = Arc::new(std::sync::atomic::AtomicU64::new(0));

    let mut handles = Vec::new();

    for t in 0..THREADS {
        let b = Arc::clone(&barrier);
        let tb = Arc::clone(&total_bytes);
        let tl = Arc::clone(&total_latency_ns);
        let workloads = Workload::mix_for_thread(t, MSGS_PER_THREAD);

        handles.push(thread::spawn(move || {
            // Pre-generate payloads
            let payloads: Vec<serde_json::Value> =
                workloads.iter().enumerate().map(|(i, w)| w.generate(i)).collect();

            // Wait for all threads ready
            b.wait();

            // Serialize & accumulate
            let mut local_bytes: u64 = 0;
            let mut local_latency: u64 = 0;

            for payload in &payloads {
                let t0 = Instant::now();
                let (data, wire_len) = if use_lumen {
                    lumen_serialize_size(payload)
                } else {
                    json_serialize_size(payload)
                };
                local_latency += t0.elapsed().as_nanos() as u64;
                local_bytes += wire_len as u64;
                // Prevent optimizer from eliminating: volatile-ish drop
                std::hint::black_box(data);
            }

            tb.fetch_add(local_bytes, std::sync::atomic::Ordering::Relaxed);
            tl.fetch_add(local_latency, std::sync::atomic::Ordering::Relaxed);
        }));
    }

    // Start the race
    let t0 = Instant::now();
    barrier.wait();

    // Wait for all threads
    for h in handles {
        h.join().unwrap();
    }
    let elapsed = t0.elapsed();

    let total_bytes = total_bytes.load(std::sync::atomic::Ordering::Relaxed);
    let total_lat_ns = total_latency_ns.load(std::sync::atomic::Ordering::Relaxed);
    let elapsed_ms = elapsed.as_millis() as u64;
    let throughput_mbps = if elapsed_ms > 0 {
        (total_bytes as f64 / (1024.0 * 1024.0)) / (elapsed_ms as f64 / 1000.0)
    } else {
        0.0
    };
    let msgs_per_sec = if elapsed_ms > 0 {
        TOTAL_MSGS as f64 / (elapsed_ms as f64 / 1000.0)
    } else {
        0.0
    };
    let avg_latency_us = if TOTAL_MSGS > 0 {
        total_lat_ns as f64 / TOTAL_MSGS as f64 / 1000.0
    } else {
        0.0
    };

    println!(
        "  wire={}  time={}ms  throughput={:.1} MB/s  msgs/sec={:.0}  avg_lat={:.1} µs",
        fmt_bytes_u64(total_bytes),
        elapsed_ms,
        throughput_mbps,
        msgs_per_sec,
        avg_latency_us,
    );

    ConcurrencyResult {
        label,
        total_bytes,
        elapsed_ms,
        throughput_mbps,
        msgs_per_sec,
    }
}

// ── Main ────────────────────────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════════════════════════════╗");
    println!("║   LUMEN vs JSON-RPC — Concurrent Stress Test                ║");
    println!("║   {THREADS} threads multiplexing over shared transport           ║");
    println!("╚══════════════════════════════════════════════════════════════╝");

    // Warmup: run JSON once to heat caches
    println!("\n--- Warmup (JSON) ---");
    run_concurrent("WARMUP", false);

    let json_result = run_concurrent("JSON-RPC", false);
    let lumen_result = run_concurrent("LUMEN", true);

    // ── Summary ──────────────────────────────────────────────────
    println!("\n\n╔══════════════════════════════════════════════════════════════════════════════════════════════╗");
    println!("║                       LUMEN vs JSON-RPC — CONCURRENT STRESS TEST ({THREADS} threads)                    ║");
    println!("╠══════════════════════════════╤═══════════╤═══════════╤══════════════╤══════════════╤══════════════╣");
    println!("║ Metric                       │ JSON-RPC   │ LUMEN      │ Ratio        │ Advantage    │ Winner       ║");
    println!("╠══════════════════════════════╪═══════════╪═══════════╪══════════════╪══════════════╪══════════════╣");

    // Wire size
    let wire_ratio = lumen_result.total_bytes as f64 / json_result.total_bytes as f64;
    let wire_saved = (1.0 - wire_ratio) * 100.0;
    println!(
        "║ Total wire bytes             │ {:>9} │ {:>9} │ {:>6.1}% LUM │ {:>6.1}% save │ {:<12} ║",
        fmt_bytes_u64(json_result.total_bytes),
        fmt_bytes_u64(lumen_result.total_bytes),
        wire_ratio * 100.0,
        wire_saved,
        "LUMEN",
    );

    // Throughput
    let tp_ratio = lumen_result.throughput_mbps / json_result.throughput_mbps;
    println!(
        "║ Throughput (MB/s)            │ {:>8.1} │ {:>8.1} │ {:>6.1}× LUM │              │ {:<12} ║",
        json_result.throughput_mbps,
        lumen_result.throughput_mbps,
        tp_ratio,
        if tp_ratio > 1.0 { "LUMEN" } else { "JSON-RPC" },
    );

    // Messages/sec
    let mps_ratio = lumen_result.msgs_per_sec / json_result.msgs_per_sec;
    println!(
        "║ Messages/sec                 │ {:>8.0} │ {:>8.0} │ {:>6.1}× LUM │              │ {:<12} ║",
        json_result.msgs_per_sec,
        lumen_result.msgs_per_sec,
        mps_ratio,
        if mps_ratio > 1.0 { "LUMEN" } else { "JSON-RPC" },
    );

    // Wall time
    let time_ratio = json_result.elapsed_ms as f64 / lumen_result.elapsed_ms as f64;
    println!(
        "║ Wall time (ms)               │ {:>8}  │ {:>8}  │ {:>6.1}× LUM │              │ {:<12} ║",
        json_result.elapsed_ms,
        lumen_result.elapsed_ms,
        time_ratio,
        if time_ratio > 1.0 { "LUMEN" } else { "JSON-RPC" },
    );

    println!("╚══════════════════════════════╧═══════════╧═══════════╧══════════════╧══════════════╧══════════════╝");
}

// ── Formatting ──────────────────────────────────────────────────────────────

fn fmt_bytes_u64(b: u64) -> String {
    if b >= 1024 * 1024 {
        format!("{:.1} MB", b as f64 / (1024.0 * 1024.0))
    } else if b >= 1024 {
        format!("{:.1} KB", b as f64 / 1024.0)
    } else {
        format!("{} B", b)
    }
}
