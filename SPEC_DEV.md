# LUMEN — Protocol Specification v1.0-draft

> **L**ightweight **U**niversal **M**odel **E**xchange **N**etwork

---

## 1. Overview and Philosophy

### 1.1 The JSON-RPC problem

MCP (Model Context Protocol) uses JSON-RPC 2.0 as its messaging layer. Although functional, it has shortcomings:

| Problem | Impact |
|----------|---------|
| Repeated keys per message (`jsonrpc`, `id`, `method`) | ~40–60 bytes of fixed overhead |
| Text parsing (UTF-8 → DOM → native types) | CPU penalty at each endpoint |
| No native key compression | The same strings are re-serialized millions of times |
| No token streaming support | Each LLM token requires a full JSON frame |
| No zero-copy | Payloads are copied between buffers during serialization/deserialization |
| No zero-trust | No permission attenuation mechanism between agents |

### 1.2 LUMEN design principles

1. **Local-first**: The primary profile is local IPC (stdio, UDS). The web is secondary.
2. **Zero-copy whenever possible**: Payloads are referenced, not copied.
3. **Zero-trust by design**: Each endpoint carries its own attenuable Capability Tokens.
4. **Pay only for what is used**: No fixed columns for optional features (MUX, encryption).
5. **O(1) on the hot path**: The header parser never iterates for common modes.
6. **Self-delimiting**: Frames do not depend on external delimiters (`\n`, HTTP framing).

---

## 2. Transport Abstraction (LTA)

LUMEN is **transport-agnostic**, but it requires a minimum contract by level.

### 2.1 Level 1 — Stream (required)

```
Requirements:
  ✅ Guaranteed ordering (FIFO)
  ✅ No byte loss
  ✅ Full-duplex

Transports that satisfy it:
  • stdio (stdin/stdout pipes)
  • Unix Domain Sockets (SOCK_STREAM)
  • Named Pipes (Windows)
  • TCP
  • WebSocket (binary frames)
```

This is the base level. Any LUMEN implementation **must** support Level 1.

### 2.2 Level 2 — Zero-Copy (implemented in Rust)

```
Additional requirements:
  ✅ Everything from Level 1
  ✅ Shared memory between endpoints (mmap / shm on Unix, CreateFileMapping on Windows)
  ✅ Frames without serialization (direct memory casts via ring buffers)
  ✅ In-band negotiation with TYPE_TRANSPORT_INIT (0x0B) / TYPE_TRANSPORT_ACK (0x0C)

Transports that satisfy it:
  • Unix: shm_open + mmap (MAP_SHARED) with path like /lumen-shm-<ts>-<pid>
  • Windows: CreateFileMappingW + MapViewOfFile with unique name
  • WASM: unsupported (stub returning Unsupported)

Ring buffer architecture:
  ┌─────────────────────────────────────────────────────────────┐
  │ Header (128 bytes): magic="LUME", version=1, layout info    │
  │   Ring A: write_a cursor (client), read_a cursor (server)   │
  │   Ring B: write_b cursor (server), read_b cursor (client)   │
  ├─────────────────────────────────────────────────────────────┤
  │ Ring A data: Client → Server  (~256 KiB)                    │
  │ Ring B data: Server → Client  (~256 KiB)                    │
  └─────────────────────────────────────────────────────────────┘
  Default region: 512 KiB total. SPSC lock-free with AtomicU64.
  Each frame is prefixed with a 4-byte LE length.
```

Negotiation:
```
Client → Server:  TYPE_TRANSPORT_INIT (0x0B) → { "caps": ["mmap","stdio"] }
Server → Client:  TYPE_TRANSPORT_ACK  (0x0C) → { "cap":"mmap",
                                                     "shm_path":"/lumen-shm-<ts>-<pid>",
                                                     "shm_size":524288 }
```

If the handshake fails or mmap is unavailable, it automatically degrades to Level 1.

### 2.3 Level 3 — Datagram (implemented)

```
Additional requirements:
  ✅ Everything from Level 1
  ✅ UDP unicast (send_to / recv_from)
  ✅ Non-blocking mode
  ✅ IPv4 multicast (join/leave, configurable TTL, loopback)
  ✅ Each datagram = exactly 1 complete LUMEN frame

Guarantees:
  ❌ No ordering guarantee
  ❌ No delivery guarantee
  ❌ No duplicate suppression

Transports that satisfy it:
  • UDP (std::net::UdpSocket in Rust, node:dgram in TypeScript)
  • IPv4 multicast (239.0.0.0/8, default TTL = 1)

Limits:
  • MAX_DATAGRAM_SIZE = 65507 bytes (65535 − 8 UDP − 20 IP)
  • MAX_FRAME_PAYLOAD  = 65500 bytes (MAX_DATAGRAM_SIZE − 7 Hyb128+TYPE+FLAGS overhead)

Use cases:
  • Telemetry / metrics (fire-and-forget)
  • Heartbeats (keep-alive best-effort)
  • Log shipping (high throughput, loss-tolerant)
  • Service discovery (multicast DISCOVER frames)
```

Architecture:

```
┌─────────────────────────────────────────────────┐
│ DatagramTransport                               │
│   socket: UdpSocket (non-blocking)              │
│   recv_buf: [u8; 65507]                         │
│                                                 │
│   bind(addr)         → Self                     │
│   connect(local,remote) → Self (connected UDP)   │
│   send_frame_to(fr,addr) → bytes sent           │
│   recv_frame()       → Option<(&[u8], SrcAddr)> │
│   join_multicast(maddr, iface)                  │
│   set_multicast_ttl(ttl)                        │
│   set_multicast_loop(on/off)                    │
└─────────────────────────────────────────────────┘

Included benchmarks (bin/dgram-shootout.rs):
  S1: Roundtrip latency (ping-pong), payloads 16B → 65KB
  S2: Unidirectional throughput (fire-and-forget)
  S3: Heartbeat ping-pong (8B payload)
  S4: Frame parse overhead (build → send → recv → parse)
  S5: Max payload stress test (65500B payload, 100 frames)

TypeScript: DatagramTransport in src/dgram.ts (node:dgram).
  13 tests: bind, send/recv unicast, multiple frames, parse, close, binary payload.
```

---

## 3. Frame Anatomy

### 3.1 General structure

```
┌──────────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [TYPE:1B] [FLAGS:1B] [PAYLOAD:LEN bytes]   │
└──────────────────────────────────────────────────────────┘

Minimum overhead: 3 bytes (payload 0–63 B)
Typical overhead: 4 bytes (payload 64 B–64 KB)
Maximum overhead: 12 bytes (payload > 4 GB, LEB128)
```

### 3.2 Hyb128 — Hybrid length encoding

The first byte of the frame encodes the payload length in its top 2 bits:

```
Byte 0: [MODE:2bits] [VALUE:6bits]
```

| Mode | Bits | Decoding | Total bytes | Range |
|------|------|----------|-------------|-------|
| `00` | `00xxxxxx` | The low 6 bits are the length | **1** | 0–63 |
| `01` | `01xxxxxx` | Following bytes in LEB128 | **2–11** | > 4 GB |
| `10` | `10xxxxxx` | Next 2 bytes as little-endian u16 | **3** | 64–65535 |
| `11` | `11xxxxxx` | Next 4 bytes as little-endian u32 | **5** | 65536–4294967295 |

#### O(1) property

For modes `00`, `10`, and `11`, the parser knows **in a single CPU read** how many additional bytes to read:

```
mode = first_byte >> 6;

switch (mode) {
    0b00: len = first_byte & 0x3F;           skip = 0;
    0b10: len = read_u16_le(buf[1..3]);      skip = 2;
    0b11: len = read_u32_le(buf[1..5]);      skip = 4;
    0b01: len = leb128_decode(&buf[1..]);    skip = variable;
}
```

There are no loops on the hot path. About 90% of MCP messages fall into modes `00` or `10`.

> **Reference implementation**: [`hyb128.rs`](implementations/rust/src/hyb128.rs)

### 3.3 Fixed header (TYPE + FLAGS)

Immediately after Hyb128:

```
[TYPE:1B] [FLAGS:1B]
```

**TYPE** — identifies frame semantics:

| ID | Constant | Direction | Description |
|----|----------|-----------|-------------|
| `0x01` | `REQUEST` | C→S, S→C | Request expecting a response |
| `0x02` | `RESPONSE` | S→C, C→S | Response to a REQUEST |
| `0x03` | `NOTIFY` | ↔ | Fire-and-forget, no response |
| `0x04` | `STREAM_DATA` | ↔ | Data chunk for an active stream |
| `0x05` | `SCHEMA_PATCH` | ↔ | Schema delta (add/remove tools, resources) |
| `0x06` | `STREAM_INIT` | ↔ | Initializes a token stream |
| `0x07` | `DICT_SYNC` | ↔ | Session dictionary synchronization |
| `0x08` | `DISCOVER` | ↔ | Dynamic introspection (late binding) |
| `0x09` | `MUX` | ↔ | Multiplexing wrapper |
| `0x0A` | `HEARTBEAT` | ↔ | Keep-alive |
| `0x0B` | `TRANSPORT_INIT` | C→S | Transport capability negotiation init (§2.2) |
| `0x0C` | `TRANSPORT_ACK` | S→C | Transport capability negotiation ack (§2.2) |
| `0x0D–0x0E` | *Reserved* | — | For future expansion |
| `0x0F` | `PROBE` | C→S | Protocol negotiation probe (may carry X25519 public key) |
| `0x10` | `PROBE_ACK` | S→C | Protocol negotiation ack (may carry X25519 public key) |
| `0x11+` | *Reserved* | — | For future expansion |

**FLAGS** — 8-bit bitmask:

| Bit | Constant | Meaning |
|-----|----------|---------|
| `0x01` | `COMPRESSED` | Payload compressed with the LUMEN dictionary |
| `0x02` | `ENCRYPTED` | Encrypted payload |
| `0x04` | `PRIORITY` | Priority frame (skip queues) |
| `0x08` | `FRAGMENTED` | Fragmented frame (continuation in next frame) |
| `0x10–0x80` | *Reserved* | For future expansion |

---

## 4. Workflow and Multiplexing

### 4.1 Request lifecycle

```
Client                                Server
  │                                       │
  │──── REQUEST (id=1, method="tool") ───→│
  │                                       │ process...
  │←─── RESPONSE (id=1, result=...) ─────│
  │                                       │
```

- Each `REQUEST` carries an `id` (dictionary ID `0x04`).
- The `RESPONSE` repeats the `id` for correlation.
- `NOTIFY` does not carry an `id` and does not expect a response.

### 4.2 Multiplexing (MUX)

Frame `0x09 MUX` wraps another LUMEN frame in a logical channel:

```
MUX Frame:
┌──────────────────────────────────────────────────────────────┐
│ [LEN:Hyb128] [0x09] [FLAGS]                                  │
│ [CHANNEL:1B] [CTRL:4b] [RESERVED:4b]                        │
│ [INNER: complete LUMEN frame]                                │
└──────────────────────────────────────────────────────────────┘

CTRL bits:
  bit0: OPEN  — Create logical channel
  bit1: CLOSE — Close logical channel
  bit2: PAUSE — Backpressure (pause sending)
  bit3: RESUME — Resume sending
```

- **No overhead on normal frames**: MUX is paid for only when used.
- **256 logical channels** over a single physical connection.
- **Per-channel flow control**: Avoids head-of-line blocking.

### 4.3 TokenStream — Native streaming for LLMs

```
Initialization:
┌────────────────────────────────────────────┐
│ [0x06] [FLAGS]                             │
│ [STREAM_ID:2B] [TOKEN_TYPE:1B]             │
└────────────────────────────────────────────┘

TOKEN_TYPE:
  0x00 = UTF-8 text tokens
  0x01 = u16 token IDs
  0x02 = u32 token IDs
  0x03 = f32 embeddings (4 bytes)

Data bursts:
┌────────────────────────────────────────────┐
│ [0x04] [FLAGS]                             │
│ [STREAM_ID:2B] [BURST_LEN:Hyb128] [TOKENS] │
└────────────────────────────────────────────┘

Close: BURST_LEN = 0 in STREAM_DATA
```

---

## 5. Semantic Compression (Dictionaries)

### 5.1 Architecture

```
Uncompressed:  {"tool": "search", "arguments": {"query": "hola"}}
Compressed:    {0x00: "search", 0x01: {lookup("query"): "hola"}}
```

### 5.2 Static Dictionary (IDs `0x00–0x7F`)

128 predefined entries. **They never change.** → See [`DICTIONARY.md`](DICTIONARY.md).

### 5.3 Session Dictionary (IDs `0x80–0xFE`)

127 entries negotiated during handshake and updateable via `DICT_SYNC` (`0x07`):

```
DICT_SYNC payload:
[OP:1B] [ENTRY_COUNT:1B] [ENTRIES...]

OP:
  0x00 = ADD
  0x01 = REMOVE
  0x02 = REPLACE

ENTRY: [ID:1B] [KEY_LEN:1B] [KEY:N]
```

API available in all 5 languages: `register_session_key`, `unregister_session_key`,
`init_session_dict`, `clear_session_dict`, `session_dict_size`.

### 5.4 Synchronization

```
Client: "My dict v3, 142 entries"
Server: "I have v3 with 140. Sending delta."
          → SCHEMA_PATCH ADD entries 141, 142
Client: "ACK complete dict v3 (142 entries)"
```

### 5.5 ID 0xFF — Uncompressed key

When a key is not in any dictionary, it is transmitted as plain text.

---

## 6. Late Binding — Dynamic Discovery

### 6.1 DISCOVER (0x08)

```
DISCOVER Request:  [0x08] [FLAGS] [SCOPE:1B]
SCOPE:
  0x00 = All (tools + resources + prompts + capabilities)
  0x01 = Tools only
  0x02 = Resources only
  0x03 = Capabilities only

DISCOVER Response: [0x02] [FLAGS] [SCOPE:1B] [SCHEMA...]
```

The response may be **incremental** (only what is new since the last synchronization).

---

## 7. Integrated Security (Zero-Trust)

### 7.1 Handshake

```
Client → Server:
  REQUEST { version: 1, capabilities: ["stream"], macaroon: "<token>" }
```

### 7.2 Capability Tokens (Macaroons)

```yaml
caveats:
  - op: "filesystem.read:/home/user/project"
  - op: "tool.call:search_code"
  - exp: "2026-06-11T18:00:00Z"
  - rate: "100/min"
```

### 7.3 Attenuation

A node can **further restrict** a Macaroon without invalidating the signature:

```
Orchestrator receives: op: filesystem.read:/
Delegates to sub-agent: op: filesystem.read:/home/user/project/src  ← attenuated
Sub-agent CANNOT:       ❌ Read /etc/passwd
```

### 7.4 Wire Encryption (ChaCha20-Poly1305 + X25519)

LUMEN supports **authenticated frame-level encryption** using ChaCha20-Poly1305 AEAD
with X25519 key exchange. Encryption is optional and negotiated during the
PROBE/PROBE_ACK handshake.

#### 7.4.1 Encrypted payload format

When `FLAG_ENCRYPTED` (0x02) is active, the frame payload contains:

```
┌──────────────────────────────────────────────────────────────┐
│ [NONCE:12B] [CIPHERTEXT:N bytes] [TAG:16B]                   │
└──────────────────────────────────────────────────────────────┘

Total overhead: 28 bytes (12B nonce + 16B Poly1305 tag)
```

The complete frame on the wire:

```
┌──────────────────────────────────────────────────────────────┐
│ [Hyb128:LEN] [TYPE:1B] [FLAGS:1B | 0x02] [encrypted_payload] │
└──────────────────────────────────────────────────────────────┘
```

#### 7.4.2 Nonce

96-bit ChaCha20-Poly1305 nonce (12 bytes):

```
[NONCE:12B] = [COUNTER:u64 LE][ZEROS:4B]
```

- **Counter**: Monotonically increasing, independent per direction
  (client→server and server→client start at 0).
- **Zeros**: 4 zero bytes to prevent collisions.

The receiver **MUST** reject frames with a nonce less than or equal to the last received nonce
(anti-replay protection).

#### 7.4.3 Key Exchange (X25519)

```
Client                               Server
  │                                      │
  │ 1. Generates X25519 keypair          │
  │ 2. PROBE { pk: <pubkey_b64> }  ────→│
  │                                      │ 3. Generates X25519 keypair
  │                                      │ 4. Derives shared secret
  │ 5. Derives shared secret             │
  │ 6. PROBE_ACK { pk: <pubkey_b64> } ←─│
  │                                      │
  │  ◄════ encrypted frames ════════════►│
```

- Each side generates an **ephemeral** X25519 keypair (not reused between sessions).
- The 32-byte shared secret is used directly as the ChaCha20-Poly1305 key.
- Public keys (32 bytes) are encoded as **base64** inside the PROBE/PROBE_ACK JSON.
- If the server does not include `pk` in its ACK, encryption is **not negotiated** and communication
  continues in plaintext.

#### 7.4.4 API

```rust
// Rust
use lumen::crypto::{Keypair, Cipher};

let kp = Keypair::generate();
let shared = kp.derive_shared_secret(&peer_public);
let mut cipher = Cipher::new(&shared);

let frame = cipher.build_encrypted_frame(TYPE_REQUEST, 0, b"payload");
// ... send frame ...
// ... receive encrypted_payload ...
let plaintext = cipher.decrypt(encrypted_payload).unwrap();
```

```typescript
// TypeScript (Web Crypto API)
import { generateKeypair, deriveSharedSecret, Cipher } from "@lumen/mcp-transport";

const kp = await generateKeypair();
const shared = await deriveSharedSecret(kp.secretKey, peerPublicKey);
const cipher = new Cipher();
await cipher.init(shared);

const frame = await cipher.buildEncryptedFrame(TYPE_REQUEST, 0, payload);
const plaintext = await cipher.decrypt(encryptedPayload);
```

#### 7.4.5 Guarantees

| Property | Mechanism |
|---|---|
| **Confidentiality** | ChaCha20 (stream cipher, 256-bit key) |
| **Integrity** | Poly1305 MAC (authenticates nonce + ciphertext) |
| **Anti-replay** | Monotonic nonce counter (receiver rejects duplicates) |
| **Forward secrecy** | Ephemeral X25519 keypairs (not perfect PFS, but ephemeral per session) |
| **No certificates** | Trust-on-first-use (TOFU) via PROBE/PROBE_ACK |

> ⚠️ **Current limitation:** There is no PKI or identity verification. Encryption protects
> against passive eavesdropping and active MITM (thanks to AEAD), but it does not authenticate
> peer identity. For mutual authentication, combine with Macaroons (§7.2).

### 7.5 Implementations

| Language | Module | Encryption | Key Exchange |
|---|---:|---:|---:|
| **Rust** | `crypto.rs` | ✅ ChaCha20-Poly1305 | ✅ X25519 |
| **TypeScript** | `crypto.ts` | ✅ ChaCha20-Poly1305 (WebCrypto) | ✅ X25519 (WebCrypto) |
| **Python** | *(pending)* | — | — |
| **C#** | *(pending)* | — | — |
| **PHP** | *(pending)* | — | — |

---

## 8. Reference Tables

### 8.1 Frame Types

| ID | Type | Additional overhead |
|----|------|---------------------|
| `0x01` | REQUEST | 0 |
| `0x02` | RESPONSE | 0 |
| `0x03` | NOTIFY | 0 |
| `0x04` | STREAM_DATA | 2B (stream_id) + Hyb128 (burst_len) |
| `0x05` | SCHEMA_PATCH | 2B (op + count) |
| `0x06` | STREAM_INIT | 3B (stream_id + token_type) |
| `0x07` | DICT_SYNC | 2B (dict_version) |
| `0x08` | DISCOVER | 1B (scope) |
| `0x09` | MUX | 2B (channel + ctrl) |
| `0x0A` | HEARTBEAT | 0 |

### 8.2 Flags

| Bit | Mask | Name |
|-----|------|------|
| 0 | `0x01` | COMPRESSED |
| 1 | `0x02` | ENCRYPTED |
| 2 | `0x04` | PRIORITY |
| 3 | `0x08` | FRAGMENTED |

> `ENCRYPTED` (bit 1, 0x02): The payload contains a blob encrypted with ChaCha20-Poly1305.
> See §7.4 for the complete encryption format and X25519 handshake.

---

## 9. References

- [Model Context Protocol (MCP)](https://modelcontextprotocol.io/)
- [Macaroons: Cookies with Contextual Caveats](https://research.google/pubs/pub41892/)
- [LEB128 Encoding](https://en.wikipedia.org/wiki/LEB128)
- Reference implementation: [`implementations/rust/`](implementations/rust/)
- WASM bindings: `wasm-pack build --target web --features wasm` → `pkg/lumen.js`

---

*LUMEN v0.1.0 — Last updated: 2026-06-14*
