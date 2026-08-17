# LUMEN + Hermes Agent — Installation Guide

> **Status**: ✅ Verified — **115 tools across 4 MCP servers** (filesystem, web, thinking, PDB)
> **PR**: [NousResearch/hermes-agent#47740](https://github.com/NousResearch/hermes-agent/pull/47740)
> **Transport**: JSON-RPC stdio (plain MCP) — the path verified with the Hermes MCP client

---

## Quick Install (2 minutes)

### Option A — Setup script (recommended)

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol

# macOS / Linux / git-bash (Windows)
bash scripts/setup_hermes_mcp.sh

# Windows (cmd/PowerShell)
scripts\setup_hermes_mcp.bat
```

The script creates the venv, installs `lumen-mcp`, registers the 4 servers
with `hermes mcp add`, and verifies with `hermes mcp list`.

### Option B — Manual

#### 1. Clone the repo

```bash
git clone https://github.com/GonzaloMonzonC/lumen-protocol.git
cd lumen-protocol
```

#### 2. Create venv + install LUMEN Python package

```bash
python -m venv .venv
# Windows:
.venv\Scripts\pip install -e implementations\python
# macOS / Linux:
.venv/bin/pip install -e implementations/python
```

> The MCP servers must run with this venv's python — they import the `lumen` package.

#### 3. Register the 4 MCP servers

```bash
hermes mcp add lumen-filesystem --command "C:/abs/path/lumen-protocol/.venv/Scripts/python.exe" --args "C:/abs/path/lumen-protocol/implementations/mcp-servers/filesystem/server.py"
hermes mcp add lumen-web        --command "C:/abs/path/lumen-protocol/.venv/Scripts/python.exe" --args "C:/abs/path/lumen-protocol/implementations/mcp-servers/web/server.py"
hermes mcp add lumen-thinking   --command "C:/abs/path/lumen-protocol/.venv/Scripts/python.exe" --args "C:/abs/path/lumen-protocol/implementations/mcp-servers/thinking/server.py"
hermes mcp add lumen-pdb        --command "C:/abs/path/lumen-protocol/.venv/Scripts/python.exe" --args "C:/abs/path/lumen-protocol/implementations/mcp-servers/pdb/server.py"
```

(macOS/Linux: use `.venv/bin/python` and `/abs/path/...`.)

Equivalent `~/.hermes/config.yaml` block (plain stdio JSON-RPC — **no
`transport: lumen` keys needed**; the LUMEN binary transport is optional, see below):

```yaml
mcp_servers:
  lumen-filesystem:
    command: C:/abs/path/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/abs/path/lumen-protocol/implementations/mcp-servers/filesystem/server.py]
    enabled: true
  lumen-web:
    command: C:/abs/path/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/abs/path/lumen-protocol/implementations/mcp-servers/web/server.py]
    enabled: true
  lumen-thinking:
    command: C:/abs/path/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/abs/path/lumen-protocol/implementations/mcp-servers/thinking/server.py]
    enabled: true
  lumen-pdb:
    command: C:/abs/path/lumen-protocol/.venv/Scripts/python.exe
    args: [C:/abs/path/lumen-protocol/implementations/mcp-servers/pdb/server.py]
    enabled: true
```

#### 4. Restart Hermes

```
/reset
```

#### 5. Verify

```bash
hermes mcp list
```

All 4 servers must show `✓ enabled`. Then, in the agent's tool catalog, search
for `mcp__lumen_*` — the 115 tools will be listed there.

---

## What You Get

| Server | Tools | Key Features |
|--------|-------|--------------|
| **Filesystem** | 13 | Bulk reads, context search, streaming, health metrics, zero shell dependency |
| **Web** | 2 | Search + extract in 1 call, no API key |
| **Thinking** | 81 | External reasoning, kanban/niches, wiki, patterns, decisions, PDB watches, dashboards |
| **PDB** | 19 | Persistent `^ns(key)=value` store, vector search (KNN), MVM app registry, notifications |
| **Total** | **115** | 0 API keys required |

---

## Optional: Native LUMEN binary transport (50-80% wire savings)

For even more compression, the servers also ship a native binary mode
(`server_native.py` + `transport: lumen`). This path is **experimental** with
the current Hermes MCP client — the JSON-RPC stdio config above is the
verified, recommended setup:

```yaml
mcp_servers:
  lumen_filesystem:
    command: "python"
    args:
      - "path/to/lumen-protocol/implementations/mcp-servers/filesystem/server_native.py"
    transport: lumen
    lumen_force_json_rpc: false  # native binary mode
```

---

## Troubleshooting

### "MCP server failed to connect" / discovery hangs

Hermes's MCP client requires a full `initialize` + `tools/list` handshake.
The PDB server had a bug that made discovery hang; **it is fixed in the repo**
(commit `7499c3a`, `pdb/server.py`). If you're on an old checkout:

```bash
git pull
```

Then re-test the server manually:

```bash
# Windows
.venv\Scripts\python.exe implementations\mcp-servers\pdb\server.py
# macOS / Linux
.venv/bin/python implementations/mcp-servers/pdb/server.py
```

### `pdb_set` returns "unable to open database file"

The database now lives at `implementations/mcp-servers/pdb/lumen-pdb.db` (inside
the repo, auto-created — see `_paths.py`). It previously pointed at a hardcoded
path on the developer's machine. Override with the `PDB_PATH` / `PDB_DB`
environment variables (useful for benchmarks):

```bash
export PDB_PATH=/path/to/my-pdb.db
```

### "LUMEN SDK not available"

```bash
.venv\Scripts\pip install -e implementations\python   # or .venv/bin/pip on macOS/Linux
```

### Server registered but 0 tools

- Make sure the `command` points to the **venv** python (not the system python).
- Check Hermes logs: `cat ~/AppData/Local/hermes/logs/mcp-stderr.log | tail -20`
- Restart Hermes with `/reset` after registering.

---

## See Also

- [HERMES_INTEGRATION.md](HERMES_INTEGRATION.md) — Full integration guide
- [TOOLS_GUIDE.md](implementations/mcp-servers/docs/TOOLS_GUIDE.md) — When to use each tool
- [RETROSPECTIVE.md](implementations/mcp-servers/RETROSPECTIVE.md) — Before/after comparison
