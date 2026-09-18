# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/). History predating this file
lives in `git log` and the GitHub Releases.

## [2026-09] — 2026-09-18

### Added
- **M-Light — `spawn:run` device**: auto-launches the compile sandbox with a
  timeout; `zroutines:rollback` (`.bak`) for ZS saves.
- **`deepseek` provider without thinking**: `"thinking":{"type":"disabled"}` in
  the request body (~702 ms, zero reasoning; the API ignores
  `chat_template_kwargs` for this).

### Fixed
- **`D ^RUTINA` — definitive fix**: routine calls now run **inline**
  (`inline_frames`) — the only path that resumes **yields** correctly
  (`$DEVICE` LLM/READ calls inside routines return their answer instead of
  empty); local labels in the routine source are rewritten to
  `D ETIQ^RUTINA` before inlining. Verified: `%LLT` yields+phrase ✓ ·
  `%TT` args ✓ · `%TT2` labels ✓.
- **`D ^RTN(args)`**: split-target regression — arguments are re-wrapped in
  `(...)` before delegation.
- **`D ^RUTINA` ≡ `D PRIMERLABEL^RUTINA`**: local labels resolve
  («unknown label CHECK» was this).
- **`spawn`**: empty timeout ⇒ 10 s default (was 1 s).
- **M classic semantics**: `$L(x,d)` = piece count · `$P` out of range = `""` ·
  `$E(x,i)` = to end of string (suite `%CONF` 37/37 green).
- **Chained `I c1 I c2 D` before a DO block**: the extra conditionals stayed
  *inside* the \x01 condition → MUNDEF «undefined variable» with plain operands,
  or (string comparisons) the block fired unconditionally. The compiler now
  normalizes the chain to comma-AND with short-circuit (`I c1, c2 D`) — same M
  semantics; verified by the new `chained_if_before_do_block` test (12 cases).

## [2026-09] — 2026-09-17

### Docs
- **Paper — *Curación distribuida de modelos LLM gratuitos*** (architecture +
  empirical evaluation: 87 validations / 14 models / 5 sources / $0): Markdown +
  print-ready HTML + `.docx` + `.pdf`.
- **LUMEN para la democratización**: fit comparison + **Lumen@Home**
  (SETI-style volunteering) + **radio P2P** (Reticulum/LoRa) — LUMEN payloads
  fit in 1 kbps.

## [2026-09] — 2026-09-16

### Added
- **M-Light — `ssh:exec` device** (feature `ssh`): SSH hands for MVMs
  (BatchMode, `^CONFIG("ssh_allow")` allowlist, hard timeout, output cap).
  **Fail-closed**: without allowlist the device is disabled (not even
  localhost).
- **Portable `Atomic64`**: shim for targets without 64-bit atomics (fixes
  mips32 builds; port to MIPS routers with build-std).

### Fixed
- **Live READ**: pending output is flushed before blocking on `R`; «live READ»
  marker in the REPL (real wait vs slow LLM).
- **thinking**: counters re-read the persisted max id before assigning
  (incident 6 fix).

## [2026-09] — 2026-09-14

### Added
- **Node devices**: `sys:top` (the node's own top — RSS/peak/CPU/threads/fds/
  load/RAM from /proc), `rag:query`/`rag:stats` (local TF-IDF over `^RAG`;
  per-book scope filter), `ddp:agent` (borrowed voice), `ddp:health`/`pull`/
  `push` (F2) and **DDP refs in the host** (F2c: `get`/`order`/`data` by
  reference + `has_value`/`has_children`, bounded cache).
- **`ddp_client.rs`** — DDP over plain `TcpStream` + legacy HMAC
  (`ts + data + key`).
- **LLM key fallback**: if the env has no key, `^CONFIG("llm_key_<prov>")` is
  used (self-configuring node; verified on the NAS at 703 ms).
- **vm_api (hub)**: `_collect`/`_push`/`_cordone`/`_allocate` **SQL-direct** +
  `ThreadingHTTPServer` + `_WRITE_LOCK` — pulls ~**850× faster**.
- **`compilation.rs` (JIT)**: `MVM_NO_JIT` gate for toolchain-less nodes; no
  retry after failure; creates workspace/src (ENOENT fix).

### Fixed
- **Interpreter**: local labels in routines (nested program context + args
  bound to the first label), multi-group `^G(a)(b)` parser, formal
  save/restore (recursion), tolerant `^AGENTES` lookup.
- **Network resilience**: `minreq` retry (3 attempts, backoff, lookup/connect
  only) for http/llm + DNS retry in the SSRF guard (LAN hiccups aborted
  suites: 11/11 and 8/8 green).
- **`host.rs` stubs without `minreq`** + stack-overflow guard in `eval_expr`.

## [2026-09] — 2026-09-13

### Fixed
- **PDB**: tolerant `decode_subkey` — 3 subkey formats that broke the DB (9.4%
  of cases).
- **thinking/kanban**: monotonic counters (`task_create` overwrote ids); dead
  path to create tasks from the dashboard repaired; `save` no longer erases
  other instances' tasks.

## [2026-09] — 2026-09-11

### Added
- 🌐 **Website — [lumen.cadences.app](https://lumen.cadences.app)**: the door to the metal —
  live numbers generated from this repo (`scripts/extract_data.py` in the private site repo),
  benchmarks, the 8 areas, MCP tools, implementations, Colab CTA; EN/ES with theme toggle.
  Repo homepage points to it.

### Fixed
- **`^ROUTINE`**: ASCII subkey decoder fixed («unknown routine LQ»); quantum
  submit now surfaces real errors (e.g. 429 from Tuna-9).

### Docs
- README: 🌐 Website link in the nav row. README_ES: same + tool-count consistency —
  **115 tools** registered across 4 MCP servers (matching the published benchmark).

## [2026-09] — 2026-09-10

### Security
- **Removed a hardcoded internal URL** from `implementations/python/pdb-sync/pdb_ddp_client.py`:
  the client now requires `PDB_EDGE_URL` (env var or local secrets file) or an explicit
  `base_url` — no private infrastructure endpoints live in this repository.

### Added
- **`examples/colab/lumen_demo.ipynb` — the demo, v3** (self-contained, zero
  keys): runs the **A·I·E tríada** (the real MIT routines from
  [astrid](https://github.com/GonzaloMonzonC/astrid),
  [iris](https://github.com/GonzaloMonzonC/iris),
  [elena](https://github.com/GonzaloMonzonC/elena)) on the real MVM + PDB,
  with:
  - a **local GPU LLM** reached through the MVM's native
    `$DEVICE("llm:call", …, "local")` provider — model selector
    (Qwen3.8-27B / Qwen3.5-9B / Qwen2.5-14B) with auto-fallback, and a 3B CPU
    mode;
  - the full **evidence → hypothesis → decision** cycle, notary contract (cid)
    and local semantic search;
  - an interactive **chat UI** (Gradio): pick a sibling or the council — with
    conversation memory, every exchange recorded in the PDB;
  - the **full MCP arsenal**: a local MCP server (system tools + thinking kit
    writing into the shared PDB), native `mcp:call` from the Rust MVM, web
    fetch via the HTTP device, and Elena signing a decision card with live
    data in hand;
  - the **parallel council**: `$FORK ×3 + $AWAIT` with the local provider
    (~3× vs sequential);
  - the **embedded browser console**: M-WASM console wired to the notebook's
    PDB (vm_api + same-origin proxy + Colab port-forward) — write M live
    (`ZW ^HYPOTHESIS`, `D ^%GL`, `S ^GLOBAL=…`).
- Release asset **`mvm-console-pkg.zip`** (console + WASM pkg) under
  `mlight-v0.1.0`.

### Fixed
- **`m_light_console.html` routines** rewritten for the current MVM parser
  (labels must start a line): `ZW` is now 2-level (keys + subkeys/values),
  `%GL` works (`^GLOBAL_SIZES` computed client-side on every merge), and
  output + errors are both shown.

### Docs
- README (+ ES): the **tríada A·I·E** referenced in the layer map, the MIT
  contents list and the closing call-to-action.
