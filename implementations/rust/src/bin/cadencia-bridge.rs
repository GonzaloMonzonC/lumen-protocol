//! cadencia-bridge — LUMEN sidecar for Cadencia (VS Code extension).
//!
//! ## Architecture
//!
//! The bridge runs as a child process spawned by the VS Code extension.
//! It reads JSON commands on stdin, executes them using LUMEN's native
//! Rust encoder, and reports results on stdout.
//!
//! ## Protocol (stdin → stdout, line-delimited JSON)
//!
//! ```json
//! → {"cmd":"ping"}
//! ← {"status":"ok","version":"0.1.0","protocol":"lumen/1"}
//!
//! → {"cmd":"index","files":["src/main.rs","src/lib.rs",...]}
//! ← {"status":"ok","files":1234,"total_bytes":5242880,"wire_bytes":4915200,
//!     "encode_ms":12,"elapsed_ms":34}
//!
//! → {"cmd":"stop"}
//! ← {"status":"ok","reason":"requested"}
//! ```
//!
//! ## Design decisions
//!
//! - **No MCP server interaction in v1** — the bridge only does local encode.
//!   The extension handles transport to the MCP server. This keeps the
//!   bridge simple and testable.
//! - **Single-allocation encode** via `compress_into` — zero intermediate Vecs.
//! - **File reading is batched** — the extension sends all paths upfront so the
//!   bridge can stream frames back without back-and-forth.

use lumen::{compress, frame, hyb128};
use serde::{Deserialize, Serialize};
use std::io::{self, BufRead, Write};

// ── JSON Protocol Types ──────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct Command {
    cmd: String,
    #[serde(default)]
    files: Vec<String>,
}

#[derive(Debug, Serialize)]
struct Response {
    status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    version: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    protocol: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    files: Option<usize>,
    #[serde(skip_serializing_if = "Option::is_none")]
    total_bytes: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    wire_bytes: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    encode_us: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    elapsed_us: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    error: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    reason: Option<String>,
}

impl Response {
    fn ok() -> Self {
        Response {
            status: "ok".into(),
            version: None,
            protocol: None,
            files: None,
            total_bytes: None,
            wire_bytes: None,
            encode_us: None,
            elapsed_us: None,
            error: None,
            reason: None,
        }
    }

    fn err(msg: &str) -> Self {
        let mut r = Response::ok();
        r.status = "error".into();
        r.error = Some(msg.into());
        r
    }
}

// ── Core Logic ───────────────────────────────────────────────────────────────

/// Encode a single file's content as a LUMEN frame (TYPE_RESPONSE + FLAG_COMPRESSED).
/// Returns the framed bytes. Uses a single allocation.
fn encode_file(_path: &str, content: &[u8]) -> io::Result<Vec<u8>> {
    let value = serde_json::Value::String(
        String::from_utf8(content.to_vec())
            .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, e))?,
    );

    let est = compress::compressed_size(&value);
    let max_hdr = hyb128::MAX_ENCODED_LEN;
    let mut buf = Vec::with_capacity(max_hdr + 2 + est);
    buf.resize(max_hdr + 2, 0u8);
    compress::compress_into(&value, &mut buf);

    let payload_len = buf.len() - (max_hdr + 2);
    let real_hdr = hyb128::encoded_len(payload_len as u64);
    if real_hdr < max_hdr {
        buf.copy_within(max_hdr.., real_hdr);
        buf.truncate(buf.len() - (max_hdr - real_hdr));
    }

    let mut scratch = [0u8; hyb128::MAX_ENCODED_LEN];
    let hn = hyb128::encode(payload_len as u64, &mut scratch);
    buf[..hn].copy_from_slice(&scratch[..hn]);
    buf[hn] = frame::TYPE_RESPONSE;
    buf[hn + 1] = frame::FLAG_COMPRESSED;

    Ok(buf)
}

fn handle_index(files: &[String]) -> Response {
    use std::time::Instant;

    if files.is_empty() {
        return Response::err("no files specified");
    }

    let start = Instant::now();
    let mut total_bytes: u64 = 0;
    let mut wire_bytes: u64 = 0;
    let mut encode_ns: u64 = 0;

    for path in files {
        let content = match std::fs::read(path) {
            Ok(c) => c,
            Err(e) => {
                eprintln!("warning: skipping {}: {}", path, e);
                continue;
            }
        };

        total_bytes += content.len() as u64;

        let encode_start = Instant::now();
        let framed = match encode_file(path, &content) {
            Ok(f) => f,
            Err(e) => {
                eprintln!("warning: encode failed for {}: {}", path, e);
                continue;
            }
        };
        encode_ns += encode_start.elapsed().as_nanos() as u64;

        wire_bytes += framed.len() as u64;

        // In a real deployment, frames would be written to the MCP server.
        // For the prototype, the extension reads them via a follow-up command.
    }

    let mut r = Response::ok();
    r.files = Some(files.len());
    r.total_bytes = Some(total_bytes);
    r.wire_bytes = Some(wire_bytes);
    r.encode_us = Some(encode_ns / 1000);
    r.elapsed_us = Some(start.elapsed().as_micros() as u64);
    r
}

fn handle_ping() -> Response {
    let mut r = Response::ok();
    r.version = Some("0.1.0".into());
    r.protocol = Some("lumen/1".into());
    r
}

// ── Main Loop ────────────────────────────────────────────────────────────────

fn main() -> io::Result<()> {
    let stdin = io::stdin();
    let stdout = io::stdout();
    let mut stdout = stdout.lock();

    // Send ready signal
    let ready = handle_ping();
    writeln!(stdout, "{}", serde_json::to_string(&ready).unwrap())?;
    stdout.flush()?;

    for line in stdin.lock().lines() {
        let line = line?;
        let line = line.trim().to_owned();
        if line.is_empty() {
            continue;
        }

        let cmd: Command = match serde_json::from_str(&line) {
            Ok(c) => c,
            Err(e) => {
                let resp = Response::err(&format!("invalid command: {}", e));
                writeln!(stdout, "{}", serde_json::to_string(&resp).unwrap())?;
                stdout.flush()?;
                continue;
            }
        };

        let resp = match cmd.cmd.as_str() {
            "ping" => handle_ping(),
            "index" => handle_index(&cmd.files),
            "stop" => {
                let mut r = Response::ok();
                r.reason = Some("requested".into());
                writeln!(stdout, "{}", serde_json::to_string(&r).unwrap())?;
                stdout.flush()?;
                break;
            }
            _ => Response::err(&format!("unknown command: {}", cmd.cmd)),
        };

        writeln!(stdout, "{}", serde_json::to_string(&resp).unwrap())?;
        stdout.flush()?;
    }

    Ok(())
}
