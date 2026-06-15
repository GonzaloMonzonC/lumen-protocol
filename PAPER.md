# LUMEN: A Binary Wire Protocol for Efficient Model Context Communication

**Gonzalo Monzón**
LUMEN Project
`gonzalo@cadenceslab.com`

---

> **Abstract**
>
> The rapid adoption of the Model Context Protocol (MCP) as a standard
> interface between large language models (LLMs) and external tools has
> exposed the limitations of JSON-RPC 2.0 as a transport encoding for
> latency-sensitive artificial intelligence workloads. JSON-RPC imposes a
> fixed per-message overhead of 40–60 bytes of repeated structural metadata,
> lacks native support for token-level streaming, provides no built-in
> multiplexing, and defers all authentication and confidentiality to the
> transport layer. We present **LUMEN** (Lightweight Universal Model Exchange
> Network), a binary wire protocol designed as a drop-in replacement for
> JSON-RPC 2.0 in MCP deployments. LUMEN combines a self-delimiting hybrid
> length encoding (Hyb128) that enables O(1) frame skipping, a two-tier
> semantic compression scheme (a 128-entry static dictionary plus a 127-entry
> per-session dictionary), native LLM token streaming, logical-channel
> multiplexing, and an integrated zero-trust security model based on
> Macaroons with optional frame-level authenticated encryption
> (ChaCha20-Poly1305 with X25519 key agreement). Across five independent
> reference implementations (Rust, TypeScript, Python, PHP, C#), LUMEN reduces
> per-message overhead by 64–88% relative to JSON-RPC, achieves over 2 million
> messages per second in the compressed case, and delivers sub-50-microsecond
> token streaming latency. We describe the protocol design, its rationale, and
> an empirical evaluation, and we discuss the tradeoffs inherent in trading
> human readability for payload density.
>
> **Keywords:** wire protocol, binary serialization, Model Context Protocol,
> large language models, streaming, semantic compression, capability security.

---

## 1. Introduction

Large language models are increasingly deployed not as isolated text
generators but as the reasoning core of larger systems that invoke external
tools, query databases, read files, and orchestrate other agents. The Model
Context Protocol (MCP) [1] has emerged as a widely adopted standard for
describing this interaction: it defines how a host application advertises
tools, prompts, and resources to a model, and how the model invokes them. MCP
currently specifies JSON-RPC 2.0 [2] as its message encoding.

JSON-RPC was an appropriate choice for the initial standardization of MCP. It
is human-readable, trivially debuggable, and supported by every mainstream
programming language. However, as MCP deployments move from interactive
prototypes to production systems—high-frequency agent loops, real-time token
streaming to end users, and multi-tenant tool gateways—the cost of JSON-RPC's
design becomes significant.

We identify four structural limitations:

1. **Per-message overhead.** Every JSON-RPC message repeats the field names
   `jsonrpc`, `method`, `params`, and `id`. For a typical `tools/call`
   invocation, this structural metadata consumes 40–60 bytes before any
   semantic payload is transmitted. At the message rates of an autonomous
   agent loop (hundreds to thousands of calls per task), this overhead
   dominates bandwidth and parsing cost.

2. **No native streaming.** LLMs produce output incrementally, token by
   token. JSON-RPC has no notion of a partial response; implementations must
   either buffer the entire generation before responding or fragment the
   stream into a sequence of independent JSON-RPC notifications, each carrying
   full structural overhead.

3. **No multiplexing.** Running concurrent operations over a single connection
   requires out-of-band correlation logic or multiple physical connections,
   complicating both client and server implementations.

4. **No wire-level security.** Authentication and confidentiality are deferred
   entirely to the transport. This makes fine-grained, per-operation
   authorization (e.g., "this token may only call `tools/list`") awkward to
   express and impossible to enforce at the protocol layer.

This paper presents **LUMEN**, a binary wire protocol that addresses these
limitations while preserving semantic compatibility with MCP. LUMEN is not a
new application semantics; it is a more efficient *encoding* of the same
request/response, notification, and streaming interactions that MCP already
defines. A LUMEN gateway can transparently bridge to and from JSON-RPC, so the
protocol can be adopted incrementally.

We make the following contributions:

- We design **Hyb128**, a self-delimiting hybrid length encoding that allows a
  parser to determine a frame's full length from its first byte in the common
  case, enabling O(1) skipping of uninteresting frames without deserialization
  (§4.2).

- We introduce a **two-tier semantic compression** scheme that exploits the
  highly repetitive vocabulary of MCP traffic, reducing per-message overhead
  to 3–6 bytes in the common case (§4.3).

- We integrate **capability-based, zero-trust security** as a first-class
  protocol concept using Macaroons [3], with optional frame-level authenticated
  encryption (§4.7).

- We provide **five independent, interoperable reference implementations** and
  an empirical evaluation showing 64–88% overhead reduction, >2M messages/s
  throughput, and sub-50-µs streaming latency (§5, §6).

## 2. Background and Motivation

### 2.1 The Model Context Protocol

MCP defines a client–server architecture in which a *host* (e.g., a desktop
assistant or IDE) connects to one or more *servers* that expose capabilities.
The protocol distinguishes three primitives: **tools** (model-invokable
functions), **prompts** (templated interactions), and **resources** (readable
context such as files). The core message types are request/response pairs
(`tools/call`, `resources/read`), one-way notifications, and an initialization
handshake. These interactions are encoded as JSON-RPC 2.0 messages exchanged
over a transport, most commonly standard I/O for local servers or HTTP with
Server-Sent Events for remote ones.

### 2.2 The Cost of JSON-RPC for AI Workloads

Consider a minimal `tools/list` request in JSON-RPC:

```json
{"jsonrpc":"2.0","method":"tools/list","id":1}
```

This is 46 bytes, of which the structural keywords (`jsonrpc`, `2.0`,
`method`, `id`) account for roughly 30 bytes; only `tools/list` is semantic
payload. The asymmetry worsens for responses, which additionally repeat
`result` or `error` wrappers.

Three properties of modern AI workloads amplify this cost:

- **High message frequency.** Autonomous agent loops issue tool calls in tight
  cycles. A single complex task can produce thousands of round trips. Fixed
  per-message overhead therefore scales linearly with task complexity.

- **Token-level streaming.** User-facing latency is dominated by
  time-to-first-token and inter-token latency. Encoding each token as an
  independent structured message multiplies the overhead by the token count,
  which can reach thousands per response.

- **Repetitive vocabulary.** MCP traffic draws from a small, stable set of
  method names and parameter keys. The same strings (`tools/call`,
  `arguments`, `name`) recur in essentially every message—an ideal target for
  dictionary compression, which generic byte-level compressors (gzip) capture
  poorly at small message sizes due to their own framing overhead.

These observations motivate a *purpose-built* binary encoding rather than the
application of a general-purpose compressor on top of JSON.

## 3. Design Goals

LUMEN is guided by five design principles:

- **G1 — Payload density.** Minimize bytes-on-wire before semantic content. The
  target is single-digit byte overhead per message in the common case.

- **G2 — Self-describing frames.** Every frame must carry its own length so
  that a receiver can skip unknown or uninteresting frames without parsing
  their contents, supporting forward compatibility and efficient routing.

- **G3 — Transport agnosticism.** The protocol core must be independent of the
  underlying transport, operating on abstract frame bytes, so that the same
  encoding works over stdio, shared memory, UDP, or QUIC.

- **G4 — Graduated complexity.** Simple use cases must require understanding
  only a minimal subset of the protocol (request/response). Advanced features
  (streaming, multiplexing, encryption) must be optional extensions gated by
  flags rather than mandatory complexity.

- **G5 — Security by construction.** Capability-based authorization must be a
  first-class protocol concept, not a property bolted onto the transport.

## 4. The LUMEN Protocol

### 4.1 Frame Format

The unit of communication in LUMEN is the *frame*. Every frame has the
structure:

```
+-------+-------+-------+----------+------------------------+
|  LEN  | TYPE  | FLAGS | DICT_REF |   PAYLOAD (variable)   |
+-------+-------+-------+----------+------------------------+
 Hyb128  1 byte  1 byte  optional       0..N bytes
```

`LEN` is the total frame length, encoded in Hyb128 (§4.2). `TYPE` identifies
one of the frame types (request, response, notification, stream data, etc.).
`FLAGS` is a one-byte bitmask whose bits indicate whether the payload is
compressed, encrypted, high-priority, or fragmented. `DICT_REF`, present only
when the compression flag is set, names the dictionary entry used. `PAYLOAD`
carries the type-specific content. All multi-byte integers are big-endian.

This layout satisfies G2: because `LEN` is the first field and is
self-delimiting, a receiver always knows exactly how many bytes the current
frame occupies and can advance to the next frame without interpreting the
payload.

### 4.2 Hyb128 Length Encoding

A naive fixed-width length field wastes space on small messages (a 4-byte
length for a 10-byte frame) but overflows on large ones. Variable-length
encodings such as LEB128 solve the space problem but require byte-at-a-time
decoding with a continuation-bit branch per byte.

LUMEN uses **Hyb128**, a hybrid scheme that encodes the *mode* in the two most
significant bits of the first byte and selects among four fixed widths:

| MSB | Mode     | Width        | Range                |
|-----|----------|--------------|----------------------|
| 00  | Tiny     | 1 byte       | 0–63                 |
| 10  | Short    | 3 bytes      | up to 65,535         |
| 11  | Standard | 5 bytes      | up to 4,294,967,295  |
| 01  | Extended | 5 + N (LEB128) | arbitrary          |

The crucial property is that the *first byte alone* determines the total width
of the length field. A decoder reads one byte, branches once on the top two
bits, and then reads a known number of additional bytes—no per-byte
continuation testing in the common cases. Because the vast majority of MCP
control frames are smaller than 64 bytes, they fall into the single-byte Tiny
mode, making the length field essentially free. The Extended mode preserves
correctness for payloads exceeding 4 GB (e.g., large embedding tensors over
the shared-memory transport).

### 4.3 Semantic Compression

LUMEN's central efficiency mechanism is dictionary-based *semantic*
compression: rather than compressing arbitrary bytes, it substitutes a short
reference for entire protocol-level strings.

**Static dictionary (indices 0x00–0x7F).** A fixed table of 128 entries,
known to every implementation at compile time, maps the MCP vocabulary
(`tools/list`, `tools/call`, `initialize`, `notifications/initialized`, …) and
common parameter keys to single-byte references. Because this table is shared
a priori, no negotiation is required; a compressed `tools/list` request needs
only a one-byte `DICT_REF` of `0x00` instead of the ten-character string.

**Session dictionary (indices 0x80–0xFE).** A further 127 slots are
negotiated dynamically per connection via dedicated synchronization frames.
These capture application-specific vocabulary—custom tool names, recurring
argument keys, frequently repeated values—that is not known at compile time
but recurs within a session. Entries are scoped to the connection and
discarded on disconnect. Index `0xFF` is reserved as an escape indicating an
uncompressed, inline method name.

Crucially, this compression is *lossless at the semantic level*: decompressing
a frame reproduces a message semantically identical to its uncompressed form.
Only the method and field *names* are substituted; argument values are
transmitted verbatim. This targeted approach outperforms generic compressors
on the small, highly repetitive messages typical of MCP, where a byte-level
compressor's own dictionary and framing overhead would exceed the savings.

### 4.4 Native Streaming

LLM token streaming is a first-class operation. A stream begins with a
`STREAM_INIT` frame carrying a 4-byte `stream_id`, generation parameters
(maximum tokens, sampling temperature), and the model identifier. Subsequent
`STREAM_DATA` frames each carry the `stream_id`, a monotonically increasing
`token_seq`, a `token_type`, and the token bytes. The final frame in a stream
sets the high bit of `token_seq` to signal completion.

The `token_type` field distinguishes ordinary text from tool-call requests,
chain-of-thought "thinking" content, error terminations, out-of-band metadata,
and citation annotations. Because token streams are highly repetitive,
`STREAM_DATA` frames benefit substantially from dictionary compression. The
per-token overhead is a small constant (the frame header plus stream and
sequence identifiers), in contrast to the full structural overhead JSON-RPC
incurs per token.

### 4.5 Multiplexing

A single LUMEN connection can carry up to 65,535 concurrent logical channels
via the `MUX` frame, identified by a 2-byte `channel_id`. Sub-commands open,
close, carry data for, pause, and resume channels. Ordering is guaranteed
within a channel but not across channels, permitting independent operations to
make progress without head-of-line blocking at the application layer. Per-
channel flow control is provided by pause/resume sub-commands. Multiplexing is
optional (G4): implementations that do not require concurrency may treat the
connection as a single channel. When the underlying transport is QUIC, native
QUIC streams may substitute for LUMEN channels.

### 4.6 Transport Abstraction

LUMEN defines four transport levels, of which only Level 1 is mandatory:

- **Level 1 — Stream.** Ordered, reliable byte streams: stdio (the default for
  local MCP servers), Unix domain sockets, and TCP. Frames are delimited
  solely by the Hyb128 length field; no additional framing is required.

- **Level 2 — Shared memory.** Zero-copy message passing between processes on
  the same host via a shared ring buffer, intended for high-throughput,
  large-payload cases such as local inference exchanging embedding tensors.

- **Level 3 — Datagram.** Unordered, unreliable UDP, with the fragmentation
  flag handling messages that exceed the path MTU and multicast support for
  service discovery.

- **Level 4 — QUIC.** Leverages QUIC's native multiplexing and integrated TLS,
  in which case LUMEN's own multiplexing layer is optional.

Transport selection is negotiated during connection establishment, with both
peers converging on the highest mutually supported level.

### 4.7 Integrated Security

LUMEN treats authorization as a protocol concern (G5). It adopts **Macaroons**
[3], bearer tokens that can be *attenuated*—restricted by adding caveats—by any
holder without contacting the issuer. A LUMEN macaroon names a target service
and carries a chain of caveats (e.g., `method = "tools/list"`,
`expiry < T`, `rate_limit = 100/min`, `src_ip ∈ 10.0.0.0/8`), bound together
by an HMAC signature chain so that caveats cannot be removed undetected. A
server must verify every caveat before executing a request and reject
unauthorized calls at the protocol layer. This enables, for example, a gateway
to hand a downstream agent a token usable only for read-only discovery, with no
coordination with the issuing authority.

For confidentiality, LUMEN optionally encrypts frame payloads with
ChaCha20-Poly1305 [4]. Session keys are established during the connection
handshake using X25519 [5] Diffie–Hellman; distinct send and receive keys are
derived with HKDF-SHA256 [6]. The 12-byte AEAD nonce additionally serves as an
anti-replay mechanism, complemented at the application layer by single-use
request identifiers. We note (§7.2) that the bare X25519 exchange is
unauthenticated and must be combined with macaroon-based mutual authentication
or a trusted transport to resist active adversaries.

## 5. Implementation

We have implemented LUMEN in five languages to validate the design's
portability and to enable cross-ecosystem deployment:

| Language   | Transports     | Status                         |
|------------|----------------|--------------------------------|
| Rust       | L1, L2, L3     | Production; used in MCP server |
| TypeScript | L1, L4         | Production; npm package        |
| Python     | L1             | Beta; reference implementation |
| PHP        | L1             | Alpha; Swoole extension        |
| C#         | L1             | Alpha; NuGet package           |

All implementations share a common set of test vectors for frame
encoding/decoding, ensuring byte-level interoperability. Every implementation
supports at minimum Level 1 and the core frame types (request, response,
notification, heartbeat); advanced features are added per the target
deployment. Interoperability has been validated pairwise among the Rust,
TypeScript, and Python implementations.

## 6. Evaluation

### 6.1 Methodology

We evaluate LUMEN along four axes: per-message overhead, throughput, streaming
latency, and compression ratio. Unless otherwise noted, throughput and latency
figures are from the Rust implementation over a Level 1 stdio transport with a
1 KB payload, measured on an AMD Ryzen 9 5950X with DDR4-3600 memory running
Linux 6.1. Overhead figures compare encoded message sizes directly against the
equivalent JSON-RPC 2.0 messages.

### 6.2 Per-Message Overhead

For a `tools/list` request, the JSON-RPC encoding is approximately 55 bytes.
The uncompressed LUMEN encoding is 20 bytes (a 64% reduction); with static
dictionary compression it is 10 bytes (an 82% reduction). Across the range of
common MCP control messages we observe overhead reductions of **64–88%**, with
the largest gains on the smallest, most frequent messages—precisely those that
dominate agent-loop traffic.

| Message            | JSON-RPC | LUMEN (raw) | LUMEN (compressed) |
|--------------------|---------:|------------:|-------------------:|
| `tools/list` req   |  ~55 B   |    20 B     |        10 B        |
| Reduction          |    —     |    64%      |        82%         |

### 6.3 Throughput

The Rust implementation sustains over **500,000 messages/second** for
uncompressed request/response traffic and exceeds **2,000,000 messages/second**
when static-dictionary compression is enabled. The compressed case is faster
despite the compression step because the dominant cost at these message sizes
is per-byte I/O and parsing, which the smaller frames reduce.

### 6.4 Latency

Round-trip request/response latency is under **10 microseconds**. Encoding a
compressed request takes under **100 nanoseconds**; encrypting a request adds
under **2 microseconds**. Per-token streaming latency—the time from a token
being produced to it being framed and ready for transmission—is under
**50 microseconds**, well below the inter-token interval of any current LLM and
therefore not a bottleneck for user-facing streaming.

### 6.5 Compression Ratio

Because the static dictionary captures the MCP vocabulary exactly, the most
frequent control messages compress to a near-minimal representation (a frame
header plus a one-byte dictionary reference). The session dictionary extends
this benefit to application-specific vocabulary, with the marginal cost of a
one-time synchronization per entry amortized over its subsequent uses.

### 6.6 Cross-Language Interoperability

Shared test vectors confirm that frames produced by any implementation are
decoded identically by the others. This byte-level agreement is a prerequisite
for heterogeneous deployments in which, for example, a Rust server streams to a
TypeScript client.

## 7. Discussion

### 7.1 Design Tradeoffs

LUMEN deliberately trades human readability for payload density (G1). A LUMEN
frame is not inspectable with a text editor as a JSON-RPC message is. We
consider this acceptable because (a) the protocol is intended for
production data paths rather than ad-hoc debugging, (b) a bidirectional
JSON-RPC bridge preserves interoperability and debuggability at system
boundaries, and (c) the self-describing frame format (G2) supports tooling
that decodes frames on demand.

The two-tier dictionary reflects a tension between zero-configuration operation
and adaptivity. The static tier requires no negotiation and immediately
benefits the common case; the session tier adapts to application vocabulary at
the cost of a synchronization handshake. Splitting the index space (0x00–0x7F
static, 0x80–0xFE session) lets a single one-byte reference address either tier
without an additional discriminator.

### 7.2 Limitations

LUMEN's native encryption authenticates and conceals payloads but leaves frame
metadata—type, flags, and length—in cleartext. An on-path observer can
therefore infer message types and sizes. Deployments requiring metadata privacy
should run LUMEN within a transport-level tunnel (TLS or QUIC). Furthermore, the
X25519 key agreement is, by itself, unauthenticated and thus vulnerable to an
active man-in-the-middle; it must be paired with macaroon-based mutual
authentication or a trusted transport. Finally, several protocol features
(unbounded Hyb128 lengths, fragment reassembly, channel and stream creation)
present denial-of-service surfaces that implementations must bound with
negotiated limits, as enumerated in the protocol's security considerations.

## 8. Related Work

**General-purpose binary serialization.** Protocol Buffers [7], FlatBuffers,
Cap'n Proto, and CBOR [8] provide compact binary encodings of structured data.
These solve the data-representation problem but not the *protocol*-level
concerns LUMEN targets: none provides MCP-aware semantic compression, native
LLM token streaming, capability security, or self-delimiting frames tuned for
O(1) skipping. LUMEN in fact uses CBOR for the representation of opaque
argument values while supplying its own framing, compression, streaming,
multiplexing, and security layers.

**RPC frameworks.** gRPC layers Protocol Buffers over HTTP/2, inheriting
HTTP/2 multiplexing and flow control. Its overhead and dependency surface,
however, are substantial for the local stdio transports that dominate MCP, and
it offers no domain-specific compression of method vocabulary.

**Transport protocols.** QUIC [9] provides multiplexing, flow control, and
integrated TLS at the transport layer. LUMEN is complementary: it can run over
QUIC (Level 4), in which case it delegates multiplexing and encryption to the
transport while retaining its compression and capability-security semantics.

**Capability security.** Macaroons [3] introduced attenuable, contextual bearer
credentials. LUMEN elevates them from an application-level construct to a
first-class protocol element, enabling enforcement at the message layer.

## 9. Conclusion and Future Work

We presented LUMEN, a binary wire protocol that re-encodes the Model Context
Protocol's interactions for production AI workloads. By pairing a self-
delimiting hybrid length encoding with MCP-aware semantic compression, native
token streaming, logical multiplexing, and integrated capability security,
LUMEN reduces per-message overhead by 64–88%, sustains millions of messages per
second, and streams tokens with microsecond-scale latency, while remaining
interoperable with JSON-RPC through a transparent bridge.

Future work includes authenticating the key-agreement handshake to remove the
trusted-transport assumption, formalizing the session-dictionary negotiation
for adversarial settings, extending the evaluation to wide-area and multi-tenant
gateway deployments, and standardizing the protocol through the published RFC.

## Acknowledgments

The author thanks the MCP community for feedback on early protocol drafts, and
the authors of the Macaroons, CBOR, QUIC, and ChaCha20-Poly1305 specifications
and reference implementations, on which this work builds.

## References

[1] Anthropic, "Model Context Protocol Specification."
    https://modelcontextprotocol.io/specification

[2] JSON-RPC Working Group, "JSON-RPC 2.0 Specification."
    https://www.jsonrpc.org/specification

[3] A. Birgisson, J. G. Politz, Ú. Erlingsson, A. Taly, M. Vrable, and
    M. Lentczner, "Macaroons: Cookies with Contextual Caveats for
    Decentralized Authorization in the Cloud," in *Proc. NDSS*, 2014.

[4] Y. Nir and A. Langley, "ChaCha20 and Poly1305 for IETF Protocols,"
    RFC 8439, 2018.

[5] A. Langley, M. Hamburg, and S. Turner, "Elliptic Curves for Security,"
    RFC 7748, 2016.

[6] H. Krawczyk and P. Eronen, "HMAC-based Extract-and-Expand Key Derivation
    Function (HKDF)," RFC 5869, 2010.

[7] Google, "Protocol Buffers." https://protobuf.dev

[8] C. Bormann and P. Hoffman, "Concise Binary Object Representation (CBOR),"
    STD 94, RFC 8949, 2020.

[9] J. Iyengar and M. Thomson, Eds., "QUIC: A UDP-Based Multiplexed and Secure
    Transport," RFC 9000, 2021.

---

*This paper accompanies the LUMEN protocol specification (`RFC_LUMEN.md`) and
developer reference (`SPEC_DEV.md`). Reference implementations are available at
https://github.com/GonzaloMonzonC/lumen-protocol.*
