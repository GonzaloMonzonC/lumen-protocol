<p align="center">
  <br>
  <h1 align="center">◆ LUMEN Protocol</h1>
  <p align="center"><strong>The open binary transport for AI agent societies</strong></p>
  <p align="center"><em>Zero-copy · hierarchical · edge — MIT licensed</em></p>
  <p align="center">
    The rest of the world is running societies of AI agents on 2010s web architecture.
    <br>
    LUMEN runs them on <strong>binary, hierarchical, zero-copy memory at the edge</strong>.
  </p>
  <br>
</p>

<p align="center">
  <strong>Open metal:</strong> binary protocol, zero-copy transport, PDB/MVM cognitive state, M-Light evaluator, Poli + Smith agents, 115 MCP tools.
  <br>
  <a href="QUICKSTART.md"><strong>🚀 Quickstart</strong></a> · <a href="QUICKSTART_ES.md"><strong>Empezar aquí</strong></a> &nbsp;|&nbsp;
  <a href="INSTALL.md"><strong>🚀 Install in Hermes Agent</strong></a> &nbsp;|&nbsp;
  <a href="docs/COGNITIVE_OS.md"><strong>🧠 Cognitive OS docs</strong></a> &nbsp;|&nbsp;
  <strong>✅ Level 2 SHM zero-copy · 55-80% wire savings · 4 MCP servers · works with Hermes</strong>
</p>

---

## 🌍 Why LUMEN exists — the three bets

> *"The world is trying to make AI societies run on slow web architectures from the 2010s. We built an execution engine that is binary and hierarchical at the edge, where agents are not scripts connected by APIs but cognitive threads sharing the same physical memory, auditing each other in real time."*

Three bets. Three walls the industry will hit:

**1. The I/O collapse (the JSON-RPC problem).** While a human talks to an LLM, JSON latency is invisible. When 10 agents debate, extract data, review schemas and run retrospectives, the system becomes I/O-bound — the wire, not the model, is the bottleneck. The inevitable future of multi-agent orchestration is **binary transport and shared zero-copy memory at the edge**. LUMEN already ships it, benchmarked: **55-80% wire savings, Level 2 SHM (mmap ring buffers, zero kernel copies, sub-ms latency), 20K calls/sec in enterprise stress tests, 46% smaller LLM token streams**.

**2. The end of the "RAG memory" patch.** Giving agents memory by force-injecting vector databases into stateless architectures is a patch — vectors are an index, not a memory. The real future of artificial cognition is **transactional, structured, hierarchical state that acts as native cognitive memory**: a virtual machine on disk where decisions, dictionaries and behavioral patterns live intrinsically in the infrastructure. That is **PDB + MVM**: MUMPS (1966) heritage globals, `$LOCK`, `^IDX` auto-indexes, `ON SET`/`ON KILL` triggers, WAL journaling, 15 μs/GET — and an M Virtual Machine running autonomous, persistent processes.

**3. Software Factory, not a developer framework.** The mainstream is hostage to Python/TypeScript, and the human should not have to touch the metal. LUMEN is the **open metal** of a full cognitive OS: agents that write their own M logic, share the same memory, and execute deterministically at the edge. On top of this repo, Cadences Lab has built **[ECOS](https://ecos.cadenceslab.com)** (Edge Cognitive Operating System) — the orchestration layer where specialized agents run as teams and the human acts as Chief Operating Officer. That layer is proprietary; the metal below it is MIT.

**Layer map**

| Layer | What it is | Open here? |
|-------|-----------|-----------|
| LUMEN protocol + transports | Binary wire (Hyb128), SHM zero-copy, datagram, QUIC, ChaCha20-Poly1305, macaroons | ✅ **This repo (MIT)** |
| PDB + M-Light + MVM | Hierarchical cognitive state, M evaluator, autonomous M processes | ✅ **This repo** |
| Poli + Smith | The open agent of LUMEN (memory, personalities, M logic) and its multi-personality orchestrator | ✅ **This repo** |
| MCP servers (115 tools) | Filesystem, web, thinking, PDB — ready for Hermes Agent | ✅ **This repo** |
| [ECOS — Edge Cognitive Operating System](https://ecos.cadenceslab.com) | Multi-agent teams, memory consolidation, voice, Lab — built on LUMEN | 🔒 Proprietary layer |
| Cadences Lab | The company running its agent ecosystem on LUMEN | 🔒 Proprietary |

**What's open here (MIT):**
- **Protocol & transports** — Hyb128 framing, static + session dictionaries, binary compression, native streaming, macaroons (zero-trust capability auth), ChaCha20-Poly1305 wire encryption, X25519, MUX channels; 4 levels: stream (stdio/TCP/WS), SHM zero-copy (mmap), datagram (UDP+multicast), QUIC (WAN).
- **PDB — Process Database** — hierarchical KV+SQL with MUMPS heritage: `$LOCK`, `^IDX` auto-indexes, `ON SET`/`ON KILL` triggers, WAL journaling, 15 μs/GET, 40 MCP tools.
- **M-Light + MVM — the M Virtual Machine** — MUMPS evaluator and autonomous M processes: spawn, tick, mailbox, kill, persistence across restarts. Rust reference implementation (`lumen-m-light`, `lumen-mvm`, `lumen-pdb`).
- **Poli — the open agent** — the agent that lives inside the MVM: memory, personalities and M logic (`implementations/mcp-servers/poli/`).
- **Smith — multi-personality orchestration** — detects domains, activates expert profiles in parallel, synthesizes a unified answer (`implementations/rust/lumen-m-light/src/smith.rs`).
- **MCP servers (115 tools)** — filesystem (13), web (2), thinking (81), PDB (19); zero API keys.
- **Bindings** — Rust (reference), TypeScript, Python, PHP, C#/.NET, WASM (22 KB gzipped).

**What you can do here today:** replace your JSON-RPC MCP wire with a binary one (55-80% smaller), give your agent a persistent hierarchical brain (PDB), run autonomous M processes at the edge (MVM), and even run the open agent Poli with its multi-personality orchestrator Smith — all with zero API keys.

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

# Register the 4 MCP servers in Hermes Agent (115 tools):
bash scripts/setup_hermes_mcp.sh    # Windows: scripts\setup_hermes_mcp.bat
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

> **Benchmarked**: 115 tools across 4 servers, 0 errors. See [cognitive benchmarks](implementations/mcp-servers/pdb/bench-results/INFORME_GLOBAL.md) and [raw speed](docs/BENCHMARKS.md).

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
| **PHP** | `implementations/php/` | Core protocol (Hyb128, compression, dict). E2E: 217/217 passing |
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

> **115 tools across 4 MCP servers, 0 API keys required. 9× faster than Hermes built-ins on filesystem ops.**

> **🧠 PDB** — 40 tools, a hierarchical KV+SQL database with MUMPS (1966) heritage. No schemas, no migrations, 15 μs per GET. Includes $LOCK, ^IDX auto-indexes, ON SET/ON KILL triggers, ^GLOBAL→file global mapping, automatic partitioning, WAL journaling (concurrent readers + writer), DBFIX, and an M REPL. It is where the agent keeps its persistent memory. [More in COGNITIVE_OS.md →](docs/COGNITIVE_OS.md#-pdb-process-database--la-memoria-del-agente)

---

## 🧠 Your Personal Assistant with Cognitive Superpowers

LUMEN is not just a fast protocol. On top of Hermes Agent, it becomes a **personal assistant with memory, organization, and state awareness**:

| Capability | Tools | What it does for you |
|-----------|-------|-------------------|
| **📋 Cognitive kanban** | `niche_create`, `task_create`, `task_move`, `task_list`, `task_search`, `kanban_stats` | Organizes projects into niches, tracks tasks, measures velocity |
| **📚 Persistent wiki** | `wiki_create`, `wiki_read`, `wiki_update`, `wiki_delete`, `wiki_list` | Documents decisions, keeps knowledge across sessions |
| **🐞 Bug memory** | `pattern_record`, `pattern_suggest`, `pattern_match` | Learns from past mistakes, suggests known fixes |
| **📋 Decision log** | `decision_log`, `decision_list` | Architecture with rationale, alternatives, review triggers |
| **❓ Permanent Q&A** | `qa_ask`, `qa_list`, `qa_link` | Answer a question once, reuse it forever |
| **🧠 Mental model** | `model_add`, `model_map`, `model_query`, `model_stats` | Builds a graph of domain concepts |
| **🔗 Structured reasoning** | `sequential_thinking`, `thought_evaluate`, `thought_to_plan`, `thought_bridge` | Decomposes problems, evaluates hypotheses, generates plans |
| **🎯 Agent Loop** | `objective_create`, `objective_judge`, `objective_plan`, `objective_status` | Autonomous BUILD→TEST cycle with acceptance criteria |
| **🩺 Self-diagnosis** | `cognitive_integrity`, `cognitive_pulse`, `state_snapshot`, `unified_search` | Detects orphaned tasks, stalled patterns, unanswered Q&A |
| **📊 Real-time dashboard** | `:9876` — metrics, kanban, chains, works, M Console | Monitor your session like a pilot monitors the cockpit |
| **💾 PDB — persistent memory** | 40 tools: `pdb_set`, `pdb_get`, `pdb_order`, `pdb_query`, `pdb_m_eval`... | Hierarchical, ACID, schema-less, 15 μs/GET |
| **🔍 Semantic search (RAG)** | `mcp_eb_embed`, `mcp_eb_embed_search` | Local embeddings (fastembed), 0 tokens, 100 ms/query |
| **🌐 Web + research** | `web_search`, `web_extract`, `web_snapshot` | Searches, extracts, saves snapshots for reference |
| **📁 Smart filesystem** | 13 tools: `read_file`, `search_files`, `disk_usage`, `find_duplicates`... | Zero-copy SHM, no shell dependency |
| **🔐 Multi-session** | `session_init`, `session_list`, `session_search`, `work_start`, `work_log` | Cross-session work, context recovery, logs |

> **115 tools. 0 API keys. 1 assistant that remembers, learns, and organizes with you.**

[TOOLS_GUIDE.md →](implementations/mcp-servers/TOOLS_GUIDE.md) for the full reference with examples.

---

## 🧠 The Cognitive OS — agents that build their own system

LUMEN is not a library you call: it is an operating system where the agents themselves write the programs. The M Virtual Machine runs **M routines** that live in the same persistent store as the agent memory — versioned, hot-editable and transferable between nodes.

**Routines are the system.** M code is stored in the PDB with bytecode caching (SHA256): edit a routine and the next execution picks it up — no rebuild, no deploy, no maintenance window. Agents write their own routines, and even modify each other's, with authorship and audit trail built in.

**M is hostile to humans — and that is the point.** M looks unfriendly at first: tiny, no syntactic sugar, 1960s syntax. But it is so simple and regular that an LLM writes it with far higher reliability than Python or JavaScript — less surface, less ambiguity, fewer errors. The language was not designed for human comfort: it was designed for a machine to write programs in it.

**The MVM serves web — not just API calls.** The same machine that runs agents also runs servers, all reachable from M code:

| Service | How | What it does |
|---------|-----|--------------|
| HTTP client | `O 8:"GET url"` (reqwest, async) | Call any external API, non-blocking |
| Webhook server | `O 9:":8767"` (axum) | Receive POSTs → agent mailbox |
| Process/global dashboard | `D^ROUTINE web :8767` | Live HTML: processes (`D^SS`) + globals (`D^GS`) |
| WebSocket dashboard | `:9877` | Real-time browser dashboard, 80% compression |

Because the web layer is written in the same M language, **agents can build their own webhooks, HTML pages and SPAs** — interfaces that answer real requests, generated and maintained by the system itself, no separate frontend stack.

**Devices are open, not a closed list.** The MVM reaches the world through `$DEVICE` primitives — HTTP, webhooks, LLM calls, and more. The core is MIT and designed to be extended (trait `Host`, C ABI): new devices — databases, transports, external systems — plug in from M code without touching the VM core. The system grows with the needs of its agents, not the other way around.

**Nodes are portable.** Routines transfer between nodes, processes persist across restarts (`^PROCESSES`), and agents can hibernate and migrate between machines — see [CASOS_USO_AGENTES.md](docs/CASOS_USO_AGENTES.md) (shared namespaces, hibernation, node migration).

**A neighbor that audits, not a system that replaces.** Because the MVM ships as a container, you can deploy it *next to* any existing system — the same pod, the same Kubernetes cluster — and its agents watch it continuously: record how it behaves, detect failures, talk to other agents or external systems (via `$DEVICE` HTTP/webhooks) to correlate problems, and leave logs with full traceability (who, when, what, in what order). One container adds constant auditing, maintenance alerts and an A2A bridge to whatever you already run — without touching a line of it.

**Why this runs in a different latency division.** The routine above is ~10 lines / ~180 tokens; the same flow in Python or JavaScript is 30+ lines and ~550 tokens. The MVM is Rust compiled to native — no interpreter to load before the first line — and compiles to WASM at 22 KB (Python-in-browser is ~7 MB). Measured: 15 μs/GET in PDB · 58K GET/s · 27K insert/s · 3,407 calls/s · 9× faster than Hermes built-ins · 55-80% less wire. [Benchmarks →](docs/BENCHMARKS.md)

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
| MCP servers | ✅ | **115 tools** across filesystem (**13**), web (**2**), thinking (**81**), PDB (**19**) |
| SHM zero-copy transport | ✅ | Level 2 mmap ring buffers, 8 MiB, MAX_SPIN=10M, sub-ms latency |
| Plugin bridge (Hermes) | ✅ | `lumen-shm-bridge` — 61 tools (filesystem 13, web 2, thinking 46), transparent override of built-ins |
| M-Light M evaluator | ✅ | $O, $G, $D, $P, $E, $S, $L, $F, $TR, FOR, IF, GOTO, DO, Q:cond. ~70% MSM STU |
| D^ROUTINE web | ✅ | :8767 — D^SS (processes), D^GS (globals), HTML dashboard |
| MSM Compatibility | ✅ | 14/18 MSM STU patterns. Hex #, +cast, \\div, #mod. KILL of locals, comma-SET |
| Cognitive Benchmark | ✅ | 27K insert/s, 58K GET/s, hierarchical \$ORDER, M-Light \$ORDER 0.5s/1K |
| MVM — M Virtual Machine | ✅ | Autonomous M processes: spawn, tick, mailbox, kill. D^SS panel |
| Probe/ACK negotiation | ✅ | Graceful JSON-RPC fallback |
| ChaCha20-Poly1305 encryption | ✅ | Rust + TypeScript; HKDF-SHA256 key derivation (network transports). Protects against passive eavesdropping. For active MITM protection, use QUIC (TLS 1.3) or pre-shared Ed25519 keys. |
| X25519 key exchange | ✅ | Rust + TypeScript; peer key now validated against low-order points |
| Macaroons (capability auth) | ✅ | Rust: macaroon.rs — HMAC-SHA256, auto expiry check, caveat attenuation |
| MUX channels | ✅ | Rust: mux.rs — 5 sub-commands, MuxRegistry with state machine |
| Multi-agent sessions | ✅ | Python: thinking server — session_init, session_list, per-session isolation |
| QUIC transport (L4) | ✅ | Rust: `quic.rs` — server/client endpoints, TLS 1.3, bidirectional streams, 7 tests |
| Python 3.10+ impl | ✅ | Full protocol, MCP servers, e2e suite (89/89) |
| TypeScript impl | ✅ | Node.js + browser, zero-copy SHM via koffi |
| PHP 8.1+ impl | ✅ | Core protocol. E2E: 217/217 |
| C#/.NET 9 impl | 🔶 | Hyb128 + compression + FFI. No frame layer yet (partial) |
| WASM target | ✅ | 22 KB gzipped, browser-ready |
| **🔧 Rust Cognitive OS (S1-S4)** | ✅ | Agent loop, LLM engine, native storage, HTTP/webhook — see [ARCHITECTURE.md](ARCHITECTURE.md) |
| ── PdbHost nativo (redb) | ✅ | ^GLOBALS en Rust puro, sin FFI Python |
| ── Device 8 (HTTP client) | ✅ | O 8 reqwest async, non-blocking |
| ── Device 9 (Webhook server) | ✅ | O 9 axum, POSTs → mailbox |
| ── HttpLlmEngine | ✅ | POST a API LLM desde Rust |
| ── PromptBuilder v0.2 | ✅ | ^MEMORY+^MAILBOX+^MODELS → prompt |
| ── ResponseParser | ✅ | ```m / ```tool / ```msg / texto |
| ── THINK_INTERNAL hook | ✅ | JobActor intercepta, dispatch async |
| ── ToolDispatch | ✅ | mpsc non-blocking (SHM substitute) |
| ── Agent Loop | ✅ | CHECK_MAILBOX → THINK → YIELD |
| ── WAITING + back-off | ✅ | 100ms timer, mailbox wake-up |
| ── Persistencia ^PROCESSES | ✅ | Jobs sobreviven reinicio |
| ── Tests | ✅ | 15/15 pass (unit + integration) |

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
| 7 | `conformance.json` mixed `BATCH`/`FLOW_CTL` in core (`0x01..0x10` sweep) | **RESOLVED** — split into `frame_type_constants_core` + `frame_type_constants_ext_batch_flow` (`required_capability: batch_flow`) |
| 8 | PHP e2e: 181/217 (36 failures in Frame Binary Compatibility) | **RESOLVED** — test now emits compact JSON matching the golden generator (`jsonCompact()`); suite back to 217/217 |
| 9 | PHP missing `TRANSPORT_INIT`, `TRANSPORT_ACK`, `BATCH`, `FLOW_CTL` | **RESOLVED** — constants added to `Frame.php` (+ `FLAG_FLOW_PAUSE`); remaining e2e failures are #8 |
| 10 | C# no `Frame.cs` layer | **PENDING** — requires .NET SDK; currently compression/Hyb128/FFI only |
| 11 | No capability manifest per binding | **RESOLVED** — embedded in `tests/e2e/conformance.json` under `implementations.<binding>.capabilities` (all 5 bindings) |
| 12 | Rust tests not runnable in this environment | **PENDING** — requires `cargo`; reference implementation presumed complete |

---

## Docs

| Doc | Content |
|-----|---------|
| **[docs/INDEX.md](docs/INDEX.md)** | 📍 Documentation map — start here (updated 2026-07-15) |
| **[docs/SSOT_ARQUITECTURA.md](docs/SSOT_ARQUITECTURA.md)** | 🔀 **Fuente de Verdad Única (14-08-2026)**: dónde vive cada dato, convenciones del wire DDP (push subs / prefix / jsonEsc / waitUntil / HMAC), cliente TS canónico + vendoring, jerarquía MVM (Rust = motor, Python = capa) |
| **[docs/PLAN_EVOLUCION.md](docs/PLAN_EVOLUCION.md)** | Evolution plan: PDB + M-Light + MVM roadmap by ROI |
| **[docs/CASOS_USO_AGENTES.md](docs/CASOS_USO_AGENTES.md)** | Agent-to-agent use cases: shared Namespaces, hibernation and node migration |
| **[README_EXT.md](README_EXT.md)** | Protocol spec, all benchmarks, architecture deep-dive (EN) |
| **[RFC_LUMEN.md](RFC_LUMEN.md)** | Formal IETF-style protocol RFC |
| **[SPEC_DEV.md](SPEC_DEV.md)** | Developer reference specification |
| **[HERMES_INTEGRATION.md](HERMES_INTEGRATION.md)** | Hermes Agent setup guide |
| **[docs/COGNITIVE_OS.md](docs/COGNITIVE_OS.md)** | Cognitive OS architecture, 115 tool reference |
| **[docs/BENCHMARKS.md](docs/BENCHMARKS.md)** | Consolidated benchmarks (3,407 calls/sec) |
| **[docs/enterprise-stress-testing-2026-06-20.md](docs/enterprise-stress-testing-2026-06-20.md)** | 6 enterprise scenarios, 20K calls/sec |
| **[docs/token-efficient-tools-2026-06-20.md](docs/token-efficient-tools-2026-06-20.md)** | 5 token-efficient tools (90% output savings) |
| **[docs/lumen-universal-protocol-strategy.md](docs/lumen-universal-protocol-strategy.md)** | LUMEN as universal protocol infrastructure |
| **[docs/lumen-ws-dashboard.md](docs/lumen-ws-dashboard.md)** | WebSocket dashboard with LUMEN wire format |
| **[implementations/hermes-plugins/](implementations/hermes-plugins/)** | Plugin source (lumen-shm-bridge) |
| **[examples/](examples/)** | Runnable demos with bilingual READMEs |
| **[implementations/mcp-servers/](implementations/mcp-servers/)** | MCP server implementations |
| **[implementations/mcp-servers/docs/TOOLS_GUIDE.md](implementations/mcp-servers/docs/TOOLS_GUIDE.md)** | 115 tool reference with schemas |
| **[implementations/mcp-servers/pdb/m_light.py](implementations/mcp-servers/pdb/m_light.py)** | M-Light: MUMPS evaluator for PDB |
| **[docs/ROADMAP_MLIGHT.md](docs/ROADMAP_MLIGHT.md)** | M-Light MSM Compatibility Roadmap |
| **[docs/lumen_thinking_usage.md](docs/lumen_thinking_usage.md)** | Thinking server usage guide |
| **[acta_revision_1_2026-06-20.md](acta_revision_1_2026-06-20.md)** | Cognitive OS review minutes (in Spanish) |

---

## License

MIT — see [LICENSE](LICENSE)

---

<p align="center">
  <sub>LUMEN Protocol — Your MCP wire. Just smaller. Faster. Safer.</sub>
</p>
