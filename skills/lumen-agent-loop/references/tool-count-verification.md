# Tool Count Verification — Multi-Server MCP Projects

When a README or other doc claims tool counts across multiple MCP servers, verify EVERY number against source code. Never trust asserted counts.

## Procedure

### 1. Find TOOLS lists

Each server's Python source has a `TOOLS = [...]` list. Locate them:

```bash
grep -rn "TOOLS\s*=\s*\[" implementations/mcp-servers/ --include="*.py"
```

Typical locations:
- `filesystem/shared_tools.py`
- `web/server.py`
- `thinking/server.py`
- `pdb/pdb_tools.py`

### 2. Count tool dicts, not string occurrences

`grep -c` counts all matches — use Python for accurate tool-dict counting:

```python
import re
with open("server.py") as f:
    content = f.read()
start = content.index("TOOLS = [")
# find matching close bracket
depth = 0
for i, ch in enumerate(content[start:]):
    if ch == '[': depth += 1
    elif ch == ']': depth -= 1
    if depth == 0: end = start + i; break
tools_text = content[start:end+1]
count = len(re.findall(r'\{\s*"name"', tools_text))
```

### 3. Account for embedded modules

Some servers import tool schemas from external modules:

- `thinking/objective_loop.py` has `OBJECTIVE_SCHEMAS` (separate from server.py's `TOOLS`)
- May use `HANDLERS` dict + `SCHEMAS` list pattern

Search for `OBJECTIVE_SCHEMAS`, `HANDLERS`, or pattern `"name":` outside the main `TOOLS =`.

### 4. Cross-reference ALL documentation files

Every doc that mentions tool counts must be checked:

| File | What it usually says |
|------|---------------------|
| `README.md` | Hero badge, benchmark table, MCP servers table, Status section |
| `HERMES_INTEGRATION.md` | Plugin overview table, MCP servers table at bottom |
| `TOOLS_GUIDE.md` | First line usually has total count |
| `docs/COGNITIVE_OS.md` | Section headers may embed tool counts |

### 5. Verify bridge registration

The bridge plugin may register a SUBSET of all tools:

```bash
grep -c "ctx.register_tool(" implementations/hermes-plugins/*/__init__.py
```

The bridge count can differ from the total tool count — document both.

### 6. Handle edge cases

| Edge case | Handling |
|-----------|----------|
| Registered but unimplemented | Note it separately (e.g. `objective_task_done` exists in schema but handler is empty) |
| Duplicate tools across servers | Check if PDB/Objective tools overlap with thinking server's list |
| Tools listed with `+` (e.g. `47+`) | Verify against actual count; remove `+` if exact count is confirmed |
| Total says "70+" but sum is 81 | Prefer exact total over vague. Update to precise sum. |

### 7. Commit hygiene

- Use `git diff --stat` to review all changed files before commit
- `git add -A` stages untracked files too — use `git add <specific-files>` if only docs changed
- After Gerard/human co-author PRs: `git fetch origin && git merge --ff-only` before your changes
- Commit message should list exact counts per server
