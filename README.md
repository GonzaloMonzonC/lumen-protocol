# LUMEN — Lightweight Universal Model Exchange Network

A high-efficiency binary protocol for communication between MCP (Model Context Protocol) systems. Designed from scratch to overcome JSON-RPC limitations with native compression, zero-copy, zero-trust, and LLM-optimized streaming.

---

## 🎯 Motivation

JSON-RPC, the current MCP protocol, is verbose, slow to parse, and not optimized for:
- **Real-time LLM token streaming**
- **High throughput** in local communication (stdio/UDS)
- **Zero-copy** over shared memory
- **Zero-trust** with granular attenuable permissions

**LUMEN** solves all of this with a self-delimiting binary protocol with about 4 bytes of overhead.

---

## 🧬 Protocol Anatomy

```
┌──────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN]     │
└──────────────────────────────────────────────────────┘
```

### Hyb128 — O(1) hybrid length

| Mode | Bits | Range | Total bytes |
|------|------|-------|-------------|
| `00` | `00` | 0–63 B | **1 byte** |
| `10` | `10` | 64 B–64 KB | 3 bytes |
| `11` | `11` | 64 KB–4 GB | 5 bytes |
| `01` | `01` | >4 GB (rare) | LEB128 |

→ The parser knows in **a single CPU read** how many bytes to skip. No loops, no branch misprediction.

### Frame Types

| ID | Type | Description |
|----|------|-------------|
| `0x01` | `REQUEST` | Client → server request |
| `0x02` | `RESPONSE` | Server → client response |
| `0x03` | `NOTIFY` | Fire-and-forget |
| `0x04` | `STREAM_DATA` | Streaming data |
| `0x05` | `SCHEMA_PATCH` | Live schema delta |
| `0x06` | `STREAM_INIT` | Initialize token stream |
| `0x07` | `DICT_SYNC` | Dictionary synchronization |
| `0x08` | `DISCOVER` | Dynamic introspection (late binding) |
| `0x09` | `MUX` | Logical channel multiplexing |
| `0x0A` | `HEARTBEAT` | Keep-alive |

---

## 🔤 Compression Dictionary

128 static entries (IDs `0x00–0x7F`) + 127 dynamic entries per session (`0x80–0xFE`).

The most frequent keys map to 1 byte:

| ID | Key | ID | Key |
|----|-----|----|-----|
| `0x00` | `tool` | `0x08` | `text` |
| `0x01` | `arguments` | `0x20` | `resources` |
| `0x02` | `result` | `0x21` | `tools` |
| `0x03` | `error` | `0x4F` | `usage` |

`0xFF` = uncompressed key (escape hatch).

---

## 🔐 Zero-Trust with Macaroons

Each handshake exchanges **Capability Tokens** (Macaroons) with caveats such as:
```
op: filesystem.read:/home/user/project
op: tool.call:search_code
exp: 2026-06-11T18:00:00Z
rate: 100/min
```

Intermediate nodes **attenuate** permissions (add restrictions, never remove them) before delegating to sub-agents.

> 💡 Combine Macaroons with **Wire Encryption (§7.4 of SPEC)** for confidentiality +
> complete mutual authentication.

### 🔒 Wire Encryption (ChaCha20-Poly1305 + X25519)

Optional authenticated frame-level encryption, negotiated during the handshake:

```
Encrypted frame:
┌──────────────────────────────────────────────────────────────┐
│ [Hyb128] [TYPE:1B] [FLAGS:1B | 0x02] [NONCE:12B] [CIPHER+TAG]│
└──────────────────────────────────────────────────────────────┘
                          overhead: 28 bytes
```

| Mechanism | Algorithm |
|---|---|
| Encryption | ChaCha20 (256-bit key) |
| Integrity | Poly1305 MAC |
| Key exchange | X25519 (ephemeral per session) |
| Anti-replay | Monotonic nonce counter per direction |
| Negotiation | PROBE/PROBE_ACK with base64 public key |

```rust
// Rust (lumen crate)
let kp = Keypair::generate();
let mut cipher = Cipher::new(&kp.derive_shared_secret(&peer_pk));
let frame = cipher.build_encrypted_frame(TYPE_REQUEST, 0, b"payload")?;
let plaintext = cipher.decrypt(encrypted_payload)?;
```

```typescript
// TypeScript (Web Crypto API)
const kp = await generateKeypair();
const shared = await deriveSharedSecret(kp.secretKey, peerPublicKey);
const cipher = new Cipher(); await cipher.init(shared);
const frame = await cipher.buildEncryptedFrame(TYPE_REQUEST, 0, payload);
const plaintext = await cipher.decrypt(encryptedPayload);
```

| Language | Status |
|---|---|
| **Rust** | ✅ `crypto.rs` — 8 tests |
| **Rust QUIC** | ✅ `quic.rs` — 8 tests (`--features quic`) |
| **TypeScript** | ✅ `crypto.ts` — WebCrypto |
| Python, C#, PHP | *(pending)* |

> ⚠️ No PKI in this version. For identity authentication, use Macaroons (§7.2 SPEC).

---

## 🌊 Native Streaming

**TokenStream** optimized for LLMs:

```
Init:  [0x06] [STREAM_ID:2B] [TOKEN_TYPE:1B]
Data:  [0x04] [STREAM_ID:2B] [BURST_LEN:Hyb128] [TOKENS...]
Close: BURST_LEN = 0
```

No fragile terminators. No header re-serialization. Delimited bursts.

---

## 🚚 Transport (LTA)

LUMEN is transport-agnostic, with 3 levels:

| Level | Name | Transports |
|-------|------|------------|
| 1 | Stream | stdio, TCP, UDS, WebSocket |
| 2 | Zero-Copy | UDS + mmap (Unix), Named SHM (Windows) ✅ |
| 3 | Datagram | UDP, multicast ✅ |
| 4 | QUIC | UDP+TLS 1.3, multi-stream, 0-RTT ✅ |

Frames are self-delimiting (Hyb128) → they work over any reliable stream without extra layers.

### Level 4 — QUIC (RFC 9000)

Secure transport over UDP with built-in TLS 1.3, native multi-streaming, and a 0-RTT handshake. Ideal for remote agent communication that requires encryption and multiplexing without TCP head-of-line blocking.

```rust
use lumen::quic::{QuicEndpoint, generate_self_signed_cert};

// Server
let (cert, key) = generate_self_signed_cert(&["lumen.local".to_string()])?;
let endpoint = QuicEndpoint::server("0.0.0.0:4433".parse()?, cert, key)?;
let transport = endpoint.accept().await?;  // accepts incoming connection

// Client
let endpoint = QuicEndpoint::client()?;
let transport = endpoint.connect("lumen.local:4433".parse()?).await?;
transport.send(b"LUMEN frame").await?;
let response = transport.recv().await?;
```

| Property | QUIC (Level 4) | TCP (Level 1) |
|---|---|---|
| Encryption | TLS 1.3 required | Optional (LTA handshake) |
| Handshake | 1-RTT (0-RTT on reconnect) | 3-way TCP + LTA negotiation |
| Streams | Multiple independent streams | Single ordered stream |
| Head-of-line blocking | ❌ No (per stream) | ✅ Yes (global) |
| Connection migration | ✅ Native (connection ID) | ❌ Breaks when IP changes |
| Feature flag | `--features quic` | Always available |

> **Tests:** 8/8 ✅ — `cargo test --features quic`

---

## 🏗️ Project Structure

```
/LUMEN/
├── README.md               ← this file
├── SPEC.md                  ← full protocol specification (9 sections)
├── DICTIONARY.md            ← glossary of 128 static IDs
└── /implementations/
    ├── /rust/               ← reference implementation
    │   ├── Cargo.toml
    │   └── src/
    │       ├── lib.rs
    │       ├── hyb128.rs    ← hybrid length encoding
    │       ├── frame.rs     ← frame parser/builder
    │       ├── dict.rs      ← O(1) dictionary: 128 static + 127 session (OnceLock<RwLock<>>)
    │       ├── compress.rs  ← compact binary payload (TAG + dict)
    │       ├── ffi.rs       ← C FFI exports (gated out for WASM builds)
    │       ├── wasm.rs      ← WASM bindings (wasm-bindgen, builds with wasm-pack)
    │       ├── fixtures.rs  ← realistic data generators
    │       ├── transport.rs ← transport abstraction
    │       ├── crypto.rs    ← ChaCha20-Poly1305 + X25519 wire encryption
    │       ├── handshake.rs ← Transport + encryption negotiation
    │       ├── quic.rs      ← QUIC transport (RFC 9000, Level 4)
    │       └── bin/
    │           ├── shootout.rs           ← CPU + wire size benchmark
    │           ├── heap-shootout.rs      ← heap allocation benchmark
    │           ├── concurrent-shootout.rs← concurrent stress benchmark
    │           ├── ipc-shootout.rs       ← real IPC latency benchmark (TCP)
    │           ├── shm-shootout.rs       ← zero-copy shared memory benchmark
    │           ├── workspace-shootout.rs ← project indexing benchmark
    │           ├── dgram-shootout.rs     ← UDP roundtrip benchmark (Level 3)
    │           └── cadencia-bridge.rs    ← Rust sidecar for Cadencia (VS Code)
    ├── /typescript/         ← @lumen/mcp-transport (Node.js)
    │   ├── README.md         ← API docs + LUMEN negotiation
    │   ├── package.json
    │   ├── tsconfig.json
    │   └── src/
    │       ├── index.ts      ← public exports
    │       ├── transport.ts  ← LumenStdioTransport, LumenWebSocketTransport
    │       ├── negotiation.ts← LUMEN probe/ack handshake + JSON-RPC fallback
    │       ├── hyb128.ts     ← Hyb128 encode/decode
    │       ├── frame.ts      ← Frame builder/parser
    │       ├── frame-assembler.ts ← Zero-allocation streaming reassembler
    │       ├── dict.ts       ← 128 static + 127 session dictionary
    │       ├── compress.ts   ← Compact binary payload
    │       ├── compress_ffi.ts← FFI wrapper (Rust → Node via koffi)
    │       ├── shm_ffi.ts    ← SHM zero-copy transport (Level 2, FFI)
    │       ├── dgram.ts      ← Datagram UDP/multicast (Level 3)
    │       ├── zeroalloc.ts  ← ZeroAllocDecompressor (54% less GC)
    │       └── cadencia.ts   ← Rust sidecar client
    ├── /python/             ← lumen-py (pip install)
    │   ├── README.md
    │   ├── pyproject.toml
    │   ├── bench.py         ← benchmark suite
    │   ├── tests/
    │   │   └── test_lumen.py ← 94 tests
    │   └── src/lumen/
    │       ├── __init__.py
    │       ├── hyb128.py    ← Hyb128 encode/decode
    │       ├── frame.py     ← Frame builder/parser
    │       ├── frame_assembler.py ← Streaming frame reassembler
    │       ├── dict.py      ← 128 static + 127 session dictionary
    │       ├── compress.py  ← Compact binary payload
    │       ├── negotiation.py ← Probe/ack handshake
    │       ├── transport.py ← LumenStdioTransport + LumenWebSocketTransport
    │       └── cadencia.py  ← Rust sidecar bridge client
    ├── /csharp/              ← lumen-cs (.NET 9)
    │   ├── LumenCSharp.csproj
    │   ├── Dict.cs          ← 128 static + 127 session dictionary
    │   ├── Hyb128.cs        ← Hyb128 encode/decode
    │   ├── LumenCompress.cs ← Compact binary payload (native C#)
    │   ├── LumenFFI.cs      ← P/Invoke FFI (Rust → .NET)
    │   └── Program.cs       ← Test harness + benchmarks
    └── /php/                ← lumen-php (composer)
        ├── composer.json
        ├── bench.php        ← benchmark suite (8 categories, 74 results)
        ├── tests/
        │   └── e2e_test.php ← cross-implementation e2e (217 tests)
        └── src/
            ├── Compress.php       ← compact binary payload
            ├── Dict.php           ← 128 static + 127 session dictionary
            ├── Hyb128.php         ← Hyb128 encode/decode
            ├── Frame.php          ← frame parser
            └── FrameAssembler.php ← streaming frame assembler
```

---

## 🦀 Rust Implementation

```bash
cd implementations/rust
cargo test                       # 86 tests (without quic feature)
cargo test --features quic       # 94 tests (with QUIC, --test-threads=1)
cargo run --bin shootout             # CPU + wire size benchmark
cargo run --bin heap-shootout        # heap allocation benchmark
cargo run --bin concurrent-shootout  # concurrent stress benchmark
cargo run --bin ipc-shootout         # real IPC latency benchmark (TCP)
cargo run --bin shm-shootout         # zero-copy shared memory benchmark
cargo run --bin workspace-shootout   # project indexing benchmark
echo '{"cmd":"index","files":["src/main.rs"]}' | cargo run --bin cadencia-bridge  # sidecar
```

### hyb128

```rust
use lumen::hyb128;

let mut buf = [0u8; hyb128::MAX_ENCODED_LEN];
let n = hyb128::encode(42, &mut buf);
let decoded = hyb128::decode(&buf[..n]).unwrap();
assert_eq!(decoded.value, 42);
assert_eq!(n, 1); // only 1 byte for values ≤ 63
```

### frame + compress

```rust
use lumen::{frame, compress};
use serde_json::json;

let payload = json!({"tool": "search", "arguments": {"query": "hello"}});
let compressed = compress::compress(&payload);  // 30-75% smaller
let mut buf = vec![0u8; frame::build_size(compressed.len())];
let n = frame::build(frame::TYPE_REQUEST, frame::FLAG_COMPRESSED, &compressed, &mut buf);

match frame::parse(&buf[..n]) {
    frame::ParseResult::Complete { frame, .. } => {
        let value = compress::decompress(frame.payload).unwrap();
        println!("{}", serde_json::to_string_pretty(&value).unwrap());
    }
    _ => {}
}
```

### dict O(1)

```rust
use lumen::dict;

// Resolve: ID → key (static 0x00–0x7F, session 0x80–0xFE)
assert_eq!(dict::resolve(0x00), Some("tool"));
assert_eq!(dict::resolve_any(0x80), None); // session slot still empty

// Lookup: key → ID (static dict first, then session dict)
assert_eq!(dict::lookup_fast("tool"), Some(0x00));
assert_eq!(dict::lookup_fast("nonexistent"), None);

// Session dictionary (127 dynamic slots)
dict::register_session("my_custom_key", 0x80).unwrap();
assert_eq!(dict::resolve_any(0x80), Some("my_custom_key".to_string()));
assert_eq!(dict::lookup_fast("my_custom_key"), Some(0x80));
```

### Compact binary format

```
Value tags:  0xE0=NULL  0xE1=BOOL  0xE2=FLOAT(f64 LE)  0xE3=INT(LEB128 zigzag)
             0xE4=STR_DICT(1B ID)  0xE5=STR_RAW  0xE6=ARRAY  0xE7=OBJECT

Keys inside objects:  0x00..0x7E = dict ID  0xFF = raw UTF-8
```

### WASM (WebAssembly)

Compiles the Rust crate to WASM for direct use from JavaScript/TypeScript in browsers or edge runtimes:

```bash
rustup target add wasm32-unknown-unknown
npm install -g wasm-pack        # or: cargo install wasm-pack
wasm-pack build --target web --features wasm
```

```javascript
import init, { lumen_compress, lumen_decompress, lumen_version } from "./pkg/lumen.js";

await init();

const json = JSON.stringify({ tool: "search", arguments: { query: "hello" } });
const compressed = lumen_compress(json);   // Uint8Array
const restored = lumen_decompress(compressed); // string (JSON)
console.log(lumen_version());              // "0.1.0"
```

The `ffi.rs` module (C FFI) is automatically excluded from the WASM build to avoid
symbol collisions (`#[cfg(not(feature = "wasm"))]`).

---

## 📊 Benchmark — LUMEN vs JSON-RPC

6 realistic MCP scenarios, measured with `cargo run --bin shootout` (WARMUP=20, MEASURE=200):

```
╔════════════════════════════════════════╤═══════════╤═══════════╤══════════╤═════════╗
║ Scenario                               │ JSON wire │ LUMEN wire│ Savings  │ Speedup ║
╠════════════════════════════════════════╪═══════════╪═══════════╪══════════╪═════════╣
║ S1: tools/list (1000 tools)            │ 390.86 KB │ 267.41 KB │  31.6%   │  2.06×  ║
║ S2: file_context (5 MB, 50 files)      │  5.01 MB  │  4.89 MB  │   2.5%   │  7.02×  ║
║ S3: token_stream (10K tokens)          │ 732.90 KB │ 125.57 KB │  82.9%   │  3.00×  ║
║ S4: multi_agent (1K reqs, 10 agents)   │ 109.03 KB │  67.38 KB │  38.2%   │  1.23×  ║
║ S5: heartbeat (100K heartbeats)        │     89 B  │     48 B  │  46.1%   │  1.61×  ║
║ S6: session_dict (127 keys)            │  2.50 KB  │    453 B  │  82.3%   │  1.73×  ║
╚════════════════════════════════════════╧═══════════╧═══════════╧══════════╧═════════╝
```

**🏆 LUMEN wins in EVERY scenario on both wire size AND speed.**

### Why LUMEN is faster

| Factor | JSON-RPC | LUMEN |
|---|---|---|
| Empty message overhead | ~40 bytes | **3 bytes** |
| Typical message overhead | ~60 bytes | **~5 bytes** |
| Payload format | JSON with escaping | Binary Tags + Dict IDs |
| Repeated keys | Full string every time | **1 byte** (dict ID) |
| Long strings (>1KB) | Escapes `\"`, `\n`, `\\` | **Raw binary, no escaping** |
| Dictionary lookup | N/A | **O(1)** `OnceLock<HashMap>` |
| Framing | `\n` delimiters | O(1) self-delimiting Hyb128 |
| LLM streaming | JSON per token (~75 B/token) | **Binary (~12 B/token)** |
| Compression | Not native | 128+127 ID dictionary |
| Zero-Copy | No | **Yes (mmap/shared memory, Level 2 ✅)** |
| Zero-Trust | No | Attenuable Macaroons |
| Late Binding | No | DISCOVER + SchemaPatch |

### Where each scenario shines

- **S3 (82.9% saving):** Each LLM token goes from ~75 JSON bytes to ~12 binary bytes. Hyb128 framing + no quotes. The most extreme saving in the benchmark.
- **S6 (82.3% saving):** 127 dynamically registered session keys (0x80–0xFE). Each key collapses from 14-character strings to 1 byte. Ideal for specialized domains.
- **S2 (7.02× faster):** 100KB source code files — LUMEN writes raw bytes without escaping `"`, `\n`, `\t`. `serde_json` suffers badly here.
- **S1/S4 (31-38% saving):** Keys like `"name"`, `"description"`, `"inputSchema"`, `"method"`, `"params"` collapse from 10-15 bytes to **1 byte** each.
- **S5 (46.1% saving):** A LUMEN heartbeat weighs 48 bytes vs 89 for JSON-RPC. ×1M heartbeats: 45 MB vs 85 MB.

---

## 🧠 Heap Allocation Profiling

Measured with `cargo run --bin heap-shootout` using a custom `#[global_allocator]` with atomic counters. Average per iteration (×100 runs):

```

╔══════════════════════════════════════╤═══════════╤═══════════╤══════════════╤══════════════╤══════════╤══════════╗
║ Scenario (per iteration)             │ JSON alloc│ LUMEN allo│ Alloc Ratio  │ Bytes Ratio  │ JSON peak│ LUM peak ║
╠══════════════════════════════════════╪═══════════╪═══════════╪══════════════╪══════════════╪══════════╪══════════╣
║ S1: tools/list (1000 tools)          │    37.5K  │    37.3K  │    1.0×      │    1.6× ⭐    │    3313K │    2529K ║
║ S2: file_context (5 MB)              │      444  │      411  │    1.1× ⭐    │    2.2× ⭐    │   13366K │   10029K ║
║ S3: token_stream (1K tokens)         │     1.0K  │     1.0K  │    1.0×      │    2.0× ⭐    │     119K │      83K ║
║ S4: multi_agent (1K reqs)            │    14.8K  │    12.8K  │    1.2× ⭐    │    2.0× ⭐    │    1353K │     945K ║
║ S5: heartbeat (1 frame)              │       11  │       11  │    1.0×      │    1.4× ⭐    │       1K │       1K ║
╚══════════════════════════════════════╧═══════════╧═══════════╧══════════════╧══════════════╧══════════╧══════════╝
```

### Interpretation

| Metric | Finding |
|--------|---------|
| **Bytes allocated** | LUMEN allocates **40-55% fewer bytes** — S2 (file_context 5 MB) drops from 21.2 MB → 9.8 MB, S3 (tokens) from 165 KB → 83 KB |
| **Peak memory** | LUMEN reduces heap peak by **24-30%** — S2 drops from 13.4 MB → 10.0 MB, S4 from 1.35 MB → 0.94 MB |
| **Allocation count** | Comparable in most scenarios. S4 improves from 14.8K → 12.8K (14% fewer). The `compress_into` fusion removes the double-buffer |
| **Single-allocation encode** | LUMEN encode uses **a single `Vec`** — zero intermediate buffers. Direct writes into the destination buffer |

> **Conclusion:** LUMEN not only reduces wire size (31-83%), it also allocates **40-55% fewer bytes** and reduces heap peak by **24-30%**. Fusing the encode path with `compress_into` removes the double-buffer.

---

## ⚡ Concurrent Stress Test

Simulates **64 threads** competing for a shared transport with a realistic mixed load (10% heartbeats, 30% tokens, 40% tool calls, 20% 5 KB file chunks). Measured with `cargo run --bin concurrent-shootout`:

```
╔══════════════════════════╤═══════════╤═══════════╤══════════════╤════════════════╗
║ Metric                   │ JSON-RPC   │ LUMEN      │ Ratio        │ Winner         ║
╠══════════════════════════╪═══════════╪═══════════╪══════════════╪════════════════╣
║ Total wire bytes         │   38.7 MB  │   35.7 MB  │  92.2% LUM   │ LUMEN (7.8%)   ║
║ Throughput (MB/s)        │     29.1   │     50.3   │   1.7× LUM   │ LUMEN          ║
║ Messages/sec             │   24,042   │   45,070   │   1.9× LUM   │ LUMEN          ║
║ Wall time (ms)           │    1,331   │      710   │   1.9× LUM   │ LUMEN          ║
╚══════════════════════════╧═══════════╧═══════════╧══════════════╧════════════════╝
```

### Why LUMEN does not suffer Head-of-Line Blocking

| Factor | JSON-RPC under contention | LUMEN under contention |
|--------|---------------------------|-------------------------|
| Serialization per msg | ~981 µs (JSON parser blocks) | **~43 µs** (binary O(1) framing) |
| Large files (5 KB) | Escapes `\"`, `\n`, `\t` → saturates CPU | **Raw binary copy** → CPU breathes |
| Framing | `Content-Length: ...\r\n\r\n` → line-by-line parsing | **Hyb128**: 1-5 bytes, parser knows in 1 cycle how much to skip |
| CPU contention | Serializing 5 KB of source code monopolizes the core | O(1) dict compression + raw copy frees the core quickly |
| Cascade effect | One slow thread → the others wait | All threads finish quickly → less contention |

> **Conclusion:** Under real concurrent load (64 threads mixing heartbeats, tokens, tool calls, and files), LUMEN doubles throughput and reduces wall time by 1.9×. This is critical for orchestrators like Synapse where multiple agents share the same socket.

---

## 🌐 IPC End-to-End Latency (TCP Loopback)

Measures real *Round Trip Time* over TCP loopback (`127.0.0.1`, `nodelay`) — the full kernel TCP stack. Echo server in one thread, client in another. 2000 iterations per workload, 500 warmup. Measured with `cargo run --bin ipc-shootout`:

```
╔══════════════════════════════╤══════════╤══════════╤══════════╤══════════╤══════════╤══════════╗
║ Workload                     │ JSON p50 │ LUMEN p50│ JSON p99 │ LUMEN p99│ JSON avg │ LUMEN avg║
╠══════════════════════════════╪══════════╪══════════╪══════════╪══════════╪══════════╪══════════╣
║ W1: heartbeat (tiny, ~90B)   │     91µs │    155µs │    297µs │    656µs │    108µs │    173µs ║
║ W2: tool_call (~400B)        │    153µs │    140µs │    571µs │    543µs │    181µs │    177µs ║
║ W3: llm_token (~32B)         │     76µs │    100µs │    222µs │    207µs │     89µs │    111µs ║
║ W4: file_chunk (5 KB)        │    634µs │    161µs │   1199µs │    367µs │    715µs │    177µs ║
║ W5: tokens_x10 (batch)       │     92µs │    108µs │    195µs │    247µs │    102µs │    126µs ║
╚══════════════════════════════╧══════════╧══════════╧══════════╧══════════╧══════════╧══════════╝
```

### Analysis

| Workload | Speedup | Wire saving | Interpretation |
|----------|---------|-------------|----------------|
| **W4: file_chunk** | **4.0×** | 3% | Raw binary copy of source code without escaping `\"`, `\n`, `\t`. `serde_json` chokes |
| W2: tool_call | 1.0× | 33% | Technical tie under TCP (~140-180 µs). Dict compression wins on wire (33%), but kernel TCP levels the RTT |
| W5: tokens_x10 | 0.8× | 6% | Batch of 10 tokens — binary overhead (tags + Hyb128 per token) is similar to the JSON array |
| W1: heartbeat | 0.6× | 47% | TCP stack (~90-150 µs base) dominates both. LUMEN wire is smaller (48B vs 90B), but the kernel rules |
| W3: llm_token | 0.8× | 9% | Single token — JSON is just `"text"`, LUMEN adds tag + dict ID + zigzag logprob |

> **Conclusion:** For payloads >1 KB, LUMEN wins by **4.0× in real RTT over TCP**. For small payloads (<500 B), the TCP kernel dominates (~70-150 µs base) and both protocols are equivalent. **LUMEN's real IPC advantage appears with large files** (source code, resources, blobs), where raw binary copy crushes JSON escaping. For token streaming, the advantage is in the **CPU benchmark** (S3: 3.00×) and **concurrency** (1.9×), not in single-token RTT.

---

## 🌊 Level 3 — Datagram (UDP / Multicast)

LUMEN Level 3 is **message-oriented**: each UDP datagram carries exactly one complete LUMEN frame. No additional framing layer — the datagram boundary **is** the frame boundary. The socket operates in non-blocking mode with a pre-allocated 65 KB buffer.

```
┌──────────────────────────────────────────────────┐
│  UDP Datagram                                    │
│  ┌────────────────────────────────────────────┐  │
│  │ [Hyb128:LEN] [TYPE:1B] [FLAGS:1B] [DATA]   │  │
│  └────────────────────────────────────────────┘  │
│  1 datagram = 1 LUMEN frame                     │
└──────────────────────────────────────────────────┘
```

### Why UDP for MCP?

TCP is ideal for reliable streams (Level 1/2), but there are workloads where **latency and throughput matter more than guaranteed delivery**:

| Workload | TCP (Level 1) | UDP (Level 3) |
|---|---|---|
| **Service Discovery** | Need to know IP:port up front | A multicast DISCOVER frame reaches all agents on the subnet |
| **Telemetry / metrics** | 3-way handshake per connection → latency | Fire-and-forget: sender does not wait for ACK |
| **Heartbeats** | Persistent, stateful connection | Stateless: each heartbeat is autonomous, connectionless |
| **Log shipping** | Kernel TCP backpressure slows the sender | Sender fires at maximum speed, receiver processes what it can |
| **Late binding** | Fixed point-to-point connection | An agent can discover new peers at runtime without reconfiguration |

### Multicast — Service Discovery without an orchestrator

```
┌──────────┐                              ┌──────────┐
│ Agent A  │──── DISCOVER (239.1.1.1) ───→│ Agent B  │
│          │                              │          │
│          │←─── RESPONSE (unicast) ──────│          │
│          │                              │          │
│          │←─── RESPONSE (unicast) ──────│ Agent C  │
│          │                              │          │
│          │←─── RESPONSE (unicast) ──────│ Agent D  │
└──────────┘                              └──────────┘

1 DISCOVER frame  →  N unicast responses
No central registry, no DNS, no configuration files.
```

Multicast TTL defines scope:

| TTL | Scope | Use |
|-----|-------|-----|
| 0 | Same host | Local agent-to-sidecar |
| 1 | Same subnet | Microservices in a cluster |
| 32 | Same site | Multi-rack in a datacenter |
| 64 | Same region | Multi-AZ |
| 255 | Global | Theoretical (rarely used) |

### API — Rust

```rust
use lumen::datagram::DatagramTransport;

// Receiver (listens on a fixed port)
let mut rx = DatagramTransport::bind("127.0.0.1:9999")?;
while let Some((data, src)) = rx.recv_frame()? {
    // data: &[u8] with the complete LUMEN frame
    println!("Frame from {}: {} bytes", src, data.len());
}

// Sender (ephemeral port)
let tx = DatagramTransport::bind("127.0.0.1:0")?;
tx.send_frame_to(&frame_bytes, "127.0.0.1:9999".parse()?)?;

// Multicast
rx.join_multicast("239.1.1.1", None)?;
tx.set_multicast_ttl(1)?;
tx.send_frame_to(&discover_frame, "239.1.1.1:9999".parse()?)?;
```

### API — TypeScript

```typescript
import {
  DatagramTransport,
  buildDgram,
  parseDgram,
  TYPE_HEARTBEAT,
} from "@lumen/mcp-transport";

// Receiver
const rx = new DatagramTransport({ bindPort: 9999 });
await rx.bind();
rx.onMessage = (data, rinfo) => {
  const result = parseDgram(data);
  if (result.kind === "complete") {
    console.log(`Frame 0x${result.frame.frameType.toString(16)} de ${rinfo.address}`);
  }
};

// Sender
const tx = new DatagramTransport();
await tx.bind();
const frame = buildDgram(TYPE_HEARTBEAT, 0, Buffer.from("ping"));
await tx.send(frame, 9999, "127.0.0.1");

// Multicast
rx.addMulticastMembership("239.1.1.1");
tx.setMulticastTTL(1);
await tx.send(frame, 9999, "239.1.1.1");
```

### Limits and guarantees

| Property | Value |
|---|---|
| **Max datagram payload** | 65,507 bytes (65,535 − 8 UDP − 20 IP) |
| **Max frame payload** | 65,500 bytes (65,507 − 7 Hyb128+TYPE+FLAGS) |
| **Order** | ❌ Not guaranteed |
| **Delivery** | ❌ Not guaranteed (best-effort) |
| **Duplicates** | ❌ Possible (the network may retransmit) |
| **I/O mode** | Non-blocking (Rust: `set_nonblocking(true)`) |

### Benchmark — dgram-shootout (Rust)

5 scenarios, `cargo run --bin dgram-shootout`:

| Scenario | Metric |
|---|---|
| **S1: Roundtrip** | UDP ping-pong for payloads 16B → 65KB. Measures real RTT with echo server/client in separate threads |
| **S2: Unidirectional** | Fire-and-forget at maximum speed. Measures throughput without waiting for ACK |
| **S3: Heartbeat** | Ping-pong with minimal payload (8B). Measures the smallest possible case |
| **S4: Parse overhead** | Build → send → recv → parse. Profiles the full datagram cycle |
| **S5: Max payload** | Stress test with 65,500-byte frames. Verifies integrity under load |

### Test coverage

| Language | Tests | Runner |
|---|---|---|
| **Rust** | 5 scenarios (S1–S5) | `cargo run --bin dgram-shootout` |
| **TypeScript** | **13/13** ✅ | `node --test dist/dgram.test.js` |

> **Conclusion:** Level 3 does not compete with TCP — it complements it. Use Level 1 (stdio/TCP) for RPC request/response and token streaming. Use Level 3 (UDP/multicast) for discovery, telemetry, heartbeats, and log shipping. The lack of TCP handshake and multicast capability make LUMEN Level 3 the ideal layer for **many-to-many communication without a central orchestrator**.

---

## ⚖️ Levels 1, 2, and 3 — Selection Guide

Each transport level solves a different problem. There is no “best” level — there is a **right level for each workload**.

### Latency hierarchy

Estimated *round-trip* latency for a heartbeat (~90 bytes) on local loopback:

```
  Level 2 (SHM)        ▏ ~200–500 ns   (lock-free ring buffer, no kernel)
  Level 3 (UDP)        ▎ ~20–50 µs     (sendto/recvfrom syscall, no handshake)
  Level 1 (TCP)        ▍ ~90–170 µs    (3-way handshake already paid by the connection)
```

And for large payloads (5–64 KB):

```
  Level 2 (SHM)        ▏ ~2–10 µs      (direct memcpy, ~10–20 GB/s)
  Level 3 (UDP)        ▎ ~80–120 µs    (single datagram, no IP fragmentation)
  Level 1 (TCP)        ▍ ~160–180 µs   (TCP segmentation + ACKs)
```

> ⚠️ Level 2 and 3 figures are **expected** based on the design (lock-free ring buffer, single syscall per datagram). Run `cargo run --bin shm-shootout` and `cargo run --bin dgram-shootout` for real numbers on your machine.

### Decision matrix

| Criterion | Level 1 — Stream | Level 2 — SHM | Level 3 — Datagram |
|---|---|---|---|
| **Connection** | Yes (TCP handshake, ~0.5–3 ms) | Yes (mmap + ring setup, ~1–5 ms) | **No** (stateless) |
| **Order** | ✅ Guaranteed | ✅ Guaranteed (SPSC ring) | ❌ Not guaranteed |
| **Delivery** | ✅ Guaranteed | ✅ Guaranteed (buffer in RAM) | ❌ Best-effort |
| **Typical latency** | ~100–700 µs (kernel TCP) | **~0.2–10 µs** (pure user-space) | ~20–120 µs (single syscall) |
| **Throughput** | ~50–500 MB/s (TCP stack) | **~10–20 GB/s** (RAM bandwidth) | ~100–500 MB/s (NIC/kernel) |
| **Topology** | 1:1 (point-to-point) | 1:1 (same-machine processes) | **1:N, N:M** (native multicast) |
| **Multi-machine** | ✅ Yes | ❌ Same machine only | ✅ Yes |
| **Fire-and-forget** | ❌ TCP forces ACKs | ❌ Ring buffer is synchronous | ✅ Natural |
| **Discovery** | ❌ Need to know IP:port | ❌ Need known path | ✅ **Multicast DISCOVER** |
| **CPU overhead** | Medium (kernel↔user copy) | **Minimal** (zero-copy, memcpy) | Low (syscall per datagram) |
| **Ideal case** | RPC + token streaming | **Large files between processes** | Telemetry + heartbeats + discovery |

### Choice by workload

```
                    ┌─────────────────────────────────────────────┐
                    │ Are the processes on the same machine?       │
                    └─────────────────────────────────────────────┘
                                   │
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
                   Yes         Doesn't matter     No
                    │              │              │
            ┌───────┴───────┐      │      ┌───────┴───────┐
            │ Payload >1KB? │      │      │ Need automatic │
            └───────────────┘      │      │ discovery?     │
            │         │           │      └───────────────┘
            ▼         ▼           │          │         │
           Yes        No          │         Yes        No
            │         │           │          │         │
            ▼         ▼           │          │         │
        ┌────────┐ ┌────────┐    │     ┌────────┐ ┌────────┐
        │Level 2 │ │Level 1 │    │     │Level 3 │ │Level 1 │
        │  SHM   │ │ (TCP)  │    │     │  UDP   │ │ (TCP)  │
        └────────┘ └────────┘    │     └────────┘ └────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
               Delivery      Fire-and-     Both
               guarantee?    forget?       processes
                    │            │          local?
                    ▼            ▼            ▼
                Level 1      Level 3      Level 2
                 (TCP)        (UDP)        (SHM)
```

### Combining levels in practice

A typical LUMEN agent uses **all three levels simultaneously**:

| Task | Level | Why |
|---|---|---|
| `tools/call` request/response | **Level 1** (TCP) | Delivery guarantee, ordering, result streaming |
| `llm/stream` tokens | **Level 1** (TCP) | Strict token ordering, kernel backpressure |
| Workspace indexing (files >1 KB) | **Level 2** (SHM) | Zero-copy: 10–20 GB/s without touching the TCP stack |
| Remote communication between agents | **Level 4** (QUIC) | Native TLS 1.3, multi-stream, no head-of-line blocking |
| Heartbeats (keep-alive) | **Level 3** (UDP) | Stateless, connectionless, fire-and-forget |
| Service discovery (what agents exist?) | **Level 3** (multicast) | One DISCOVER frame → N responses, no registry |
| Telemetry / metrics | **Level 3** (UDP) | High throughput, tolerated loss |
| Log shipping | **Level 3** (UDP) | No backpressure, receiver filters what it can |

> **Golden rule:** If the message absolutely must arrive → Level 1. If it must arrive at maximum speed → Level 2. If it must reach many destinations without configuring each one → Level 3. If you need secure remote communication with multi-streaming → Level 4 (QUIC).

---

## 🛠️ Workspace Indexing Shootout (Cadencia)

Simulates the real **Cadencia** workload by analyzing a project: reads all source files from the directory and serializes them as MCP frames. Measured with `cargo run --bin workspace-shootout`:

```
╔══════════════════════╤══════════════╤══════════════╤═══════════════╗
║ Metric               │ JSON-RPC     │ LUMEN        │ Advantage      ║
╠══════════════════════╪══════════════╪══════════════╪═══════════════╣
║ Encode time          │    0.024 s   │    0.004 s   │    5.62× FASTER ║
║ Throughput           │     8.6 MB/s │    45.3 MB/s │    5.25× MORE   ║
║ Time per file        │    1.062 ms  │    0.189 ms  │    5.62× FASTER ║
║ Wire bytes (total)   │     0.21 MB  │     0.20 MB  │    6.6% LESS   ║
╚══════════════════════╧══════════════╧══════════════╧═══════════════╝

  Projection 5,000 files → JSON-RPC: 5.3s  |  LUMEN: 0.9s  |  5.6× faster
  With files >100KB (real source code) → up to 7× faster (see S2)
```

> **For Cadencia:** 80% of workspace indexing time goes into serializing long strings with JSON escapes (`\"`, `\n`, `\t`). LUMEN copies raw bytes without touching them.

---

## 🔧 Rust FFI (C ABI) — Native Bindings

The Rust crate exports a stable C interface (`cdylib`) with 10 `extern "C"` functions:

### Compression (5 functions)

| Function | Signature | Description |
|----------|-----------|-------------|
| `lumen_compress` | `(data, len, out, outLen) → i32` | Compresses JSON → LUMEN binary |
| `lumen_decompress` | `(data, len, out, outLen) → i32` | Decompresses LUMEN binary → JSON |
| `lumen_free` | `(ptr)` | Frees buffer allocated by Rust |
| `lumen_version` | `() → *const c_char` | Library version |
| `lumen_error_message` | `() → *const c_char` | Last error message |

### Zero-Copy Shared Memory (5 functions, Level 2)

| Function | Signature | Description |
|----------|-----------|-------------|
| `lumen_shm_create` | `(name, name_len, size) → *ShmOpaque` | Creates SHM region (server) |
| `lumen_shm_open` | `(name, name_len, size) → *ShmOpaque` | Opens SHM region (client) |
| `lumen_shm_write_frame` | `(h, side, data, data_len) → i32` | Writes frame to ring buffer |
| `lumen_shm_read_frame` | `(h, side, buf, buf_cap, out_len) → i32` | Reads frame from ring buffer |
| `lumen_shm_close` | `(h)` | Closes and frees the SHM region |

```c
// Example from C
int32_t len = lumen_compress(json_bytes, json_len, &out, &out_len);
```

The FFI lets any language with C FFI support (Node, Python, C#, Go, Zig, etc.)
benefit from the high-performance Rust compressor without reimplementing the protocol.

### Node.js (koffi)

```typescript
import { compressValueFFI, decompressValueFFI } from "@lumen/mcp-transport";

const compressed = compressValueFFI({ jsonrpc: "2.0", method: "tools/list" });
const original = decompressValueFFI(compressed);
```

Uses [koffi](https://koffi.dev/) (pure JS, zero build) to load `lumen.dll` / `liblumen.so`.

### Node.js — Zero-Copy SHM (Level 2)

```typescript
import { ShmTransportFFI } from "@lumen/mcp-transport";

// Server
const server = ShmTransportFFI.createServer("/lumen-shm-demo");
server.writeFrame(Buffer.from("hello from server"));
const req = server.readFrame();  // null if no data

// Client (another process)
const client = ShmTransportFFI.openClient("/lumen-shm-demo");
client.writeFrame(Buffer.from("hello from client"));
const res = client.readFrame();  // "hello from server"

server.close(); client.close();
```

Zero-copy inter-process communication via lock-free SPSC ring buffers over
native shared memory (Rust `ShmRegion` → koffi FFI → Node.js `ShmTransportFFI`).

### C# (.NET 9 P/Invoke)

```csharp
using Lumen;

var compressed = LumenFFI.CompressValue(jsonElement);
var decompressed = LumenFFI.DecompressValue(compressed);
```

P/Invoke with `[DllImport("lumen")]` and `CallingConvention.Cdecl`. Zero dependencies.

---

## 🎯 C# Implementation (.NET 9)

```bash
cd implementations/csharp
dotnet run -c Release
```

### Results — 17/17 roundtrip, 28/28 golden, 0 failures

| Suite | Result |
|-------|--------|
| Roundtrip (17 cases) | 17/17 ✅ |
| FFI roundtrip + cross-check | 17/17 ✅ |
| Golden binary (28 files) | 28/28 ✅ |
| Golden FFI | 28/28 ✅ |

### Benchmark — .NET 9, C# native vs P/Invoke FFI

| Payload | Op | Native | FFI | Speedup |
|---------|----|--------|-----|---------|
| MCP tools/list | compress | 2.1µs | 3.6µs | 0.6× |
| MCP tools/list | decompress | 6.5µs | 5.2µs | 1.2× |
| MCP initialize | compress | 6.7µs | 7.2µs | 0.9× |
| MCP initialize | decompress | 18.0µs | 17.8µs | 1.0× |
| MCP tools ×20 | compress | 234.9µs | 244.5µs | 1.0× |
| MCP tools ×20 | **decompress** | 463.7µs | 161.8µs | **2.9×** |
| LLM response | decompress | 14.1µs | 8.9µs | **1.6×** |
| **TOTAL** | compress | 250.2µs | 263.1µs | 1.0× |
| **TOTAL** | **decompress** | 502.3µs | 193.6µs | **2.6×** |

> **FFI decompress is 2.6× faster.** The FFI returns JSON directly from Rust,
> while the native C# decoder builds intermediate trees (`Dictionary<string, object?>`,
> `object[]`) and re-serializes them with `JsonSerializer`. The compression FFI is equivalent
> (1.0×) — the native C# encoder is already optimized with `ArrayPool<byte>` and `stackalloc`.

### Implementation details

| Feature | Detail |
|---------|--------|
| **Native encoder** | `System.Text.Json` + `ArrayPool<byte>` + `stackalloc` — zero alloc on the hot path |
| **Native decoder** | Intermediate `Dictionary<string, object?>` / `object[]` → `JsonSerializer.SerializeToElement` |
| **FFI** | P/Invoke `[DllImport]`, `CallingConvention.Cdecl`, `nint` for pointers |
| **Dictionary** | `Dict.cs` — 128 static entries with O(1) lookup and reverse lookup |
| **Hyb128** | `Hyb128.cs` — encode/decode with the 4 modes (00/10/11/01) |

---

## 📊 Multi-Language FFI Benchmark

Performance comparison of the Rust FFI vs the native implementation in each language:

| Language | Compress (FFI vs native) | Decompress (FFI vs native) | FFI library |
|----------|--------------------------|----------------------------|-------------|
| **Node.js** | **4.4× faster** 🔥 | 1.0× | [koffi](https://koffi.dev/) v3.0.2 |
| **C# (.NET 9)** | 1.0× | **2.6× faster** 🔥 | P/Invoke `[DllImport]` |
| **Python** | 0.5× (slower) | 0.5× (slower) | `ctypes` (stdlib) |

> **Node.js:** The FFI shines in compression because TS `compressValue` goes through the V8 JIT
> while Rust runs native. In decompress, TS `decompressValue` is already highly optimized
> and the FFI adds no advantage.
>
> **C#:** The FFI wins in decompress because Rust returns already parsed JSON, avoiding
> reconstruction of intermediate trees. In compress, the native C# encoder with
> `ArrayPool<byte>` matches Rust.
>
> **Python:** `ctypes` has high overhead (marshalling Python objects ↔ C).
> For small payloads, overhead dominates and the FFI is slower than CPython's
> native encoder (which is already in C).

---

## 🐘 PHP Implementation (lumen-php)

```bash
cd implementations/php
php tests/e2e_test.php          # cross-implementation e2e: 217/217
php bench.php > bench_out.json  # benchmark suite (74 results)
```

### Results — 217/217 e2e tests passing (PHP 8.5.7)

| Suite | Tests |
|-------|-------|
| Compress roundtrip + golden binary | 27+28 ✅ |
| Hyb128 encode/decode | 22 ✅ |
| Frame parse | 22 ✅ |
| Compressed frame integration | 118 ✅ |
| **Total** | **217/217 ✅** |

### Benchmark — PHP 8.5.7: json_encode/decode vs compress/decompress

| Payload | json encode | LUMEN encode | Ratio | json decode | LUMEN decode | Ratio |
|---------|------------|--------------|-------|------------|--------------|-------|
| initialize (157B→91B) | 1.4µs | 33.4µs | 0.04× | 6.5µs | 29.0µs | 0.22× |
| tools_list (835B→386B) | 9.4µs | 170.6µs | 0.06× | 39.1µs | 215.7µs | 0.18× |
| llm_request (323B→166B) | 5.3µs | 62.2µs | 0.08× | 15.8µs | 93.3µs | 0.17× |
| error_response (175B→95B) | 2.1µs | 26.3µs | 0.08× | 6.2µs | 32.0µs | 0.19× |
| **big_result (5193B→5104B)** | 14.2µs | 41.6µs | **0.34×** | 30.3µs | 43.7µs | **0.69×** |

> **PHP json_encode/decode wins on speed** — same pattern as Python: `json_encode` and
> `json_decode` are Zend engine C extensions (12–24× faster for small payloads),
> while `compress`/`decompress` are interpreted PHP bytecode. The gap narrows
> with large payloads: in `big_result` (5 KB), LUMEN decode is only **1.44× slower**
> because it avoids string escaping.
>
> **LUMEN's advantage in PHP is wire size** (46–54% savings on typical MCP payloads)
> and **cross-language binary compatibility** with Python, TypeScript, Rust, and C#.

### PHP wire size (same protocol, same bytes)

| Payload | JSON | LUMEN | Saving |
|---------|------|-------|--------|
| initialize | 157 B | 91 B | **42%** |
| tools_list | 835 B | 386 B | **54%** |
| llm_request | 323 B | 166 B | **49%** |
| error_response | 175 B | 95 B | **46%** |
| big_result | 5,193 B | 5,104 B | 2% |

### Hyb128 — PHP 8.5.7

| Operation | Best case | Worst case (mode >1B) |
|-----------|-----------|-----------------------|
| **Encode** | 4.3M/s (1B mode) | 1.5M/s (3/5B mode) |
| **Decode** | 2.8M/s (1B mode) | 0.5M/s (5B mode) |

> PHP Hyb128 is 10–20× slower than TypeScript because it is pure bytecode (vs V8 JIT).
> Content-Length framing is faster than Hyb128 in PHP (the opposite of TS),
> because `preg_match`/`substr` are C functions while Hyb128 is pure PHP.

---

## 🔌 Cadencia Bridge (Rust Sidecar)

A minimal binary that the VS Code extension runs as a child process. It receives JSON commands over stdin, reads files from disk, compresses them with LUMEN, and returns binary frames. **Zero runtime dependencies** — it only needs the compiled binary.

```bash
# Manual sidecar test
echo '{"cmd":"index","files":["Cargo.toml","src/lib.rs","src/frame.rs"]}' \
  | cargo run --bin cadencia-bridge

# Output:
# {"status":"ok","version":"0.1.0","protocol":"lumen/1"}
# {"status":"ok","files":3,"total_bytes":21530,"wire_bytes":21572,...}
```

### Protocol (line-delimited JSON over stdin/stdout)

| Command | Description |
|---------|-------------|
| `{"cmd":"ping"}` | Initial handshake → `{"status":"ok","version":"0.1.0","protocol":"lumen/1"}` |
| `{"cmd":"index","files":[...]}` | Reads and compresses files → wire/time stats |
| `{"cmd":"stop"}` | Graceful shutdown |

### TypeScript client

```typescript
import { CadenciaBridge } from "@lumen/mcp-transport";

const bridge = new CadenciaBridge({
  binaryPath: "./cadencia-bridge", // compiled from implementations/rust
  cwd: workspaceRoot,
});

await bridge.start();                    // handshake
const result = await bridge.index([     // index 5000 files
  "src/main.ts", "src/utils.ts", /* ... */
]);
console.log(result);                     // { files: 5000, total_bytes: ..., wire_bytes: ..., encode_us: ... }
await bridge.stop();
```

---

## 📊 TypeScript Benchmark Suite

**122 benchmarks in 18 categories**, run with `node --expose-gc --import tsx src/bench.ts`. Results in `implementations/typescript/bench_results_full.json`.

### 🧪 Test Suite — 755+ tests passing

| Suite | Tests | Language | Runner |
|---|---|---|---|
| LUMEN Rust core | **94/94** | Rust | `cargo test --features quic -- --test-threads=1` |
| FrameAssembler stress | **17/17** | TypeScript | `node --test` |
| ZeroAllocDecompressor | **79/79** | TypeScript | `node --test` |
| SHM FFI (Level 2) | **10/10** | TS ↔ Rust | `node --test dist/shm_ffi.test.js` |
| Datagram (Level 3) | **13/13** | TypeScript | `node --test dist/dgram.test.js` |
| **TS e2e cross-impl** | **217/217** | TypeScript | `npx tsx --test src/e2e.test.ts` |
| CadenciaBridge integration | **3/3** | TS ↔ Rust | `node --test` |
| Python unit tests | **94/94** | Python | `pytest` |
| C# roundtrip + golden | **17/17 + 28/28** | C# (.NET 9) | `dotnet run` |
| C# FFI (P/Invoke) | **17/17 + 28/28** | C# ↔ Rust | `dotnet run` |
| PHP e2e (roundtrip + golden + frames) | **217/217** | PHP 8.5 | `php tests/e2e_test.php` |

### 🔗 Cross-Implementation E2E — 588 tests

Golden file testing across the 5 implementations (Python generates, the rest validate):

| Implementation | E2E Tests | Scope | Status |
|---|---|---|---|
| **Python** | 89/89 | 28 vectors × golden generate/validate | ✅ Generates golden binaries |
| **TypeScript** | 217/217 | Full suite (compress + Hyb128 + Frame + integr.) | ✅ Binary match + cross-decode |
| **Rust** | 9/9 | 9 `#[test]` fn at ~28 iters each (~250 assertions) | ✅ Semantic match + Hyb128 + frames |
| **C# (.NET 9)** | 28/28 | Compress/decompress golden (no Hyb128/Frame) | ✅ Byte-for-byte binary match |
| **C# FFI (P/Invoke)** | 28/28 | Compress/decompress via Rust FFI | ✅ Byte-for-byte binary match |
| **PHP 8.5** | 217/217 | Full suite (compress + Hyb128 + Frame + integr.) | ✅ Binary match + frame integration |

> **Why do PHP and TS have 217 while Rust has only 9?**
> PHP and TS use the same e2e structure: 28 vectors × 3 tests + 8 stability + 11 Hyb128
> + 36 frame roundtrip + 72 frame compat + 6 integration = **217 individual tests**.
> Rust uses the `#[test]` convention with one function per test type that internally iterates
> over all vectors — same coverage, different count.
> C# has a benchmark-focused harness and only validates compress/decompress.

The 28 shared vectors in `tests/e2e/shared_vectors.json` cover all LUMEN
value types (null, bool, int, float, string, array, object) and real MCP payloads
(initialize, tools/list, llm_request, error_response).

### 🥊 TypeScript — Where LUMEN wins

The TypeScript implementation of LUMEN prioritizes **wire size** and **efficient framing**. For high-CPU-speed scenarios, it uses the native Rust FFI (`compressValueFFI`, **4.4× faster**) or the `ZeroAllocDecompressor` (**54% less GC**). Pure speed benchmarks are in the Rust sections above (shootout, heap-shootout, concurrent, IPC, workspace).

### ⚡ A. FrameAssembler — Zero-Allocation Streaming Parser

Binary parser with pre-allocated buffers. Measures frames/second and throughput in MB/s for 5 sizes × 7 chunk sizes:

| Payload | fps (chunk=full) | MB/s |
|---|---|---|
| 16 B (tiny) | 57,789 | 1.10 |
| 256 B (small) | 164,373 | 41.06 |
| 4 KB (medium) | 227,340 | **888** |
| 64 KB (large) | 18,429 | **1,152** |
| 256 KB (xlarge) | 4,868 | **1,217** |

> **Saturates at ~1.2 GB/s** from 4 KB onward. The parser allocates nothing — it reuses pre-allocated `Uint8Array` buffers.

#### Chunk-size stress (payload=4KB)

| Chunk | fps | Interpretation |
|---|---|---|
| 1 byte (torture) | 114,599 | Worst case: 4096 calls to `push()` |
| 16 bytes | 259,510 | Typical network fragmentation |
| 64 bytes | 282,321 | Typical UDP packet |
| 256 bytes | 280,788 | Standard read buffer |
| 4 KB (full) | 227,340 | Best case: 1 frame = 1 chunk |

> Even in the **torture test (1 byte/chunk)**, the parser maintains 114K fps — only 2× slower than the ideal case.

### 📦 B. Compression — JSON vs LUMEN (wire bytes)

Same real MCP payloads, measured with the `compress.ts` codec:

| MCP scenario | JSON | LUMEN | Ratio | Saving |
|---|---|---|---|---|
| `initialize` | 157 B | 92 B | **58.6%** | 65 B (41.4%) |
| `tools/list` | 835 B | 386 B | **46.2%** | 449 B (53.8%) |
| `llm_request` | 323 B | 166 B | **51.4%** | 157 B (48.6%) |
| `error_response` | 175 B | 95 B | **54.3%** | 80 B (45.7%) |
| `big_result` (5 KB) | 5,193 B | 5,104 B | **98.3%** | 89 B (1.7%) |

> **Average on typical MCP payloads: 47–55% compression.** Only in massive payloads without repeated keys (>5 KB) does binary tag overhead become diluted.

### 🔢 C. Hyb128 Codec — Encode/Decode

Microbenchmarks of the hybrid length codec. 11 values covering modes 00, 10, 11:

| Operation | Best case | Worst case | Average |
|---|---|---|---|
| **Decode** | 49.3M/s (`0`, mode 00) | 8.3M/s (`1`, mode 00) | ~30M/s |
| **Encode** | 30.7M/s (`0`, mode 00) | 10.1M/s (`63`, boundary) | ~20M/s |

> Decode is **~1.5× faster** than encode. Encode suffers at mode boundaries because of branching.

### 📖 D. Dict O(1) Lookup

| Metric | Value |
|---|---|
| `Map.get()` O(1) | **20.8M/s** |
| Operations | 1,000,000 |
| Duration | ~48 ms |

### 🔗 TypeScript ↔ Rust Integration (CadenciaBridge)

The Rust sidecar runs as a child process. TypeScript sends JSON commands over stdin, Rust returns LUMEN frames:

| Test | Result |
|---|---|
| Ping handshake | ✅ 21.8 ms |
| Index 30K files | ✅ 17.6 ms (encode: 163 µs) |
| Graceful shutdown | ✅ 4.4 ms |

---

### 📏 H. Framing: Content-Length vs Hyb128 (header parse)

| Value | CL ops/s | Hyb128 ops/s | Ratio | Bytes (CL→Hyb) |
|---|---|---|---|---|
| 0 | 6.28M | **37.0M** | 5.9× | 21→1 |
| 42 | 4.35M | **15.5M** | 3.6× | 22→1 |
| 255 | 5.15M | **38.9M** | 7.6× | 23→3 |
| 1024 | 5.92M | **42.2M** | 7.1× | 24→3 |
| 65535 | 5.69M | **45.3M** | 8.0× | 25→3 |
| 1000000 | 5.64M | **38.7M** | 6.9× | 27→5 |

> 🏆 **LUMEN dominates**: Hyb128 parsing is **3.6–8× faster** and uses **5–21× fewer bytes** than Content-Length. The parser knows in 1 cycle how much to skip.

---

### 🪢 I. String Escape — JSON.stringify vs LUMEN raw copy

JSON.stringify must inspect **each character** looking for `"`, `\`, `\n`, `\t`, `\r` and escape them with `\`. LUMEN performs a raw binary copy — no inspection and no expansion.

| Payload | JSON ops/s | LUMEN ops/s | Speedup | Wire (JSON→LUMEN) |
|---|---|---|---|---|
| code_json_1KB | 125,893 | 117,189 | 0.93× | 1,589→1,398 (-12%) |
| **quotes_heavy** | 36,589 | 79,982 | **2.19×** 🔥 | 8,025→4,018 (-50%) |
| newlines_tabs | 17,933 | 20,206 | **1.13×** | 15,014→13,007 (-13%) |
| backslash_hell | 47,635 | 71,755 | **1.51×** | 6,020→3,013 (-50%) |
| mixed_escape_4KB | 42,401 | 53,798 | **1.27×** | 5,594→4,447 (-20%) |

> 🏆 **LUMEN wins 4 of 5 scenarios.** In `quotes_heavy` (strings with many quotes), LUMEN is **2.19× faster** and produces **half the bytes**. The only loss is `code_json_1KB` (0.93×), where there are few special characters and binary format overhead is not amortized. **Raw binary copy is structurally superior to JSON's escaping model.**

### 🧠 ZeroAllocDecompressor — 54% less GC

The original TypeScript decoder (`decompressValue`) was recursive and generated temporary objects (tags, string fragments, stack frames). The optimized version (`ZeroAllocDecompressor`, `src/zeroalloc.ts`) uses an iterative loop with a pre-allocated stack and shared buffers — **with no intermediate objects on the hot path**.

Results measured with `node --expose-gc` over a 500-tool payload:

| Decoder | Heap Δ | vs JSON | Garbage eliminated |
|---|---|---|---|
| `JSON.parse` (native C++) | ~380 KB | 1.0× | baseline |
| `decompressValue` (original recursive) | ~3,030 KB | 8.0× | — |
| **`ZeroAllocDecompressor`** | **~1,400 KB** | **3.7×** | **🔥 54% less** |

**Optimizations applied:**
- Shared module-level `TextDecoder` — zero allocs per string
- Inline Hyb128 — no intermediate `{ value, headerLen }` allocations
- Iterative loop + frame pool — no recursion, reused stack
- Shared dict refs — dictionary keys return the same reference

> 🏆 **54% less garbage without touching the protocol or adding build steps.** The remaining garbage (~1 MB) is the real unique strings and `subarray()` views for UTF-8 — data also retained by `JSON.parse`. The Rust FFI (`compressValueFFI`) complements this with **4.4× more speed** on encode.

### 🆚 Comparative Summary

| # | Metric | Winner | Detail |
|---|---|---|---|
| 1 | Wire size | **LUMEN** | 30–83% smaller (Rust shootout + section B) |
| 2 | Encode speed | **LUMEN** (Rust/FFI) | Rust: 1.6–7×, TS FFI: 4.4× |
| 3 | Framing parse | **LUMEN** | Hyb128 3.6–8× vs Content-Length |
| 4 | String escape | **LUMEN** | Raw binary copy, 1.1–2.2× faster |
| 5 | GC pressure | **LUMEN** (ZeroAlloc) | 54% less garbage vs recursive decoder |
| 6 | Streaming | **LUMEN** | ~12 B/token vs ~75 B/token JSON |
| 7 | Zero-Copy | **LUMEN** | SHM Level 2 (mmap/ring buffers) |

---

## 📝 License

MIT
