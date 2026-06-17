//! LUMEN vs JSON-RPC — IPC End-to-End Latency Benchmark
//!
//! Real TCP loopback (127.0.0.1) round-trip: serialize → send → recv → deserialize.
//! Server echoes every frame back. Measures p50, p99, avg RTT.
//!
//! Run: `cargo run --bin ipc-shootout`

use lumen::compress;
use lumen::fixtures;
use lumen::frame;
use lumen::hyb128;
use std::io::{Read, Write};
use std::net::{TcpListener, TcpStream};
use std::thread;
use std::time::Instant;

// ── Config ──────────────────────────────────────────────────────────────────

const PORT: u16 = 19200;
const WARMUP: usize = 500;
const ITERS: usize = 2000;

// ── JSON-RPC echo server ────────────────────────────────────────────────────

fn json_server() {
    let listener = TcpListener::bind(("127.0.0.1", PORT)).expect("JSON server bind");
    let (mut stream, _) = listener.accept().expect("JSON server accept");

    let mut buf = Vec::with_capacity(64 * 1024);
    let mut tmp = [0u8; 64 * 1024];

    loop {
        buf.clear();
        loop {
            let n = stream.read(&mut tmp).expect("json server read");
            if n == 0 {
                return;
            }
            buf.extend_from_slice(&tmp[..n]);
            if buf.last() == Some(&b'\n') {
                break;
            }
        }
        stream.write_all(&buf).expect("json server write");
        stream.flush().expect("json server flush");
    }
}

// ── LUMEN echo server ───────────────────────────────────────────────────────

fn lumen_server() {
    let listener = TcpListener::bind(("127.0.0.1", PORT + 1)).expect("LUMEN server bind");
    let (mut stream, _) = listener.accept().expect("LUMEN server accept");

    let mut len_buf = [0u8; hyb128::MAX_ENCODED_LEN];

    loop {
        let mut header_pos = 0usize;
        loop {
            let n = stream
                .read(&mut len_buf[header_pos..header_pos + 1])
                .expect("lumen server read len");
            if n == 0 {
                return;
            }
            header_pos += 1;
            if let Some(decoded) = hyb128::decode(&len_buf[..header_pos]) {
                let payload_len = decoded.value as usize;
                let total_frame = payload_len + 2; // + TYPE + FLAGS
                let mut frame_buf = vec![0u8; total_frame];
                stream
                    .read_exact(&mut frame_buf)
                    .expect("lumen server read frame");

                stream
                    .write_all(&len_buf[..header_pos])
                    .expect("lumen server write len");
                stream
                    .write_all(&frame_buf)
                    .expect("lumen server write frame");
                stream.flush().expect("lumen server flush");
                break;
            }
        }
    }
}

// ── JSON-RPC client roundtrip ───────────────────────────────────────────────

fn json_roundtrip(stream: &mut TcpStream, payload: &serde_json::Value) -> u128 {
    let t0 = Instant::now();

    let mut data = serde_json::to_vec(payload).expect("json serialize");
    data.push(b'\n');
    stream.write_all(&data).expect("json client write");
    stream.flush().expect("json client flush");

    let mut buf = Vec::with_capacity(1024);
    let mut tmp = [0u8; 4096];
    loop {
        let n = stream.read(&mut tmp).expect("json client read");
        if n == 0 {
            panic!("json server disconnected");
        }
        buf.extend_from_slice(&tmp[..n]);
        if buf.last() == Some(&b'\n') {
            break;
        }
    }

    let _val: serde_json::Value =
        serde_json::from_slice(&buf[..buf.len() - 1]).expect("json deserialize");

    t0.elapsed().as_nanos()
}

// ── LUMEN client roundtrip ──────────────────────────────────────────────────

fn lumen_roundtrip(stream: &mut TcpStream, payload: &serde_json::Value) -> u128 {
    let t0 = Instant::now();

    let compressed = compress::compress(payload, None);
    let overhead = 1 + 1 + hyb128::MAX_ENCODED_LEN;
    let mut frame_buf = vec![0u8; compressed.len() + overhead];
    let n = frame::build(
        frame::TYPE_RESPONSE,
        frame::FLAG_COMPRESSED,
        &compressed,
        &mut frame_buf,
    );

    stream.write_all(&frame_buf[..n]).expect("lumen client write");
    stream.flush().expect("lumen client flush");

    let mut len_buf = [0u8; hyb128::MAX_ENCODED_LEN];
    let mut header_pos = 0usize;
    let body_len: usize = loop {
        let n = stream
            .read(&mut len_buf[header_pos..header_pos + 1])
            .expect("lumen client read len");
        if n == 0 {
            panic!("lumen server disconnected");
        }
        header_pos += 1;
        if let Some(decoded) = hyb128::decode(&len_buf[..header_pos]) {
            break decoded.value as usize + 2; // + TYPE + FLAGS
        }
    };

    let mut echo_frame = vec![0u8; body_len];
    stream
        .read_exact(&mut echo_frame)
        .expect("lumen client read frame");

    let combined: Vec<u8> = [&len_buf[..header_pos], &echo_frame[..]].concat();
    match frame::parse(&combined) {
        frame::ParseResult::Complete { frame, .. } => {
            let _val = compress::decompress(frame.payload, None).expect("lumen decompress");
        }
        _ => panic!("lumen parse failed"),
    }

    t0.elapsed().as_nanos()
}

// ── Workloads ───────────────────────────────────────────────────────────────

struct Workload {
    name: &'static str,
    payloads: Vec<serde_json::Value>,
}

fn build_workloads() -> Vec<Workload> {
    let mut workloads = Vec::new();

    workloads.push(Workload {
        name: "W1: heartbeat (tiny)",
        payloads: (0..ITERS + WARMUP)
            .map(|_| fixtures::build_heartbeat())
            .collect(),
    });

    {
        let tools = fixtures::generate_tools(1);
        let response = fixtures::build_tools_list_response(&tools);
        workloads.push(Workload {
            name: "W2: tool_call (~400B)",
            payloads: (0..ITERS + WARMUP).map(|_| response.clone()).collect(),
        });
    }

    {
        let tokens = fixtures::generate_llm_tokens(1);
        let tp = serde_json::json!({"token": &tokens[0], "logprob": -0.42});
        workloads.push(Workload {
            name: "W3: llm_token (~75B)",
            payloads: (0..ITERS + WARMUP).map(|_| tp.clone()).collect(),
        });
    }

    {
        let code = fixtures::generate_source_code("rust", 5);
        let fp = serde_json::json!({"file": "/src/lib.rs", "content": code});
        workloads.push(Workload {
            name: "W4: file_chunk (5 KB)",
            payloads: (0..ITERS + WARMUP).map(|_| fp.clone()).collect(),
        });
    }

    // W5: Batched tokens (10 tokens) — streaming scenario
    {
        let tokens = fixtures::generate_llm_tokens(10);
        let batch = serde_json::json!({"tokens": tokens});
        workloads.push(Workload {
            name: "W5: tokens_x10 (batch)",
            payloads: (0..ITERS + WARMUP).map(|_| batch.clone()).collect(),
        });
    }

    workloads
}

// ── Stats ───────────────────────────────────────────────────────────────────

fn percentile(sorted: &[u128], pct: f64) -> f64 {
    if sorted.is_empty() {
        return 0.0;
    }
    let idx = ((sorted.len() - 1) as f64 * pct / 100.0).round() as usize;
    sorted[idx] as f64 / 1000.0
}

// ── Run single protocol ─────────────────────────────────────────────────────

struct IpcRow {
    workload: String,
    json_p50: f64,
    json_p99: f64,
    json_avg: f64,
    json_wire: usize,
    lumen_p50: f64,
    lumen_p99: f64,
    lumen_avg: f64,
    lumen_wire: usize,
}

fn run_protocol(workload: &Workload, is_lumen: bool) -> (Vec<u128>, usize) {
    let port = if is_lumen { PORT + 1 } else { PORT };
    let label = if is_lumen { "LUMEN" } else { "JSON-RPC" };

    let mut stream =
        TcpStream::connect(("127.0.0.1", port)).unwrap_or_else(|_| panic!("{} client connect", label));
    stream.set_nodelay(true).expect("set_nodelay");

    // Warmup
    for i in 0..WARMUP {
        if is_lumen {
            lumen_roundtrip(&mut stream, &workload.payloads[i]);
        } else {
            json_roundtrip(&mut stream, &workload.payloads[i]);
        }
    }

    // Measured iterations
    let mut samples = Vec::with_capacity(ITERS);
    let mut wire_total = 0usize;
    for i in WARMUP..WARMUP + ITERS {
        let ns = if is_lumen {
            let ns = lumen_roundtrip(&mut stream, &workload.payloads[i]);
            let compressed = compress::compress(&workload.payloads[i], None);
            let overhead = 1 + 1 + hyb128::MAX_ENCODED_LEN;
            let mut fb = vec![0u8; compressed.len() + overhead];
            let n = frame::build(frame::TYPE_RESPONSE, frame::FLAG_COMPRESSED, &compressed, &mut fb);
            wire_total += n;
            ns
        } else {
            let data = serde_json::to_vec(&workload.payloads[i]).expect("json ser");
            wire_total += data.len() + 1; // + newline
            json_roundtrip(&mut stream, &workload.payloads[i])
        };
        samples.push(ns);
    }

    samples.sort_unstable();
    (samples, wire_total)
}

// ── Main ────────────────────────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════════════════════════════╗");
    println!("║   LUMEN vs JSON-RPC — IPC End-to-End Latency (TCP Loopback) ║");
    println!("║   {} iterations per workload, {} warmup                      ║", ITERS, WARMUP);
    println!("╚══════════════════════════════════════════════════════════════╝");

    let workloads = build_workloads();
    let mut rows = Vec::new();

    for workload in &workloads {
        println!("\n═══ {} ═══", workload.name);

        // JSON server
        let jh = thread::spawn(json_server);
        thread::sleep(std::time::Duration::from_millis(50));

        let (json_samples, json_wire) = run_protocol(workload, false);
        println!(
            "  JSON-RPC → p50={:.1}µs  p99={:.1}µs  avg={:.1}µs  wire={}/msg",
            percentile(&json_samples, 50.0),
            percentile(&json_samples, 99.0),
            json_samples.iter().sum::<u128>() as f64 / ITERS as f64 / 1000.0,
            fmt_bytes(json_wire / ITERS),
        );

        drop(jh);
        thread::sleep(std::time::Duration::from_millis(100));

        // LUMEN server
        let lh = thread::spawn(lumen_server);
        thread::sleep(std::time::Duration::from_millis(50));

        let (lumen_samples, lumen_wire) = run_protocol(workload, true);
        println!(
            "  LUMEN    → p50={:.1}µs  p99={:.1}µs  avg={:.1}µs  wire={}/msg",
            percentile(&lumen_samples, 50.0),
            percentile(&lumen_samples, 99.0),
            lumen_samples.iter().sum::<u128>() as f64 / ITERS as f64 / 1000.0,
            fmt_bytes(lumen_wire / ITERS),
        );

        drop(lh);
        thread::sleep(std::time::Duration::from_millis(100));

        rows.push(IpcRow {
            workload: workload.name.to_string(),
            json_p50: percentile(&json_samples, 50.0),
            json_p99: percentile(&json_samples, 99.0),
            json_avg: json_samples.iter().sum::<u128>() as f64 / ITERS as f64 / 1000.0,
            json_wire: json_wire / ITERS,
            lumen_p50: percentile(&lumen_samples, 50.0),
            lumen_p99: percentile(&lumen_samples, 99.0),
            lumen_avg: lumen_samples.iter().sum::<u128>() as f64 / ITERS as f64 / 1000.0,
            lumen_wire: lumen_wire / ITERS,
        });
    }

    // ── Summary ──────────────────────────────────────────────────
    println!("\n\n╔══════════════════════════════════════════════════════════════════════════════════════════════════════════════════════╗");
    println!("║                              LUMEN vs JSON-RPC — IPC END-TO-END LATENCY (TCP loopback, nodelay)                     ║");
    println!("╠══════════════════════════════╤══════════╤══════════╤══════════╤══════════╤══════════╤══════════╤══════════╤══════════╣");
    println!("║ Workload                     │ JSON p50 │ LUMEN p50│ JSON p99 │ LUMEN p99│ JSON avg │ LUMEN avg│ JSON wire│ LUM wire ║");
    println!("╠══════════════════════════════╪══════════╪══════════╪══════════╪══════════╪══════════╪══════════╪══════════╪══════════╣");

    for row in &rows {
        let speedup = if row.lumen_avg > 0.0 {
            row.json_avg / row.lumen_avg
        } else {
            0.0
        };
        let wire_save = if row.json_wire > 0 {
            (1.0 - row.lumen_wire as f64 / row.json_wire as f64) * 100.0
        } else {
            0.0
        };
        println!(
            "║ {:<28} │ {:>7.0}µs │ {:>7.0}µs │ {:>7.0}µs │ {:>7.0}µs │ {:>7.0}µs │ {:>7.0}µs │ {:>7} │ {:>7} ║",
            row.workload,
            row.json_p50, row.lumen_p50,
            row.json_p99, row.lumen_p99,
            row.json_avg, row.lumen_avg,
            fmt_bytes(row.json_wire), fmt_bytes(row.lumen_wire),
        );
        println!(
            "║ {:<28} │ {:>7.1}× speedup │ {:.0}% wire saved                                                            ║",
            "", speedup, wire_save,
        );
    }
    println!("╚══════════════════════════════╧══════════╧══════════╧══════════╧══════════╧══════════╧══════════╧══════════╧══════════╝");
}

// ── Formatting ──────────────────────────────────────────────────────────────

fn fmt_bytes(b: usize) -> String {
    if b >= 1024 * 1024 {
        format!("{:.1}MB", b as f64 / (1024.0 * 1024.0))
    } else if b >= 1024 {
        format!("{:.1}KB", b as f64 / 1024.0)
    } else {
        format!("{}B", b)
    }
}
