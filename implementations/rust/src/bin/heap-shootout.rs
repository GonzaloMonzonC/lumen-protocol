//! LUMEN vs JSON-RPC — Heap Allocation Shootout
//!
//! Measures: total allocations, total bytes allocated, peak heap usage.
//! Uses a custom `#[global_allocator]` with atomic counters — zero deps.
//!
//! Run: `cargo run --bin heap-shootout`

use lumen::compress;
use lumen::fixtures;
use lumen::frame;
use lumen::hyb128;
use serde_json;
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicU64, Ordering};

// ── Counting Allocator ─────────────────────────────────────────────────────

static ALLOC_COUNT: AtomicU64 = AtomicU64::new(0);
static DEALLOC_COUNT: AtomicU64 = AtomicU64::new(0);
static ALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
static DEALLOC_BYTES: AtomicU64 = AtomicU64::new(0);
static PEAK_BYTES: AtomicU64 = AtomicU64::new(0);

struct CountingAllocator;

unsafe impl GlobalAlloc for CountingAllocator {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        ALLOC_COUNT.fetch_add(1, Ordering::Relaxed);
        let size = layout.size() as u64;
        let prev = ALLOC_BYTES.fetch_add(size, Ordering::Relaxed);
        let dealloc = DEALLOC_BYTES.load(Ordering::Relaxed);
        let current = (prev + size).saturating_sub(dealloc);
        // Track peak (best-effort, non-atomic across the two operations)
        let peak = PEAK_BYTES.load(Ordering::Relaxed);
        if current > peak {
            PEAK_BYTES.store(current, Ordering::Relaxed);
        }
        System.alloc(layout)
    }

    unsafe fn dealloc(&self, ptr: *mut u8, layout: Layout) {
        DEALLOC_COUNT.fetch_add(1, Ordering::Relaxed);
        DEALLOC_BYTES.fetch_add(layout.size() as u64, Ordering::Relaxed);
        System.dealloc(ptr, layout)
    }
}

#[global_allocator]
static GLOBAL: CountingAllocator = CountingAllocator;

// ── Snapshot ────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, Copy)]
struct AllocSnapshot {
    allocs: u64,
    #[allow(dead_code)]
    deallocs: u64,
    bytes_alloced: u64,
    #[allow(dead_code)]
    bytes_dealloced: u64,
    peak: u64,
}

impl AllocSnapshot {
    fn take() -> Self {
        AllocSnapshot {
            allocs: ALLOC_COUNT.swap(0, Ordering::Relaxed),
            deallocs: DEALLOC_COUNT.swap(0, Ordering::Relaxed),
            bytes_alloced: ALLOC_BYTES.swap(0, Ordering::Relaxed),
            bytes_dealloced: DEALLOC_BYTES.swap(0, Ordering::Relaxed),
            peak: PEAK_BYTES.swap(0, Ordering::Relaxed),
        }
    }

    #[allow(dead_code)]
    fn net_allocs(&self) -> u64 {
        self.allocs.saturating_sub(self.deallocs)
    }

    #[allow(dead_code)]
    fn leaked_bytes(&self) -> u64 {
        self.bytes_alloced.saturating_sub(self.bytes_dealloced)
    }

    fn peak_kb(&self) -> f64 {
        self.peak as f64 / 1024.0
    }
}

// ── Helpers ─────────────────────────────────────────────────────────────────

fn json_roundtrip(v: &serde_json::Value) {
    let data = serde_json::to_vec(v).expect("JSON serialize");
    let _val: serde_json::Value = serde_json::from_slice(&data).expect("JSON parse");
}

fn lumen_roundtrip(v: &serde_json::Value) {
    // Single allocation: pre-size with worst-case frame overhead, compress into tail
    let compressed = compress::compress(v);
    let frame_overhead = 1 + 1 + hyb128::MAX_ENCODED_LEN; // FLAGS + TYPE + max Hyb128
    let mut buf = vec![0u8; compressed.len() + frame_overhead];
    let n = frame::build(frame::TYPE_RESPONSE, frame::FLAG_COMPRESSED, &compressed, &mut buf);
    match frame::parse(&buf[..n]) {
        frame::ParseResult::Complete { frame, .. } => {
            let _val = compress::decompress(frame.payload).expect("LUMEN decompress");
        }
        _ => panic!("LUMEN parse"),
    }
}

// ── Run helpers ─────────────────────────────────────────────────────────────

/// Amortize fixed costs by running N iterations, then average.
const ITERS: u64 = 100;

struct HeapRow {
    scenario: &'static str,
    json_allocs: u64,
    lumen_allocs: u64,
    json_bytes: u64,
    lumen_bytes: u64,
    json_peak: f64,
    lumen_peak: f64,
}

fn run_scenario(name: &'static str, payload: &serde_json::Value) -> HeapRow {
    println!("\n═══ {name} (×{ITERS} iters) ═══");

    // ── JSON-RPC ─────────────────────────────────────────────────
    AllocSnapshot::take(); // drain startup
    AllocSnapshot::take(); // reset

    for _ in 0..ITERS {
        json_roundtrip(payload);
    }

    let json_snap = AllocSnapshot::take();
    println!(
        "  JSON-RPC  → allocs={:<6}  bytes={:<10}  peak={:.1} KB",
        fmt_count_u64(json_snap.allocs / ITERS),
        fmt_bytes_u64(json_snap.bytes_alloced / ITERS),
        json_snap.peak_kb(),
    );

    // ── LUMEN ─────────────────────────────────────────────────────
    AllocSnapshot::take(); // reset

    for _ in 0..ITERS {
        lumen_roundtrip(payload);
    }

    let lumen_snap = AllocSnapshot::take();
    println!(
        "  LUMEN     → allocs={:<6}  bytes={:<10}  peak={:.1} KB",
        fmt_count_u64(lumen_snap.allocs / ITERS),
        fmt_bytes_u64(lumen_snap.bytes_alloced / ITERS),
        lumen_snap.peak_kb(),
    );

    HeapRow {
        scenario: name,
        json_allocs: json_snap.allocs / ITERS,
        lumen_allocs: lumen_snap.allocs / ITERS,
        json_bytes: json_snap.bytes_alloced / ITERS,
        lumen_bytes: lumen_snap.bytes_alloced / ITERS,
        json_peak: json_snap.peak_kb(),
        lumen_peak: lumen_snap.peak_kb(),
    }
}

// ── Main ────────────────────────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════════════════════╗");
    println!("║   LUMEN vs JSON-RPC — Heap Allocation Shootout       ║");
    println!("║   Custom #[global_allocator] with atomic counters    ║");
    println!("╚══════════════════════════════════════════════════════╝");

    // Drain the alloc counters from program startup
    AllocSnapshot::take();

    let mut rows = Vec::new();

    // S1: tools/list — 1000 tools
    {
        let tools = fixtures::generate_tools(1000);
        let response = fixtures::build_tools_list_response(&tools);
        rows.push(run_scenario("S1: tools/list (1000 tools)", &response));
    }

    // S2: file_context — 50 files × 100KB
    {
        let files: Vec<_> = (0..50)
            .map(|i| {
                (
                    format!("/home/user/project/src/module_{}/lib.rs", i),
                    fixtures::generate_source_code("rust", 100),
                )
            })
            .collect();
        let payload = fixtures::build_file_context_payload(&files);
        rows.push(run_scenario("S2: file_context (5 MB)", &payload));
    }

    // S3: token_stream — 1000 tokens streamed
    {
        let tokens = fixtures::generate_llm_tokens(1000);
        let payload = serde_json::json!({ "tokens": tokens });
        rows.push(run_scenario("S3: token_stream (1K tokens)", &payload));
    }

    // S4: multi_agent — 10 agents × 100 requests
    {
        let requests = fixtures::generate_agent_requests(10, 100);
        let payload = serde_json::json!({ "requests": requests });
        rows.push(run_scenario("S4: multi_agent (1K reqs)", &payload));
    }

    // S5: heartbeat — single frame
    {
        let heartbeat = fixtures::build_heartbeat();
        rows.push(run_scenario("S5: heartbeat (1 frame)", &heartbeat));
    }

    // ── Summary ──────────────────────────────────────────────────
    println!("\n\n╔══════════════════════════════════════════════════════════════════════════════════════════════════════════╗");
    println!("║                           LUMEN vs JSON-RPC — HEAP ALLOCATIONS (×{ITERS} iter avg)                      ║");
    println!("╠══════════════════════════════════════╤═══════════╤═══════════╤══════════════╤══════════════╤══════════╤══════════╣");
    println!("║ Scenario (per iteration)             │ JSON alloc│ LUMEN allo│ Alloc Ratio  │ Bytes Ratio  │ JSON peak│ LUM peak ║");
    println!("╠══════════════════════════════════════╪═══════════╪═══════════╪══════════════╪══════════════╪══════════╪══════════╣");

    for row in &rows {
        let alloc_ratio = if row.lumen_allocs > 0 {
            row.json_allocs as f64 / row.lumen_allocs as f64
        } else {
            0.0
        };
        let bytes_ratio = if row.lumen_bytes > 0 {
            row.json_bytes as f64 / row.lumen_bytes as f64
        } else {
            0.0
        };
        println!(
            "║ {:<38} │ {:>8}  │ {:>8}  │ {:>6.1}× LUMEN │ {:>6.1}× LUMEN │ {:>7.0}K │ {:>7.0}K ║",
            row.scenario,
            fmt_count_u64(row.json_allocs),
            fmt_count_u64(row.lumen_allocs),
            alloc_ratio,
            bytes_ratio,
            row.json_peak,
            row.lumen_peak,
        );
    }
    println!("╚══════════════════════════════════════╧═══════════╧═══════════╧══════════════╧══════════════╧══════════╧══════════╝");
}

// ── Formatting ──────────────────────────────────────────────────────────────

fn fmt_count_u64(n: u64) -> String {
    if n >= 1_000_000 {
        format!("{:.1}M", n as f64 / 1_000_000.0)
    } else if n >= 1_000 {
        format!("{:.1}K", n as f64 / 1_000.0)
    } else {
        n.to_string()
    }
}

fn fmt_bytes_u64(b: u64) -> String {
    if b >= 1024 * 1024 {
        format!("{:.1} MB", b as f64 / (1024.0 * 1024.0))
    } else if b >= 1024 {
        format!("{:.1} KB", b as f64 / 1024.0)
    } else {
        format!("{} B", b)
    }
}
