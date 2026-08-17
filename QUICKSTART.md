# 🚀 LUMEN Quickstart — from zero to LLM agents in ~10 minutes

> **Status**: ✅ Verified 2026-08-18 on Windows 11 (git-bash) + Python 3.11 · macOS/Linux commands included
> **What you'll have at the end**: the **MVM running locally with native LLM agents** (DeepSeek / OpenRouter),
> persistent PDB storage, DDP sync — no account needed beyond one LLM API key.

---

## What is LUMEN?

**LUMEN** (*Lightweight Universal Model Exchange Network*) is an ecosystem for
persistent, agentic computation:

| Piece | What it is |
|-------|------------|
| **MVM** | A Rust virtual machine that executes **M** code (a small, terse language: `S ^KANBAN("t1")="x"`) — with **native LLM calls** (`$DEVICE("llm:call",...)`) and multi-agent orchestration (Smith) |
| **PDB** | A SQLite-backed persistent store: `^namespace(key)=value` with binary encoding, vector search (KNN), audit trail |
| **vm_api** | The local HTTP engine (`:8081`): execute M, DDP sync, agent dispatcher, web routes |
| **MCP servers** | 4 servers (115 tools) that plug LUMEN into [Hermes Agent](https://hermes-agent.nousresearch.com) — see `INSTALL.md` |
| **Workers (optional)** | Cloudflare Worker agents (tom, angi, …) reachable through the dispatcher |

Everything runs **locally** (except the optional Cloudflare workers). Your data
lives in a SQLite file inside the repo (gitignored).

---

## 1. Prerequisites

- **Python** 3.10+ (3.11 tested)
- **git**
- **Rust toolchain** (`cargo`) — only needed to build the MVM DLL **once** (≈4 min)
- **One LLM API key** — DeepSeek (the system default) or OpenRouter

---

## 2. Clone + virtualenv

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

python -m venv .venv
# Windows:
.venv/Scripts/pip install -e implementations/python
# macOS / Linux:
.venv/bin/pip install -e implementations/python
```

---

## 3. Build the MVM (⚠️ critical — don't skip)

The Rust MVM ships as a compiled library (`lumen_mlight.dll` / `.so` / `.dylib`)
that is **not committed** to the repo. The first time you start the engine
without it, startup silently runs a blocking `cargo build` (~4 min) that looks
like a hang. Build it explicitly:

```bash
cd implementations/rust/lumen-m-light
cargo build --release --features minreq     # ≈4 min first time
cd ../../..
# result: target/release/lumen_mlight.dll  (Windows) / .so (Linux) / .dylib (macOS)
```

> If you later `git pull` Rust changes, rebuild (the engine checks file mtimes
> and degrades to a slow Python fallback if the library is stale — you'd see
> `[UNKNOWN $DEVICE]` in agent calls). On Windows, **stop the running server
> before rebuilding** or cargo fails with "Access denied" (the DLL is locked).

---

## 4. Set your API key (never commit it!)

The MVM reads the key from the **process environment**:

```bash
# DeepSeek (default provider/model: deepseek / deepseek-v4-flash)
export DEEPSEEK_API_KEY=sk-...
# or OpenRouter:
export OPENROUTER_API_KEY=sk-or-...
```

For a persistent setup, use a gitignored `.env`-style file or your shell rc —
**never** put the key in the repo. `*.db` is already gitignored; add `.env` if
you use one. If a key is ever exposed (e.g. pasted in a shared chat), rotate it.

---

## 5. Start the engine

```bash
# Windows
.venv/Scripts/python.exe implementations/python/pdb-sync/vm_api.py 8081
# macOS / Linux
.venv/bin/python implementations/python/pdb-sync/vm_api.py 8081
```

In another terminal, verify:

```bash
curl http://localhost:8081/ddp/health
# → {"ok": true, "ddp": "local", "hmac": false}
```

> The `SyntaxWarning: invalid escape sequence '\$'` lines at startup are
> pre-existing and harmless.

> **Background processes don't inherit `export`!** If you launch the server in
> the background (nohup, `&`, a process manager), pass the key **literally in
> the command**: `DEEPSEEK_API_KEY=sk-... python vm_api.py 8081`. Otherwise
> agent calls fail with `401 Authentication Fails (auth header format should be
> Bearer sk-...)`.

---

## 6. Run M code

```bash
curl -s -X POST http://localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S ^MI_PRIMER_NS(1)=\"hola\" W \"escrito!\""}'
# → {"ok": true, "result": "hola", ...}

curl -s "http://localhost:8081/ddp/pull?ns=MI_PRIMER_NS"
# → {"success": true, "entries": [...], ...}
```

---

## 7. Run your first agent (the good part 🧠)

The MVM has **native LLM calls** — no extra services needed:

```bash
curl -s -X POST http://localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S r=$DEVICE(\"llm:call\",\"Present yourself in one sentence\",\"You are a LUMEN agent running inside the MVM\") W r"}'
# → {"ok": true, "result": "I am LUMEN, an intelligent agent running inside the MVM...", "exec_ms": 2400, ...}
```

**Multi-agent orchestration (Smith)** — parallel forks per domain + synthesis:

```bash
curl -s -X POST http://localhost:8081/vm/execute -H "Content-Type: application/json" \
  -d '{"script": "S r=$DEVICE(\"smith:orchestrate\",\"Explain entropy in 2 sentences\",\"physics,poetry\") W r"}'
# → one synthesized answer merging both voices (~19s)
```

Full LLM contract (`llm:call`, `llm:fork`, `llm:await`, `llm:chain`,
`llm:all`, `smith:orchestrate`, `^PERSONALITY` configuration, providers,
pitfalls): **[docs/GUIA_VM_API.md §11](docs/GUIA_VM_API.md)**.

> Tip: capture results with `S r=$DEVICE(...)` (an assignment), not
> `W $DEVICE(...)` — `W` writes to the output stream, `S` leaves the value on
> the stack so the API returns it in `result`.

---

## 8. Optional: agent registry + dispatcher

Seed the local agent registry (17 agents: Cloudflare workers + Poli personality
modes) and chat through the dispatcher:

```bash
.venv/Scripts/python.exe implementations/python/pdb-sync/seed_agentes.py   # or .venv/bin/python

curl -s -X POST http://localhost:8081/ddp/agent/chat -H "Content-Type: application/json" \
  -d '{"agente": "tom", "mensaje": "hello"}'
```

Remote workers require the shared HMAC secret (`DDP_HMAC_KEY` or `x-tom-key`)
that you configured when deploying them; without it they answer
`{"ok":false,"error":"Se requiere X-DDP-HMAC o x-tom-key"}`. Local Poli modes
(`tipo: poli`) need the separate `poli` core repo. The MVM agents from step 7
need **none** of that — they run entirely local.

---

## 9. Optional: connect to Hermes Agent (MCP)

LUMEN ships 4 MCP servers (115 tools: filesystem, web, thinking, PDB).
Follow **[INSTALL.md](INSTALL.md)** (or `INSTALL_ES.md`).

---

## 10. What you can build now

- **Agents with personalities** — set identity/provider/model per domain:
  `S ^PERSONALITY("fisica","identity")="Eres un fisico teorico"` then use
  `smith:orchestrate` (see `GUIA_VM_API.md` §11)
- **MVM apps** — register an app in `^APPS`, generate M code from a description,
  run it as a process, fork it, promote it (PDB MCP tools `pdb_mvm_app_*`)
- **LLM workflows** — `llm:fork` + `llm:await` for parallel calls, `llm:chain`
  for sequential reasoning
- **Routines** — persist M routines in `^ROUTINE` and call them by name
- **Internet from M** — `$DEVICE("http:get"|"http:post", url, ...)` (F1)
- **DDP sync** — push/pull namespaces between machines (with HMAC)
- **Web routes** — register M routines as HTTP endpoints on `:8081`

---

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| Startup "hangs" (no banner) | First-time `cargo build` for the missing DLL | Wait ~4 min or build manually (step 3) |
| Agent call returns `[UNKNOWN $DEVICE]` | Stale DLL (repo updated Rust sources) | Rebuild (step 3); stop server first on Windows |
| `401 ... should be Bearer sk-...` | Key missing in the **server process** env | Pass the key literally in the launch command (step 5) |
| `cargo build` → "Access denied" | Server running with the DLL loaded (Windows) | Stop the server, rebuild, restart |
| `HMAC auth failed` (DDP/workers) | Secret mismatch between local and worker | Set the same `DDP_HMAC_KEY` on both sides |
| `'utf-8' codec can't decode byte 0xbf...` in `/vm/execute` with accents/`¿` | Windows git-bash `curl -d` sends the body in the console codepage, not UTF-8 | Write the JSON to a UTF-8 file and use `curl --data-binary @file.json` |
| `/vm/execute` errors | Read the `error` field in the response | It's the engine's actual message |
| DB "unable to open database file" | `PDB_PATH`/`PDB_DB` points elsewhere | Unset them or point to a writable path |

---

## Where to go next

| Doc | Content |
|-----|---------|
| **[INSTALL.md](INSTALL.md) / [INSTALL_ES.md](INSTALL_ES.md)** | LUMEN + Hermes Agent (MCP servers) |
| **[docs/GUIA_VM_API.md](docs/GUIA_VM_API.md)** | vm_api deep dive: endpoints, `/vm/execute` contract, HMAC, audit, **LLM agents (§11)** |
| **[docs/EXTENSIBILIDAD-MVM.md](docs/EXTENSIBILIDAD-MVM.md)** | MVM device HTTP + roadmap F2/F3 |
| **[docs/INDEX.md](docs/INDEX.md)** | Full documentation map |
| **[docs/diario/](docs/diario/)** | Daily operation logs (Spanish) |
