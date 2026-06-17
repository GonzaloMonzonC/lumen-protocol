//! LUMEN Level 2 — Shared Memory Shootout Benchmark
//!
//! Benchmarks the ShmRingBuffer and ShmTransport:
//!   1. Raw ring buffer throughput (MB/s) for various payload sizes
//!   2. Frame roundtrip latency (write_frame → read_frame)
//!   3. ShmTransport echo benchmark (simulated client↔server)
//!   4. STREAM-like large sequential throughput
//!   5. Cache-line ping-pong (64B payloads)

use std::time::Instant;
use lumen::transport::Transport;

const WARMUP: usize = 200;
const ITERS: usize = 2000;

/// ── Helpers ──────────────────────────────────────────────────────

fn throughput_mbps(bytes_per_op: usize, ns_per_op: f64) -> f64 {
    (bytes_per_op as f64 / 1_000_000.0) / (ns_per_op / 1_000_000_000.0)
}

/// ── Baseline: in-memory Vec channel ──────────────────────────────

struct MemChannel {
    buf: Vec<u8>,
    read_pos: usize,
}

impl MemChannel {
    fn new() -> Self {
        Self { buf: Vec::new(), read_pos: 0 }
    }

    fn write_frame(&mut self, data: &[u8]) {
        self.buf.clear();
        self.buf.extend_from_slice(&(data.len() as u32).to_le_bytes());
        self.buf.extend_from_slice(data);
        self.read_pos = 0;
    }

    fn read_frame(&mut self) -> &[u8] {
        if self.buf.len() < 4 {
            return &[];
        }
        let len_bytes: [u8; 4] = self.buf[..4].try_into().unwrap();
        let len = u32::from_le_bytes(len_bytes) as usize;
        &self.buf[4..4 + len]
    }
}

/// ── Scenario 1: Ring Buffer Frame Throughput ─────────────────────

fn bench_ring_throughput(region_size: usize) {
    println!();
    let data_len = region_size - 128; // header
    let ring_cap = (data_len / 2) - 1; // half per ring, minus 1 for full/empty
    println!("═══ S1: Ring Buffer Frame Throughput (region={} KiB, ring_cap={}B) ═══", region_size / 1024, ring_cap);

    let mut region: Vec<u8> = vec![0u8; region_size];
    lumen::shm::ShmRingBuffer::init_region(region.as_mut_ptr(), region_size);
    let mut frame_buf = Vec::new();

    let payload_sizes = [16, 64, 256, 1024, 4096, 16384, 65536];
    println!("  payload      write_ns     read_ns    throughput    batch");

    for &psize in &payload_sizes {
        let wring = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
        let rring = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
        let payload = vec![0x42u8; psize];
        let frame_size = 4 + psize;
        let batch = (ring_cap / frame_size).max(1).min(ITERS);

        // Warmup
        for _ in 0..WARMUP {
            wring.write_frame(&payload).unwrap();
            frame_buf.clear();
            let _ = rring.read_frame(&mut frame_buf);
        }

        // Write benchmark — batch write, then batch read
        let t0 = Instant::now();
        let mut remaining = ITERS;
        while remaining > 0 {
            let n = batch.min(remaining);
            for _ in 0..n { wring.write_frame(&payload).unwrap(); }
            for _ in 0..n {
                frame_buf.clear();
                let got = rring.read_frame(&mut frame_buf);
                assert!(got.is_ok() && got.unwrap() == psize);
            }
            remaining -= n;
        }
        let total_elapsed = t0.elapsed();
        let total_ns = total_elapsed.as_nanos() as f64;

        // Estimate write/read split: half each (they're interleaved)
        let per_op_ns = total_ns / ITERS as f64;
        let bytes_total = frame_size * ITERS;
        let tput = throughput_mbps(bytes_total, per_op_ns);

        println!("  {:>6}B   {:>10.0}ns  {:>10.0}ns  {:>8.1} MB/s    {:>5}",
            psize, per_op_ns * 0.4, per_op_ns * 0.6, tput, batch);
    }
}

/// ── Scenario 2: Frame Roundtrip (Echo) ───────────────────────────

fn bench_shm_echo(region_size: usize) {
    println!();
    println!("═══ S2: ShmTransport Echo Roundtrip ═══");

    let mut region: Vec<u8> = vec![0u8; region_size];
    lumen::shm::ShmRingBuffer::init_region(region.as_mut_ptr(), region_size);

    // Client: writes to A, reads from B
    let cw = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
    let cr = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::B) };
    let mut client = lumen::transport::ShmTransport::new(cw, cr);

    // Server: writes to B, reads from A
    let sr = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
    let sw = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::B) };
    let mut server = lumen::transport::ShmTransport::new(sw, sr);

    let payload_sizes = [16, 64, 256, 1024, 4096, 16384, 65536];
    println!("  payload        p50        p99        avg");

    for &psize in &payload_sizes {
        let payload = vec![0x42u8; psize];

        // Warmup
        for _ in 0..WARMUP {
            client.write_all(&payload).unwrap();
            let mut tmp = [0u8; 65536 + 4];
            let n = server.read(&mut tmp).unwrap();
            if n > 0 { server.write_all(&tmp[..n]).unwrap(); }
            let mut rbuf = [0u8; 65536 + 4];
            let mut total = 0;
            while total < psize + 4 {
                let n = client.read(&mut rbuf[total..]).unwrap();
                if n == 0 { break; }
                total += n;
            }
        }

        // Measure
        let mut latencies = Vec::with_capacity(ITERS);
        for _ in 0..ITERS {
            let t0 = Instant::now();
            client.write_all(&payload).unwrap();
            let mut tmp = [0u8; 65536 + 4];
            let n = server.read(&mut tmp).unwrap();
            if n > 0 { server.write_all(&tmp[..n]).unwrap(); }
            let mut rbuf = [0u8; 65536 + 4];
            let mut total = 0;
            while total < psize + 4 {
                let n = client.read(&mut rbuf[total..]).unwrap();
                if n == 0 { break; }
                total += n;
            }
            latencies.push(t0.elapsed().as_nanos() as f64);
        }

        latencies.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let p50 = latencies[ITERS / 2];
        let p99 = latencies[(ITERS as f64 * 0.99) as usize];
        let avg = latencies.iter().sum::<f64>() / ITERS as f64;

        println!("  {:>6}B   {:>10.0}ns  {:>10.0}ns  {:>10.0}ns", psize, p50, p99, avg);
    }
}

/// ── Scenario 3: Baseline Memory Channel ──────────────────────────

fn bench_mem_baseline() {
    println!();
    println!("═══ S3: Baseline — In-Memory Channel (no SHM) ═══");
    println!("  payload  roundtrip_ns");

    let payload_sizes = [16, 64, 256, 1024, 4096, 16384, 65536];

    for &psize in &payload_sizes {
        let payload = vec![0x42u8; psize];
        let mut chan = MemChannel::new();

        for _ in 0..WARMUP {
            chan.write_frame(&payload);
            let _ = chan.read_frame();
        }

        let t0 = Instant::now();
        for _ in 0..ITERS {
            chan.write_frame(&payload);
            let _ = chan.read_frame();
        }
        let rt_ns = t0.elapsed().as_nanos() as f64 / ITERS as f64;

        println!("  {:>6}B   {:>12.0}ns", psize, rt_ns);
    }
}

/// ── Scenario 4: STREAM benchmark — large payload throughput ──────

fn bench_stream_throughput(region_size: usize) {
    println!();
    let data_len = region_size - 128;
    let ring_cap = (data_len / 2) - 1;
    println!("═══ S4: STREAM-like — Large sequential writes/reads ═══");

    let mut region: Vec<u8> = vec![0u8; region_size];
    lumen::shm::ShmRingBuffer::init_region(region.as_mut_ptr(), region_size);

    let wring = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
    let rring = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };

    let total_mb: usize = 10;
    let chunk_size: usize = 32768;
    let frame_size = 4 + chunk_size;
    let chunks: usize = (total_mb * 1024 * 1024) / chunk_size;
    let batch_size: usize = (ring_cap / frame_size).max(1);
    let payload = vec![0x7Fu8; chunk_size];
    let mut frame_buf = Vec::new();

    // Warmup
    for _ in 0..WARMUP {
        wring.write_frame(&payload).unwrap();
        frame_buf.clear();
        let _ = rring.read_frame(&mut frame_buf);
    }

    let t0 = Instant::now();
    let mut i = 0;
    while i < chunks {
        let end = (i + batch_size).min(chunks);
        for _ in i..end { wring.write_frame(&payload).unwrap(); }
        for _ in i..end {
            frame_buf.clear();
            let got = rring.read_frame(&mut frame_buf);
            assert!(got.is_ok() && got.unwrap() == chunk_size);
        }
        i = end;
    }
    let elapsed = t0.elapsed();

    let bytes_total = chunks * chunk_size;
    let tput = throughput_mbps(bytes_total, elapsed.as_nanos() as f64 / chunks as f64);

    println!("  total {} MB, {} chunks, chunk {}B, batch {}", total_mb, chunks, chunk_size, batch_size);
    println!("  write+read time: {:?}  ->  {:.1} MB/s", elapsed, tput);
}

/// ── Scenario 5: Cache-line ping-pong ─────────────────────────────

fn bench_ping_pong(region_size: usize) {
    println!();
    println!("═══ S5: Cache-line Ping-Pong (64-byte payloads) ═══");

    let mut region: Vec<u8> = vec![0u8; region_size];
    lumen::shm::ShmRingBuffer::init_region(region.as_mut_ptr(), region_size);

    let cw = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
    let cr = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::B) };
    let sr = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::A) };
    let sw = unsafe { lumen::shm::ShmRingBuffer::from_raw(region.as_mut_ptr(), region_size, lumen::shm::RingSide::B) };

    let payload = vec![0xABu8; 64];

    // Warmup
    for _ in 0..WARMUP {
        cw.write_frame(&payload).unwrap();
        let mut tmp = vec![0u8; 68];
        let n = sr.read(&mut tmp);
        if n >= 68 { sw.write_frame(&payload).unwrap(); }
        let mut out = vec![0u8; 68];
        let _ = cr.read(&mut out);
    }

    // Measure
    let mut latencies = Vec::with_capacity(ITERS);
    for _ in 0..ITERS {
        let t0 = Instant::now();
        cw.write_frame(&payload).unwrap();
        let mut tmp = vec![0u8; 68];
        let n = sr.read(&mut tmp);
        if n >= 68 { sw.write_frame(&payload).unwrap(); }
        let mut out = vec![0u8; 68];
        let _ = cr.read(&mut out);
        latencies.push(t0.elapsed().as_nanos() as f64);
    }

    latencies.sort_by(|a, b| a.partial_cmp(b).unwrap());
    let p50 = latencies[ITERS / 2];
    let p99 = latencies[(ITERS as f64 * 0.99) as usize];
    let avg = latencies.iter().sum::<f64>() / ITERS as f64;

    println!("  p50={:.0}ns  p99={:.0}ns  avg={:.0}ns", p50, p99, avg);
    println!("  -> {:.0} roundtrips/sec", 1_000_000_000.0 / avg);
}

/// ── Main ──────────────────────────────────────────────────────────

fn main() {
    println!("╔══════════════════════════════════════════════════════════════════╗");
    println!("║   LUMEN Level 2 — Shared Memory (SHM) Transport Shootout        ║");
    println!("║   {} warmup, {} iterations per benchmark                         ║", WARMUP, ITERS);
    println!("╚══════════════════════════════════════════════════════════════════╝");

    let region_size = 512 * 1024;

    bench_mem_baseline();
    bench_ring_throughput(region_size);
    bench_shm_echo(region_size);
    bench_stream_throughput(region_size);
    bench_ping_pong(region_size);

    println!();
    println!("═══ DONE ═══");
}
