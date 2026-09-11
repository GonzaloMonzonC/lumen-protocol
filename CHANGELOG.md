# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/). History predating this file
lives in `git log` and the GitHub Releases.

## [2026-09] — 2026-09-11

### Added
- 🌐 **Website — [lumen.cadences.app](https://lumen.cadences.app)**: the door to the metal —
  live numbers generated from this repo (`scripts/extract_data.py` in the private site repo),
  benchmarks, the 8 areas, MCP tools, implementations, Colab CTA; EN/ES with theme toggle.
  Repo homepage points to it.

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
