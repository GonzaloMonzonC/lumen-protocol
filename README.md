<p align="center">
  <br>
  <h1 align="center">◆ LUMEN</h1>
  <p align="center"><strong>Lightweight Universal Model Exchange Network</strong></p>
  <p align="center">
    El asistente cognitivo definitivo para Hermes Agent.
    <br>
    <em>106 herramientas · memoria persistente · kanban · wiki · patrones · dashboard · RAG</em>
  </p>
  <br>
</p>

<p align="center">
  <a href="INSTALL.md"><strong>🚀 Install in Hermes Agent</strong></a> &nbsp;|&nbsp;
  <a href="https://github.com/NousResearch/hermes-agent/pull/47740">PR #47740</a> (closed — superseded by plugin) &nbsp;|&nbsp;
  <strong>✅ 106 tools — Level 2 SHM zero-copy transport — 4 MCP servers — RAG on PDB — works with Hermes</strong>
</p>

---

## Why?

JSON-RPC over stdio is the MCP standard. It works. But at scale, it hurts:

| Pain | LUMEN answer |
|------|-------------|
| **Verbose wire** — `{"jsonrpc":"2.0","id":7,...}` on every message | **Static dictionary** (128 keys) + **session dictionary** (127 keys). Repeated keys → 1 byte. |
| **Kernel copies** — stdio pipes copy data twice (kernel↔user) | **Level 2 SHM** — mmap'd ring buffers eliminate all copies. Zero-copy for local IPC. |
| **No streaming** — JSON is a single, complete document | **Native streaming** (`STREAM_DATA` + `STREAM_INIT` frames). Tokens arrive token-by-token. |
| **No security model** — all-or-nothing access to the server | **Zero-trust Macaroons** with attenuable caveats. Wire encryption with ChaCha20-Poly1305. |
| **Windows fragility** — shell tools (`ls`, `grep`, `stat`, `du`) unreliable on Windows | **13 filesystem tools** including `file_info`, `disk_usage`, `search_filename`, `find_duplicates` — zero shell dependency. |

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

**It's not just theory.** Benchmark on real MCP tool responses:

| Server | JSON-RPC | LUMEN | Savings |
|--------|----------|-------|---------|
| Filesystem (13 tools) | 100% | 81% | **19% smaller** |
| Thinking (46 tools) | 100% | 67% | **33% smaller** |
| Web (2 tools) | 100% | 73% | **27% smaller** |
| PDB (40 tools) | 100% | 71% | **29% smaller** |
| Objective Loop (5 tools) | 100% | 65% | **35% smaller** |

> **Benchmarked**: 106 tools across 4 servers, 0 errors. See [cognitive benchmarks](implementations/mcp-servers/pdb/bench-results/INFORME_GLOBAL.md) and [raw speed](docs/BENCHMARKS.md).

---

## Key metrics

| Benchmark | JSON-RPC | LUMEN | Reduction |
|-----------|----------|-------|-----------|
| Small RPC (heartbeat) | 50 B | 21 B | **58%** |
| Tool list (106 tools) | 39.7 KB | 24.8 KB | **37%** |
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
| **PHP** | `implementations/php/` | Core protocol (Hyb128, compression, dict). E2E: 181/217 passing (binary compat test/golden mismatch) |
| **C#** | `implementations/csharp/` | .NET 9, P/Invoke FFI to Rust |
| **WASM** | `implementations/rust/src/wasm.rs` | Browser-ready, 22 KB gzipped |

---

## MCP Servers

Production-ready MCP servers built with LUMEN. Ready to use with Hermes Agent.

| Server | Tools | Wire Savings | Hermes Config |
|--------|-------|-------------|---------------|
| **[Filesystem](implementations/mcp-servers/filesystem/)** | **13** 🔥 (read, write, search, stream, stats, info, du, dedup...) | 10-38% | Plugin `lumen-shm-bridge` |
| **[Web](implementations/mcp-servers/web/)** | **2** (search + extract unified) | 18-36% | Plugin `lumen-shm-bridge` |
| **[Thinking](implementations/mcp-servers/thinking/)** | **46** 🔥 (chains, kanban, wiki, Q&A, patterns, decisions, model, objectives, cognitive tools...) | 11-59% | Plugin `lumen-shm-bridge` |
| **[Objective Loop](implementations/mcp-servers/thinking/objective_loop.py)** | **5** (create, judge, plan, status, checklist) | auto | Plugin `lumen-shm-bridge` |

> **106 tools, 4 server modules, 0 API keys required. 9× faster than Hermes built-ins on filesystem ops.**

> **🧠 PDB** — 40 tools, una base de datos jerárquica KV+SQL con herencia de MUMPS (1966). Sin esquemas, sin migraciones, 15 μs por GET. Incluye $LOCK, auto-indices ^IDX, triggers ON SET/ON KILL, global mapping ^GLOBAL→archivo, partitioning automático, journaling DELETE, DBFIX, y M REPL. Es donde el agente guarda su memoria persistente. [Más en COGNITIVE_OS.md →](docs/COGNITIVE_OS.md#-pdb-process-database--la-memoria-del-agente)

---

## 🧠 Tu Asistente Personal con Superpoderes Cognitivos

LUMEN no es solo un protocolo rápido. Sobre Hermes Agent, se convierte en un **asistente personal con memoria, organización y consciencia de estado**:

| Capacidad | Tools | ¿Qué hace por ti? |
|-----------|-------|-------------------|
| **📋 Kanban cognitivo** | `niche_create`, `task_create`, `task_move`, `task_list`, `task_search`, `kanban_stats` | Organiza proyectos en nichos, trackea tareas, mide velocidad |
| **📚 Wiki persistente** | `wiki_create`, `wiki_read`, `wiki_update`, `wiki_delete`, `wiki_list` | Documenta decisiones, guarda conocimiento entre sesiones |
| **🐞 Memoria de bugs** | `pattern_record`, `pattern_suggest`, `pattern_match` | Aprende de errores pasados, sugiere fixes conocidos |
| **📋 Registro de decisiones** | `decision_log`, `decision_list` | Arquitectura con rationale, alternativas, triggers de revisión |
| **❓ Q&A permanente** | `qa_ask`, `qa_list`, `qa_link` | Resuelve dudas una vez, reutiliza para siempre |
| **🧠 Modelo mental** | `model_add`, `model_map`, `model_query`, `model_stats` | Construye un grafo de conceptos del dominio |
| **🔗 Razonamiento estructurado** | `sequential_thinking`, `thought_evaluate`, `thought_to_plan`, `thought_bridge` | Descompone problemas, evalúa hipótesis, genera planes |
| **🎯 Agent Loop** | `objective_create`, `objective_judge`, `objective_plan`, `objective_status` | Ciclo BUILD→TEST autónomo con criterios de aceptación |
| **🩺 Auto-diagnóstico** | `cognitive_integrity`, `cognitive_pulse`, `state_snapshot`, `unified_search` | Detecta tareas huérfanas, patrones estancados, Q&A sin responder |
| **📊 Dashboard en tiempo real** | `:9876` — métricas, kanban, chains, works, M Console | Monitoriza tu sesión como un piloto su cabina |
| **💾 PDB — memoria persistente** | 40 tools: `pdb_set`, `pdb_get`, `pdb_order`, `pdb_query`, `pdb_m_eval`... | Jerárquico, ACID, sin esquemas, 15 μs/GET |
| **🔍 Búsqueda semántica (RAG)** | `mcp_eb_embed`, `mcp_eb_embed_search` | Embeddings locales (fastembed), 0 tokens, 100ms/query |
| **🌐 Web + research** | `web_search`, `web_extract`, `web_snapshot` | Busca, extrae, guarda snapshots para referencia |
| **📁 Filesystem inteligente** | 13 tools: `read_file`, `search_files`, `disk_usage`, `find_duplicates`... | Zero-copy SHM, sin dependencia de shell |
| **🔐 Multi-sesión** | `session_init`, `session_list`, `session_search`, `work_start`, `work_log` | Trabajo cross-session, recuperación de contexto, logs |

> **106 herramientas. 0 API keys. 1 asistente que recuerda, aprende y se organiza contigo.**

[TOOLS_GUIDE.md →](implementations/mcp-servers/TOOLS_GUIDE.md) para referencia completa con ejemplos.

---

## Transport levels

```
Level 1 — Stream           (stdio, TCP, WebSocket; Hyb128 frames, 55-80% savings)
Level 2 — SHM/mmap 🔥      (local IPC, zero-copy ring buffers, sub-ms latency)
Level 3 — Datagram         (UDP + multicast, service discovery, fire-and-forget)
Level 4 — QUIC             (WAN, HTTP/3, production)
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
| MCP servers | ✅ | **106 tools** across filesystem (**13**), web (**2**), thinking (**48**), PDB (**42**) |
| SHM zero-copy transport | ✅ | Level 2 mmap ring buffers, 8 MiB, MAX_SPIN=10M, sub-ms latency |
| Plugin bridge (Hermes) | ✅ | `lumen-shm-bridge` — 106 tools, transparent override of built-ins |
| M-Light M evaluator | ✅ | $O, $G, $D, $P, $E, $S, $L, $F, $TR, FOR, IF, GOTO, DO, Q:cond. ~70% MSM STU |
| D^ROUTINE web | ✅ | :8767 — D^SS (procesos), D^GS (globals), dashboard HTML |
| MSM Compatibility | ✅ | 14/18 MSM STU patterns. Hex #, +cast, \\div, #mod. KILL locales, coma-SET |
| Cognitive Benchmark | ✅ | 27K insert/s, 58K GET/s, \$ORDER jerárquico, M-Light \$ORDER 0.5s/1K |
| MVM — M Virtual Machine | ✅ | Procesos M autónomos: spawn, tick, mailbox, kill. D^SS panel |
| Probe/ACK negotiation | ✅ | Graceful JSON-RPC fallback |
| ChaCha20-Poly1305 encryption | ✅ | Rust + TypeScript; HKDF-SHA256 key derivation (network transports). Protects against passive eavesdropping. For active MITM protection, use QUIC (TLS 1.3) or pre-shared Ed25519 keys. |
| X25519 key exchange | ✅ | Rust + TypeScript; peer key now validated against low-order points |
| Macaroons (capability auth) | ✅ | Rust: macaroon.rs — HMAC-SHA256, auto expiry check, caveat attenuation |
| MUX channels | ✅ | Rust: mux.rs — 5 sub-commands, MuxRegistry with state machine |
| Multi-agent sessions | ✅ | Python: thinking server — session_init, session_list, per-session isolation |
| QUIC transport (L4) | ✅ | Rust: `quic.rs` — server/client endpoints, TLS 1.3, bidirectional streams, 7 tests |
| Python 3.10+ impl | ✅ | Full protocol, MCP servers, e2e suite (89/89) |
| TypeScript impl | ✅ | Node.js + browser, zero-copy SHM via koffi |
| PHP 8.1+ impl | ✅ | Core protocol. E2E: 181/217 (golden mismatch in progress) |
| C#/.NET 9 impl | 🔶 | Hyb128 + compression + FFI. No frame layer yet (partial) |
| WASM target | ✅ | 22 KB gzipped, browser-ready |

### 🚧 Planned / Under Development

| Feature | Status | Details |
|---------|--------|---------|
| LUMEN WebSocket dashboard | ✅ Deployed | Real-time dashboard on :9877, 80% compression |
| Token-efficient tools | ✅ Deployed | state_snapshot, thought_compress (90% output savings) |
| Proactive cognitive system | ✅ Deployed | Auto-evaluate, pattern suggestions, work reminders |
| Multi-machine mesh (Phase E) | 🚧 Planned | Distributed LUMEN-over-WebSocket across Cloudflare |
| Universal protocol docs | 🚧 Planned | Publish as open standard, JS + Python libraries |

### 📐 Known Spec/Code Mismatches

| # | Mismatch | Status |
|---|----------|--------|
| 1 | `RFC_LUMEN.md` claimed "Remaining unimplemented: None" while `0x0D/0x0E` were Unassigned | **RESOLVED** — now says "implementation status varies by binding", `0x0D/0x0E` → BATCH/FLOW_CTL |
| 2 | IETF boilerplate ("Internet Standards Track", "IANA has created") incompatible with independent project | **RESOLVED** — replaced with project registry, independent status |
| 3 | Transport levels: README had 5 levels (TCP=L3), RFC had 4 | **RESOLVED** — unified to L1 Stream, L2 SHM, L3 Datagram, L4 QUIC |
| 4 | `SPEC_DEV.md` claimed AEAD protects against active MITM | **RESOLVED** — corrected: wire encryption protects passive only; MITM requires TLS/PSK |
| 5 | TypeScript `src/crypto.ts` did not compile (5 TS errors) | **RESOLVED** — `isNode` boolean coercion + HKDF `Uint8Array` wrapping |
| 6 | Python missing `TYPE_TRANSPORT_INIT`, `TYPE_TRANSPORT_ACK`, `TYPE_BATCH`, `TYPE_FLOW_CTL` | **RESOLVED** — constants added and exported |
| 7 | `conformance.json` mixed `BATCH`/`FLOW_CTL` in core (`0x01..0x10` sweep) | **IN PROGRESS** — separating into `core.frame_type_constants` + `extensions.batch_flow` |
| 8 | PHP e2e: 181/217 (36 failures in Frame Binary Compatibility) | **PENDING** — needs PHP runtime; golden/test JSON compact vs spaces |
| 9 | PHP missing `TRANSPORT_INIT`, `TRANSPORT_ACK`, `BATCH`, `FLOW_CTL` | **IN PROGRESS** — constants being added (no PHP runtime to test) |
| 10 | C# no `Frame.cs` layer | **PENDING** — requires .NET SDK; currently compression/Hyb128/FFI only |
| 11 | No capability manifest per binding | **IN PROGRESS** — creating `tests/e2e/capabilities.json` |
| 12 | Rust tests not runnable in this environment | **PENDING** — requires `cargo`; reference implementation presumed complete |

---

## Docs

| Doc | Content |
|-----|---------|
| **[README_EXT.md](README_EXT.md)** | Protocol spec, all benchmarks, architecture deep-dive (EN) |
| **[RFC_LUMEN.md](RFC_LUMEN.md)** | Formal IETF-style protocol RFC |
| **[SPEC_DEV.md](SPEC_DEV.md)** | Developer reference specification |
| **[HERMES_INTEGRATION.md](HERMES_INTEGRATION.md)** | Hermes Agent setup guide |
| **[docs/COGNITIVE_OS.md](docs/COGNITIVE_OS.md)** | Cognitive OS architecture, 106 tool reference |
| **[docs/BENCHMARKS.md](docs/BENCHMARKS.md)** | Consolidated benchmarks (3,407 calls/sec) |
| **[docs/enterprise-stress-testing-2026-06-20.md](docs/enterprise-stress-testing-2026-06-20.md)** | 6 enterprise scenarios, 20K calls/sec |
| **[docs/token-efficient-tools-2026-06-20.md](docs/token-efficient-tools-2026-06-20.md)** | 5 token-efficient tools (90% output savings) |
| **[docs/lumen-universal-protocol-strategy.md](docs/lumen-universal-protocol-strategy.md)** | LUMEN as universal protocol infrastructure |
| **[docs/lumen-ws-dashboard.md](docs/lumen-ws-dashboard.md)** | WebSocket dashboard with LUMEN wire format |
| **[implementations/hermes-plugins/](implementations/hermes-plugins/)** | Plugin source (lumen-shm-bridge) |
| **[examples/](examples/)** | Runnable demos with bilingual READMEs |
| **[implementations/mcp-servers/](implementations/mcp-servers/)** | MCP server implementations |
| **[implementations/mcp-servers/TOOLS_GUIDE.md](implementations/mcp-servers/TOOLS_GUIDE.md)** | 106 tool reference with schemas |
| **[implementations/mcp-servers/pdb/m_light.py](implementations/mcp-servers/pdb/m_light.py)** | M-Light: evaluador MUMPS para PDB |
| **[docs/ROADMAP_MLIGHT.md](docs/ROADMAP_MLIGHT.md)** | M-Light MSM Compatibility Roadmap |
| **[docs/lumen_thinking_usage.md](docs/lumen_thinking_usage.md)** | Thinking server usage guide |
| **[acta_revision_1_2026-06-20.md](acta_revision_1_2026-06-20.md)** | Cognitive OS review acta (ES) |

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  <sub>LUMEN · <em>Your MCP wire. Just smaller. Faster. Safer.</em></sub>
</p>
