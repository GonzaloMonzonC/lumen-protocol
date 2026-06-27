# Post-Patch Validator — Usage Guide

The validator script lives at:
`implementations/mcp-servers/thinking/post-patch-validator.py`

## When to run

After EVERY patch or execute_code operation that modifies:
- `server.py` (thinking server)
- `dashboard.html` (dashboard HTML/JS)

## What it checks

1. **Python syntax** — `py_compile.compile()` on server.py
2. **JS brace balance** — `{` vs `}` in each `<script>` block
3. **HTML div balance** — `<div>` vs `</div>` counts
4. **JS ID consistency** — `$('id')` references match existing `<div id="id">`
5. **Duplicate function definitions** — `def _detect_model()` appearing twice
6. **Script tag balance** — `<script>` vs `</script>`

## Usage

```bash
cd lumen-protocol
python implementations/mcp-servers/thinking/post-patch-validator.py
```

Or with explicit paths:
```bash
python post-patch-validator.py /path/to/server.py /path/to/dashboard.html
```

## Exit codes

- `0` — All checks passed
- `1` — One or more checks failed

## Common failures caught by this tool

| Failure | Detected as |
|---------|------------|
| Missing `}` in JS | Brace count mismatch |
| Extra `</div>` | Div count mismatch |
| JS references non-existent HTML element | ID mismatch |
| Duplicate function from repeated patch | Duplicate function warning |
| Syntax error from broken string replacement | Python compile error |
