<p align="center">
  <br>
  <h1 align="center">◆ LUMEN</h1>
  <p align="center"><strong>Lightweight Universal Model Exchange Network</strong></p>
  <p align="center">
    A binary protocol for MCP that makes JSON-RPC feel like dial-up.
    <br>
    <em>Wire savings: 40–80%. Latency: sub-ms. Overhead: 3–6 bytes.</em>
  </p>
  <br>
</p>

<p align="center">
  <strong>English</strong> &nbsp;|&nbsp; <a href="README_ES.md">Español</a>
</p>

<p align="center">
  <a href="INSTALL.md"><strong>🚀 Install in Hermes Agent</strong></a> &nbsp;|&nbsp;
  <a href="https://github.com/NousResearch/hermes-agent/pull/47740">PR #47740</a> &nbsp;|&nbsp;
  <strong>✅ 33 tools — works with Hermes</strong>
</p>

---

## Why?

JSON-RPC over stdio is the MCP standard. It works. But at scale, it hurts:

| Pain | LUMEN answer |
|------|-------------|
| **Verbose wire** — `{"jsonrpc":"2.0","id":7,...}` on every message | **Static dictionary** (128 keys) + **session dictionary** (127 keys). Repeated keys → 1 byte. |
| **Costly parsing** — every JSON blob must be fully decoded | **Self-delimiting frames** (Hyb128). Skip entire frames in O(1). |
| **No streaming** — JSON is a single, complete document | **Native streaming** (`STREAM_DATA` + `STREAM_INIT` frames). Tokens arrive token-by-token. |
| **No security model** — all-or-nothing access to the server | **Zero-trust Macaroons** with attenuable caveats. Wire encryption with ChaCha20-Poly1305. |

---

## Quick Start

```bash
# 📦 Published packages (no clone needed)
pip install lumen-mcp           # Python
npm install @gonzalomonzonc/mcp-transport  # TypeScript

# Or build from source:
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

# Python
cd implementations/python && pip install -e . && cd ../..

# TypeScript
cd implementations/typescript && npm install && npm run build && cd ../..

# Rust
cd implementations/rust && cargo test && cargo bench && cd ../..
```

---

## Protocol in one diagram

```
┌──────────────────────────────────────────────────────┐
│ [Hyb128 LEN:1-5B]  [TYPE:1B]  [FLAGS:1B]  [PAYLOAD] │
└──────────────────────────────────────────────────────┘
  0-63B   → 1 byte        REQUEST   COMPRESSED
  64KB    → 3 bytes       RESPONSE  ENCRYPTED
  4GB     → 5 bytes       NOTIFY    STREAM
  >4GB    → LEB128        STREAM_DATA …

  Overhead: 3 bytes (small payload) to 7 bytes (4 GB)
```

**Compression in action:**
```json
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"search","arguments":{"pattern":"TODO"}}}
```
→ LUMEN: `type=REQUEST, tool, method, name, pattern` are dict IDs (1 byte each), only `"search"` and `"TODO"` go as raw strings.

---

## Key metrics

| Benchmark | JSON-RPC | LUMEN | Reduction |
|-----------|----------|-------|-----------|
| Small RPC (heartbeat) | 50 B | 21 B | **58%** |
| Tool list (100 tools) | 39.7 KB | 24.8 KB | **37%** |
| LLM token stream (10K) | 1009 KB | 543 KB | **46%** |
| Agent loop (30 turns) | 6.4 KB | 3.3 KB | **48%** |
| tools/list (4 tools) | 1128 B | 581 B | **48%** |
| tool call (echo) | 118 B | 61 B | **48%** |

> Run it yourself: `python examples/cost-calculator/cost_calculator.py`

---

## Implementations

| Language | Path | Status |
|----------|------|--------|
| **Rust** | `implementations/rust/` | Reference impl, WASM target, FFI (C ABI) |
| **TypeScript** | `npm i @gonzalomonzonc/mcp-transport` | Node.js + browser, zero-copy SHM via koffi |
| **Python** | `pip install lumen-mcp` | Full protocol, session dict, MCP tools |
| **PHP** | `implementations/php/` | PHP 8.5+, 217/217 e2e passing |
| **C#** | `implementations/dotnet/` | .NET 9, P/Invoke FFI to Rust |
| **WASM** | `implementations/rust/wasm/` | Browser-ready, 22 KB gzipped |

---

## MCP Servers

Production-ready MCP servers built with LUMEN. Ready to use with Hermes Agent.

| Server | Tools | Wire Savings | Hermes Config |
|--------|-------|-------------|---------------|
| **[Filesystem](implementations/mcp-servers/filesystem/)** | 9 (read, write, search, stream, stats...) | 32-70% | `transport: lumen` |
| **[Web](implementations/mcp-servers/web/)** | 2 (search + extract unified) | 40-50% | `transport: lumen` |
| **[Thinking](implementations/mcp-servers/thinking/)** | 22 (sequential, similarity, contradiction, assumptions, model, work...) | 60-80% | `transport: lumen` |

> **33 tools, 3 servers, 0 API keys required.**

---

## Transport levels

```
Level 1 — stdio/UDS       (local, zero-copy SHM)
Level 2 — TCP             (LAN, Hyb128 framing)
Level 3 — UDP + Multicast (service discovery, fire-and-forget)
Level 4 — QUIC            (WAN, HTTP/3, production)
```

---

## Hermes Agent Integration

LUMEN is integrated into Hermes Agent via [PR #47740](https://github.com/NousResearch/hermes-agent/pull/47740).

```yaml
# ~/.hermes/config.yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args: ["implementations/mcp-servers/filesystem/server.py"]
    transport: lumen
```

See [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) for full guide.

---

## Status & Roadmap

### ✅ Built & Working

| Feature | Status | Details |
|---------|--------|---------|
| Hyb128 framing | ✅ | 1/3/5B modes, O(1) skip, consistent across Rust/Python/TS |
| Static dictionary | ✅ | 128 keys, matches LUMEN spec |
| Session dictionary (LRU) | ✅ | Rust: per-transport. TS/Python: global singleton (per-session coming) |
| Binary compression | ✅ | TAG_NULL/FLOAT/INT/STR_DICT/STR_RAW/ARRAY/OBJECT |
| MCP servers | ✅ | 33 tools across filesystem (9), web (2), thinking (22) |
| Probe/ACK negotiation | ✅ | Graceful JSON-RPC fallback |
| ChaCha20-Poly1305 encryption | ✅ | Rust + TypeScript; HKDF-SHA256 key derivation |
| X25519 key exchange | ✅ | Rust + TypeScript |
| Native token streaming | ✅ | Rust: stream.rs — StreamInit, StreamData, StreamRegistry |
| MUX channels | ✅ | Rust: mux.rs — 5 sub-commands, MuxRegistry with state machine |
| Macaroons (capability auth) | ✅ | Rust: macaroon.rs — HMAC-SHA256 chained sigs, caveat attenuation |
| QUIC transport (L4) | ✅ | Rust: `quic.rs` — server/client endpoints, TLS 1.3, bidirectional streams, 7 tests |
| Python 3.10+ impl | ✅ | Full protocol, MCP servers, e2e suite (89/89) |
| TypeScript impl | ✅ | Node.js + browser, zero-copy SHM via koffi |
| PHP 8.5+ impl | ✅ | 217/217 e2e passing |
| C#/.NET 9 impl | ✅ | P/Invoke FFI to Rust |
| WASM target | ✅ | 22 KB gzipped, browser-ready |

### 🚧 Planned / Under Development

| Feature | Status | Notes |
|---------|--------|-------|
| Multi-agent sessions | 🚧 Rust partial | Per-transport dict; full session isolation WIP |

### 📐 Known Spec/Code Mismatches — RESOLVED

All mismatches identified in the initial audit have been resolved.
The [RFC_LUMEN.md](RFC_LUMEN.md) now matches the implementation exactly:

| Original mismatch | Resolution |
|-------------------|------------|
| Big-endian → Little-endian | RFC §2 corrected (LE is canonical). Code was always correct. |
| Frame `DICT_REF` field | Removed from RFC §3.1. Dict lookups are handled by Hyb128 STR_DICT tag. |
| Hyb128 Extended diagram | RFC Appendix A rewritten with accurate LE frames + mode-byte tables. |
| §5 "binary headers" | §5.1-5.6 rewritten to describe actual JSON-RPC opaque blobs with v2 notes. |
| CBOR references | Replaced with "LUMEN binary format (TAGs 0xE0-0xE7)" throughout. |
| Static dictionary table | Updated to match DICTIONARY.md (128 field keys, not method names). |

---

## Docs

| Doc | Content |
|-----|---------|
| **[README_EXT.md](README_EXT.md)** | Protocol spec, all benchmarks, architecture deep-dive (EN) |
| **[README_EXT_ES.md](README_EXT_ES.md)** | Same, in Spanish |
| **[RFC_LUMEN.md](RFC_LUMEN.md)** | Formal IETF-style protocol RFC |
| **[SPEC_DEV.md](SPEC_DEV.md)** | Developer reference specification |
| **[HERMES_INTEGRATION.md](HERMES_INTEGRATION.md)** | Hermes Agent setup guide |
| **[examples/](examples/)** | Runnable demos with bilingual READMEs |
| **[implementations/mcp-servers/](implementations/mcp-servers/)** | MCP server implementations |

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  <sub>LUMEN · <em>Your MCP wire. Just smaller. Faster. Safer.</em></sub>
</p>
