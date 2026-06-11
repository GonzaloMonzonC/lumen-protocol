//! LUMEN vs JSON-RPC — Workspace Indexing Shootout
//!
//! Simulates Cadencia's core workload: reading an entire project directory
//! and preparing file contents for an MCP server. Compares JSON-RPC
//! serialization (serde_json + MCP envelope) against LUMEN binary frames.
//!
//! Run: `cargo run --bin workspace-shootout [directory]`
//! Default directory: the LUMEN source tree itself.
//!
//! This is the benchmark that powers the "Cadencia indexes 5K files in 1.2s
//! vs 10.9s with JSON-RPC" narrative.

use lumen::{compress, frame, hyb128};
use std::time::Instant;

// ── Workspace Scanner ────────────────────────────────────────────────────────

struct WorkspaceFile {
    path: String,
    content: Vec<u8>,
    size: usize,
}

/// Walk `root` collecting all text-like files (source code, config, docs).
fn scan_workspace(root: &str) -> Vec<WorkspaceFile> {
    let mut files = Vec::new();
    let text_extensions = [
        "rs", "toml", "md", "json", "ts", "js", "tsx", "jsx", "py", "go",
        "c", "cpp", "h", "hpp", "java", "kt", "swift", "rb", "php", "css",
        "html", "xml", "yaml", "yml", "sh", "bat", "ps1", "gitignore",
        "dockerfile", "env", "cfg", "ini", "txt", "lock",
    ];

    fn walk(dir: &std::path::Path, files: &mut Vec<WorkspaceFile>, extensions: &[&str]) {
        if let Ok(entries) = std::fs::read_dir(dir) {
            for entry in entries.flatten() {
                let path = entry.path();
                if path.is_dir() {
                    // Skip common noise directories
                    let name = path.file_name().unwrap_or_default().to_str().unwrap_or("");
                    if name == "target" || name == "node_modules" || name == ".git"
                        || name == "__pycache__" || name == "dist" || name == "build"
                    {
                        continue;
                    }
                    walk(&path, files, extensions);
                } else if path.is_file() {
                    let ext = path.extension()
                        .and_then(|e| e.to_str())
                        .unwrap_or("")
                        .to_lowercase();
                    let name = path.file_name()
                        .and_then(|n| n.to_str())
                        .unwrap_or("")
                        .to_lowercase();
                    if extensions.iter().any(|e| *e == ext.as_str())
                        || name == "dockerfile" || name == "makefile"
                        || name == "license"
                    {
                        if let Ok(content) = std::fs::read(&path) {
                            // Skip binary files (null bytes) and huge files (>10 MB)
                            if content.contains(&0) || content.len() > 10_000_000 {
                                continue;
                            }
                            let size = content.len();
                            files.push(WorkspaceFile {
                                path: path.to_string_lossy().to_string(),
                                content,
                                size,
                            });
                        }
                    }
                }
            }
        }
    }

    walk(std::path::Path::new(root), &mut files, &text_extensions);
    files.sort_by_key(|f| f.size); // sort by size for consistent output
    files
}

// ── JSON-RPC Encoding ────────────────────────────────────────────────────────

/// Build a JSON-RPC method call envelope: {"jsonrpc":"2.0","method":"...","params":{...},"id":1}
fn json_rpc_encode(method: &str, file_path: &str, content: &str) -> Vec<u8> {
    let payload = serde_json::json!({
        "jsonrpc": "2.0",
        "method": method,
        "params": {
            "file": file_path,
            "content": content,
        },
        "id": 1,
    });
    serde_json::to_vec(&payload).unwrap()
}

// ── LUMEN Encoding ───────────────────────────────────────────────────────────

/// Encode file content as a LUMEN frame using single-allocation path.
fn lumen_encode(file_path: &str, content: &str) -> Vec<u8> {
    let payload = serde_json::json!({
        "file": file_path,
        "content": content,
    });

    let est = compress::compressed_size(&payload);
    let max_hdr = hyb128::MAX_ENCODED_LEN;
    let mut buf = Vec::with_capacity(max_hdr + 2 + est);
    buf.resize(max_hdr + 2, 0u8);
    compress::compress_into(&payload, &mut buf);

    let payload_len = buf.len() - (max_hdr + 2);
    let real_hdr = hyb128::encoded_len(payload_len as u64);
    if real_hdr < max_hdr {
        buf.copy_within(max_hdr.., real_hdr);
        buf.truncate(buf.len() - (max_hdr - real_hdr));
    }

    let mut scratch = [0u8; hyb128::MAX_ENCODED_LEN];
    let hn = hyb128::encode(payload_len as u64, &mut scratch);
    buf[..hn].copy_from_slice(&scratch[..hn]);
    buf[hn] = frame::TYPE_REQUEST;
    buf[hn + 1] = frame::FLAG_COMPRESSED;

    buf
}

// ── Main ─────────────────────────────────────────────────────────────────────

fn main() {
    let root = std::env::args().nth(1).unwrap_or_else(|| ".".to_string());

    println!("╔══════════════════════════════════════════════════════╗");
    println!("║   LUMEN vs JSON-RPC — Workspace Indexing Shootout     ║");
    println!("║   Simula: Cadencia analizando un proyecto real        ║");
    println!("╚══════════════════════════════════════════════════════╝");
    println!();
    println!("Scanning: {}", root);

    let files = scan_workspace(&root);
    let total_raw_bytes: usize = files.iter().map(|f| f.size).sum();

    println!(
        "  Found {} files, {:.1} MB total raw content",
        files.len(),
        total_raw_bytes as f64 / 1_048_576.0,
    );

    if files.is_empty() {
        println!("  No text files found. Try a different directory.");
        return;
    }

    // ── JSON-RPC encode ──────────────────────────────────────────────────

    let start = Instant::now();
    let mut json_total_bytes: usize = 0;
    for f in &files {
        let content_str = String::from_utf8_lossy(&f.content);
        let encoded = json_rpc_encode("file/context", &f.path, &content_str);
        json_total_bytes += encoded.len();
    }
    let json_elapsed = start.elapsed();

    // ── LUMEN encode ─────────────────────────────────────────────────────

    let start = Instant::now();
    let mut lumen_total_bytes: usize = 0;
    for f in &files {
        let content_str = String::from_utf8_lossy(&f.content);
        let encoded = lumen_encode(&f.path, &content_str);
        lumen_total_bytes += encoded.len();
    }
    let lumen_elapsed = start.elapsed();

    // ── Results ──────────────────────────────────────────────────────────

    println!();
    println!(
        "╔══════════════════════╤══════════════╤══════════════╤═══════════════╗"
    );
    println!(
        "║ Metric               │ JSON-RPC     │ LUMEN        │ Advantage      ║"
    );
    println!(
        "╠══════════════════════╪══════════════╪══════════════╪═══════════════╣"
    );

    let json_mb = json_total_bytes as f64 / 1_048_576.0;
    let lumen_mb = lumen_total_bytes as f64 / 1_048_576.0;
    println!(
        "║ Wire bytes (total)   │ {:>8.2} MB  │ {:>8.2} MB  │ {:>5.1}% LESS  ║",
        json_mb,
        lumen_mb,
        (1.0 - lumen_total_bytes as f64 / json_total_bytes as f64) * 100.0,
    );

    let json_s = json_elapsed.as_secs_f64();
    let lumen_s = lumen_elapsed.as_secs_f64();
    println!(
        "║ Encode time          │ {:>8.3} s   │ {:>8.3} s   │ {:>7.2}× FASTER ║",
        json_s,
        lumen_s,
        json_s / lumen_s,
    );

    let json_mbps = (json_total_bytes as f64 / 1_048_576.0) / json_s;
    let lumen_mbps = (lumen_total_bytes as f64 / 1_048_576.0) / lumen_s;
    println!(
        "║ Throughput           │ {:>7.1} MB/s │ {:>7.1} MB/s │ {:>7.2}× MORE   ║",
        json_mbps,
        lumen_mbps,
        lumen_mbps / json_mbps,
    );

    let json_ms_per_file = json_s * 1000.0 / files.len() as f64;
    let lumen_ms_per_file = lumen_s * 1000.0 / files.len() as f64;
    println!(
        "║ Time per file        │ {:>8.3} ms  │ {:>8.3} ms  │ {:>7.2}× FASTER ║",
        json_ms_per_file,
        lumen_ms_per_file,
        json_ms_per_file / lumen_ms_per_file,
    );

    println!(
        "╚══════════════════════╧══════════════╧══════════════╧═══════════════╝"
    );

    println!();
    println!("─── Per-file breakdown (largest 5) ───");
    println!(
        "{:<50} {:>10} {:>12} {:>12} {:>10}",
        "File", "Raw (B)", "JSON-RPC (B)", "LUMEN (B)", "Savings"
    );

    // Show largest 5 files
    let mut sorted: Vec<&WorkspaceFile> = files.iter().collect();
    sorted.sort_by_key(|f| std::cmp::Reverse(f.size));
    for f in sorted.iter().take(5) {
        let content_str = String::from_utf8_lossy(&f.content);
        let json_sz = json_rpc_encode("file/context", &f.path, &content_str).len();
        let lumen_sz = lumen_encode(&f.path, &content_str).len();
        let display_path = if f.path.len() > 48 {
            format!("...{}", &f.path[f.path.len() - 45..])
        } else {
            f.path.clone()
        };
        println!(
            "{:<50} {:>10} {:>12} {:>12} {:>9.1}%",
            display_path,
            f.size,
            json_sz,
            lumen_sz,
            (1.0 - lumen_sz as f64 / json_sz as f64) * 100.0,
        );
    }

    // ── Simulated Cadencia scenario ──────────────────────────────────────

    println!();
    println!("─── Simulated Cadencia scenario ───");
    println!(
        "  Project with {:.0}K files → JSON-RPC: {:.1}s  |  LUMEN: {:.1}s  |  {:.1}× faster",
        files.len() as f64 / 1000.0,
        json_s * 5.0, // scale to 5K files
        lumen_s * 5.0,
        json_s / lumen_s,
    );

    let five_k_json = json_s * (5000.0 / files.len() as f64);
    let five_k_lumen = lumen_s * (5000.0 / files.len() as f64);
    println!(
        "  Scenario: 5,000 files → JSON-RPC: {:.1}s  |  LUMEN: {:.1}s  |  {:.1}× faster",
        five_k_json,
        five_k_lumen,
        five_k_json / five_k_lumen,
    );
    println!(
        "  Wire: JSON {:.1} MB vs LUMEN {:.1} MB ({:.0}% savings)",
        json_total_bytes as f64 / 1_048_576.0 * (5000.0 / files.len() as f64),
        lumen_total_bytes as f64 / 1_048_576.0 * (5000.0 / files.len() as f64),
        (1.0 - lumen_total_bytes as f64 / json_total_bytes as f64) * 100.0,
    );
}
