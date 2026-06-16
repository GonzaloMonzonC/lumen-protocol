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

---

## ¿Por qué? / Why?

JSON-RPC over stdio is the MCP standard. It works. But at scale, it hurts:

| Pain | LUMEN answer |
|
[![Hermes Integration](HERMES_INTEGRATION.md)](HERMES_INTEGRATION.md)
------|-------------|
| **Verbose wire** — `{"jsonrpc":"2.0","id":7,...}` on every message | **Static dictionary** (128 keys) + **session dictionary** (127 keys). Repeated keys → 1 byte. |
| **Costly parsing** — every JSON blob must be fully decoded | **Self-delimiting frames** (Hyb128). Skip entire frames in O(1). |
| **No streaming** — JSON is a single, complete document | **Native streaming** (`STREAM_DATA` + `STREAM_INIT` frames). Tokens arrive token-by-token. |
| **No security model** — all-or-nothing access to the server | **Zero-trust Macaroons** with attenuable caveats. Wire encryption with ChaCha20-Poly1305. |

---

## Quick Start

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

# Python
cd implementations/python && pip install -e . && cd ../..
python examples/cost-calculator/cost_calculator.py

# TypeScript
cd implementations/typescript && npm install && npm run build && cd ../..
node --test implementations/typescript/dist/*.test.js

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

> Run it yourself: `python examples/cost-calculator/cost_calculator.py`

---

## Implementations

| Language | Path | Status |
|----------|------|--------|
| **Rust** | `implementations/rust/` | Reference impl, WASM target, FFI (C ABI) |
| **TypeScript** | `implementations/typescript/` | Node.js + browser, zero-copy SHM via koffi |
| **Python** | `implementations/python/` | Full protocol, session dict, MCP tools |
| **PHP** | `implementations/php/` | PHP 8.5+, 217/217 e2e passing |
| **C#** | `implementations/dotnet/` | .NET 9, P/Invoke FFI to Rust |
| **WASM** | `implementations/rust/wasm/` | Browser-ready, 22 KB gzipped |

---

## Transport levels

```
Level 1 — stdio/UDS       (local, zero-copy SHM)
Level 2 — TCP             (LAN, Hyb128 framing)
Level 3 — UDP + Multicast (service discovery, fire-and-forget)
Level 4 — QUIC            (WAN, HTTP/3, production)
```

---

## ◆ Demos (run in <2 min each)

| Demo | Command | What it shows |
|------|---------|---------------|
| **Cost Calculator** | `python examples/cost-calculator/cost_calculator.py` | Cloud egress cost projection for 1,000 servers |
| **Agent Loop** | `python examples/agent-loop/agent_loop.py` | Session dictionary learns your traffic in real time |
| **MCP Drop-In** | `python examples/mcp-dropin/dropin_server.py` | Real HTTP server: JSON-RPC in, LUMEN binary out |

---

## Documentación / Docs

| Doc | Content |
|-----|---------|
| **[README_EXT.md](README_EXT.md)** | Protocol spec, all benchmarks, architecture deep-dive (EN) |
| **[README_EXT_ES.md](README_EXT_ES.md)** | Lo mismo, en español |
| **[RFC_LUMEN.md](RFC_LUMEN.md)** | Formal IETF-style protocol RFC |
| **[SPEC_DEV.md](SPEC_DEV.md)** | Developer reference specification |
| **[examples/](examples/)** | Runnable demos with bilingual READMEs |

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  <sub>LUMEN · <em>Your MCP wire. Just smaller. Faster. Safer.</em></sub>
</p>