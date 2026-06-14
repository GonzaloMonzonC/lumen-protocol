//! LUMEN Level 3 — Datagram Shootout Benchmark
//!
//! Benchmarks the DatagramTransport:
//!   1. UDP roundtrip latency for various payload sizes
//!   2. Unidirectional throughput (MB/s)
//!   3. Multicast fanout (N receivers)
//!   4. Heartbeat ping-pong (smallest possible frames)
//!   5. Frame parse overhead (build → send → recv → parse)
//!
//! Run: `cargo run --bin dgram-shootout`

use lumen::datagram::{self, DatagramTransport, MAX_FRAME_PAYLOAD};
use lumen::frame;
use std::io;
use std::thread;
use std::time::{Duration, Instant};

const WARMUP: usize = 100;
const ITERS: usize = 1000;

// ── Helpers ─────────────────────────────────────────────────────────────────

fn throughput_mbps(bytes_per_op: usize, ns_per_op: f64) -> f64 {
    (bytes_per_op as f64 / 1_000_000.0) / (ns_per_op / 1_000_000_000.0)
}

/// Build a LUMEN frame for the given frame type and payload.
fn make_frame(ftype: u8, payload: &[u8]) -> Vec<u8> {
    datagram::build_dgram(ftype, 0, payload)
}

/// Parse a received frame, returning (frame_type, payload_len).
fn parse_frame(data: &[u8]) -> Option<(u8, usize)> {
    match frame::parse(data) {
        frame::ParseResult::Complete { frame, .. } => {
            Some((frame.frame_type, frame.payload.len()))
        }
        _ => None,
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 1: UDP Roundtrip Latency (ping-pong)
// ═══════════════════════════════════════════════════════════════════════════════

fn bench_roundtrip() -> io::Result<()> {
    println!();
    println!("═══ S1: UDP Roundtrip Latency (ping-pong) ═══");

    use std::sync::mpsc;

    let payload_sizes = [16, 64, 256, 1024, 4096, 16384, 65500];
    println!("  payload      rtt_ns      throughput    lost");

    for &psize in &payload_sizes {
        let payload = vec![0xAAu8; psize];
        let frame = make_frame(frame::TYPE_HEARTBEAT, &payload);
        let mut lost = 0usize;

        // Spawn echo server on ephemeral port, get address via channel
        let (addr_tx, addr_rx) = mpsc::channel();
        let echo_handle = thread::spawn(move || -> io::Result<()> {
            let mut srv = DatagramTransport::bind("127.0.0.1:0")?;
            addr_tx.send(srv.local_addr()?).unwrap();
            for _ in 0..ITERS + WARMUP {
                loop {
                    let (data_to_echo, src_to_echo) = match srv.recv_frame()? {
                        Some((data, src)) => (data.to_vec(), src),
                        None => { thread::yield_now(); continue; }
                    };
                    srv.send_frame_to(&data_to_echo, src_to_echo)?;
                    break;
                }
            }
            Ok(())
        });

        let server_addr = addr_rx.recv().unwrap();
        let mut client = DatagramTransport::bind("127.0.0.1:0")?;

        // Warmup
        for _ in 0..WARMUP {
            client.send_frame_to(&frame, server_addr)?;
            thread::sleep(Duration::from_millis(1));
            while client.recv_frame()?.is_some() {} // drain
        }

        let t0 = Instant::now();
        for _ in 0..ITERS {
            client.send_frame_to(&frame, server_addr)?;
            // Wait for echo
            loop {
                match client.recv_frame()? {
                    Some((data, _)) => {
                        if let Some((ft, plen)) = parse_frame(data) {
                            if ft == frame::TYPE_HEARTBEAT && plen == psize {
                                break;
                            }
                        }
                    }
                    None => {
                        thread::yield_now();
                        if t0.elapsed() > Duration::from_secs(5) {
                            lost += 1;
                            break;
                        }
                    }
                }
            }
        }
        let elapsed = t0.elapsed();

        // Clean up server
        drop(echo_handle);

        let rtt_ns = elapsed.as_nanos() as f64 / ITERS as f64;
        let tput = throughput_mbps(frame.len(), rtt_ns);

        println!(
            "  {:>6}B   {:>10.0}ns  {:>8.1} MB/s   {:>4}",
            psize, rtt_ns, tput, if lost > 0 { format!("{}", lost) } else { "0".into() }
        );
    }

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 2: Unidirectional Throughput (fire-and-forget)
// ═══════════════════════════════════════════════════════════════════════════════

fn bench_unidirectional() -> io::Result<()> {
    println!();
    println!("═══ S2: Unidirectional Throughput (fire-and-forget) ═══");

    let mut receiver = DatagramTransport::bind("127.0.0.1:0")?;
    let rx_addr = receiver.local_addr()?;
    let sender = DatagramTransport::bind("127.0.0.1:0")?;

    let payload_sizes = [64, 256, 1024, 4096, 16384, 65500];
    println!("  payload      send_ns     recv_ns     throughput    recv_count");

    for &psize in &payload_sizes {
        let payload = vec![0xBBu8; psize];
        let frame = make_frame(frame::TYPE_NOTIFY, &payload);

        // Warmup
        for _ in 0..WARMUP {
            sender.send_frame_to(&frame, rx_addr)?;
            thread::sleep(Duration::from_millis(1));
            while receiver.recv_frame()?.is_some() {} // drain
        }

        // Send benchmark
        let t0 = Instant::now();
        for _ in 0..ITERS {
            sender.send_frame_to(&frame, rx_addr)?;
        }
        let send_elapsed = t0.elapsed();

        // Drain and count received
        thread::sleep(Duration::from_millis(50));
        let mut received = 0usize;
        while receiver.recv_frame()?.is_some() {
            received += 1;
        }

        let send_ns = send_elapsed.as_nanos() as f64 / ITERS as f64;
        let tput = throughput_mbps(frame.len(), send_ns);

        println!(
            "  {:>6}B   {:>10.0}ns  {:>10}   {:>8.1} MB/s   {:>4}/{}",
            psize, send_ns, "—", tput, received, ITERS
        );
    }

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 3: Heartbeat Ping-Pong (smallest frames)
// ═══════════════════════════════════════════════════════════════════════════════

fn bench_heartbeat() -> io::Result<()> {
    println!();
    println!("═══ S3: Heartbeat Ping-Pong (8B payload) ═══");

    use std::sync::mpsc;

    let payload = b"lumen-v3";
    let frame_send = make_frame(frame::TYPE_HEARTBEAT, payload);
    let frame_echo = frame_send.clone();

    // Spawn echo server on ephemeral port, get bound addr via channel
    let (addr_tx, addr_rx) = mpsc::channel();
    let echo_handle = thread::spawn(move || -> io::Result<usize> {
        let mut srv = DatagramTransport::bind("127.0.0.1:0")?;
        addr_tx.send(srv.local_addr()?).unwrap();
        let mut echoed = 0usize;
        for _ in 0..ITERS + WARMUP {
            loop {
                let (data_to_echo, src_to_echo) = match srv.recv_frame()? {
                    Some((data, src)) => (data.to_vec(), src),
                    None => { thread::yield_now(); continue; }
                };
                srv.send_frame_to(&data_to_echo, src_to_echo)?;
                echoed += 1;
                break;
            }
        }
        Ok(echoed)
    });

    let server_addr = addr_rx.recv().unwrap();
    let mut client = DatagramTransport::bind("127.0.0.1:0")?;

    // Warmup
    for _ in 0..WARMUP {
        client.send_frame_to(&frame_send, server_addr)?;
        thread::sleep(Duration::from_millis(1));
        while client.recv_frame()?.is_some() {}
    }

    // Benchmark
    let mut lost = 0usize;
    let t0 = Instant::now();
    for _ in 0..ITERS {
        client.send_frame_to(&frame_send, server_addr)?;
        loop {
            match client.recv_frame()? {
                Some((data, _)) => {
                    if data == frame_echo.as_slice() {
                        break;
                    }
                }
                None => {
                    if t0.elapsed() > Duration::from_secs(3) {
                        lost += 1;
                        break;
                    }
                    thread::yield_now();
                }
            }
        }
    }
    let elapsed = t0.elapsed();

    let _echoed = echo_handle.join().unwrap()?;

    let rtt_ns = elapsed.as_nanos() as f64 / ITERS as f64;
    println!("  frame_size: {} bytes (Hyb128 + TYPE + FLAGS + payload)", frame_send.len());
    println!("  roundtrip:  {:.0} ns/op", rtt_ns);
    println!("  throughput: {:.1} MB/s", throughput_mbps(frame_send.len(), rtt_ns));
    println!("  lost:       {}", lost);
    println!("  wire_bytes: {} B/datagram", frame_send.len() + 28); // +20 IP + 8 UDP

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 4: Frame Parse Overhead (build → send → recv → parse)
// ═══════════════════════════════════════════════════════════════════════════════

fn bench_parse_overhead() -> io::Result<()> {
    println!();
    println!("═══ S4: Frame Parse Overhead ═══");

    let mut rx = DatagramTransport::bind("127.0.0.1:0")?;
    let rx_addr = rx.local_addr()?;
    let tx = DatagramTransport::bind("127.0.0.1:0")?;

    let payload_sizes = [16, 256, 4096, 65500];
    println!("  payload     build_ns    parse_ns    total_ns");

    for &psize in &payload_sizes {
        let payload = vec![0xCCu8; psize];

        // Build + send + recv + parse
        // Warmup
        for _ in 0..WARMUP {
            let f = make_frame(frame::TYPE_NOTIFY, &payload);
            tx.send_frame_to(&f, rx_addr)?;
            thread::sleep(Duration::from_millis(1));
            while let Some((data, _)) = rx.recv_frame()? {
                let _ = parse_frame(data);
            }
        }

        let t0 = Instant::now();
        for _ in 0..ITERS {
            let f = make_frame(frame::TYPE_NOTIFY, &payload);
            tx.send_frame_to(&f, rx_addr)?;
        }
        thread::sleep(Duration::from_millis(20));

        let t1 = Instant::now();
        let mut parsed = 0usize;
        while let Some((data, _)) = rx.recv_frame()? {
            let _ = parse_frame(data);
            parsed += 1;
        }
        let t2 = Instant::now();

        let build_send_ns = t1.duration_since(t0).as_nanos() as f64 / ITERS as f64;
        let recv_parse_ns = t2.duration_since(t1).as_nanos() as f64 / parsed.max(1) as f64;

        println!(
            "  {:>6}B   {:>10.0}ns  {:>10.0}ns  {:>10.0}ns  ({} parsed)",
            psize, build_send_ns, recv_parse_ns, build_send_ns + recv_parse_ns, parsed
        );
    }

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════════
// SCENARIO 5: Max-Payload Stress Test
// ═══════════════════════════════════════════════════════════════════════════════

fn bench_max_payload() -> io::Result<()> {
    println!();
    println!("═══ S5: Max Payload Stress Test ({}B payload) ═══", MAX_FRAME_PAYLOAD);

    let mut rx = DatagramTransport::bind("127.0.0.1:0")?;
    let rx_addr = rx.local_addr()?;
    let tx = DatagramTransport::bind("127.0.0.1:0")?;

    let payload = vec![0xDDu8; MAX_FRAME_PAYLOAD];
    let frame = make_frame(frame::TYPE_NOTIFY, &payload);

    println!("  frame_size: {} bytes", frame.len());
    println!("  udp_size:   {} bytes (datagram)", frame.len() + 28);

    // Warmup
    for _ in 0..10 {
        tx.send_frame_to(&frame, rx_addr)?;
        thread::sleep(Duration::from_millis(5));
        while rx.recv_frame()?.is_some() {}
    }

    let mut ok = 0usize;
    let mut truncated = 0usize;

    let t0 = Instant::now();
    for _ in 0..100 {
        tx.send_frame_to(&frame, rx_addr)?;
    }
    thread::sleep(Duration::from_millis(100));

    while let Some((data, _)) = rx.recv_frame()? {
        if data.len() == frame.len() {
            ok += 1;
        } else {
            truncated += 1;
        }
    }
    let elapsed = t0.elapsed();

    println!("  sent:       100");
    println!("  received:   {} ok + {} truncated", ok, truncated);
    println!("  total_time: {:.2?}", elapsed);
    if ok > 0 {
        let tput = throughput_mbps(frame.len(), elapsed.as_nanos() as f64 / ok as f64);
        println!("  throughput: {:.1} MB/s", tput);
    }

    Ok(())
}

// ═══════════════════════════════════════════════════════════════════════════════
// Main
// ═══════════════════════════════════════════════════════════════════════════════

fn main() -> io::Result<()> {
    println!("╔══════════════════════════════════════════════════════╗");
    println!("║     LUMEN Level 3 — Datagram Shootout               ║");
    println!("║     UDP / Multicast Benchmark                       ║");
    println!("╚══════════════════════════════════════════════════════╝");

    bench_roundtrip()?;
    bench_unidirectional()?;
    bench_heartbeat()?;
    bench_parse_overhead()?;
    bench_max_payload()?;

    println!();
    println!("═══ All scenarios complete ═══");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn roundtrip_smoke() {
        bench_roundtrip().unwrap();
    }

    #[test]
    fn unidirectional_smoke() {
        bench_unidirectional().unwrap();
    }

    #[test]
    fn heartbeat_smoke() {
        bench_heartbeat().unwrap();
    }

    #[test]
    fn parse_overhead_smoke() {
        bench_parse_overhead().unwrap();
    }

    #[test]
    fn max_payload_smoke() {
        bench_max_payload().unwrap();
    }
}
