# LUMEN Game Session — Bug Hunt Diagnosis (18/06/2026)

Practical game simulating a real bug hunt using LUMEN tools to diagnose a codebase.
The session tested 9 tools and found 2 bugs in LUMEN itself.

## Scenario

5-file Python project with known bugs (auth, API, config). Agent uses only LUMEN tools.

## Tools Tested

| Tool | Result | Notes |
|------|--------|-------|
| `list_directory` | ✅ | Explored 3 dirs, glob filter works |
| `search_with_context` | ✅ | Found 3 bugs with ±3 context lines |
| `assume` | ✅ | 3 assumptions registered |
| `model_add` | ✅ | 5 files mapped with roles |
| `model_map` | ✅ | Visual tree with emoji icons |
| `context_preserve` | ✅ | 3 critical findings saved |
| `context_check` | ✅ | Risk assessment + categories |
| `read_files` | ❌ | Windows path bug — see below |
| `check_assumption` | ⚠️ | IDs lost between server instances |

## Bugs Found in LUMEN

### 🐛 `read_files` fails with Windows paths

**Symptom**: `read_files(paths=[os.path.join(TD, "src/auth.py"), ...])` returns "NOT FOUND"
**Cause**: Backslash vs forward slash mismatch in `resolve_path()`. `os.path.join` produces backslashes on Windows; the server's path resolution doesn't normalize them.
**Fix**: Add `os.path.normpath(path)` in `resolve_path()` before checking existence.
**Impact**: Any `read_files` call with Windows-style paths fails silently.
**Severity**: Medium — `read_file` (singular) works, so there's a workaround.

### ⚠️ `check_assumption` IDs reset between server instances

**Symptom**: `check_assumption(assumption_id=1)` returns "not found" after server restart
**Cause**: `_assumptions` is stored in-memory only. Each server start = fresh state.
**Impact**: Low — assumptions are session-scoped by design. The `context_preserve` tool handles long-term preservation.
**Workaround**: Use `context_preserve` for cross-session findings; `assume` for in-session reasoning.

## Test Project

Repo structure:
```
src/auth.py      — JWT auth, md5 hashing bug
src/db.py        — In-memory user DB
src/api.py       — API endpoints
tests/test_auth.py — Unit tests
config.py        — Exposed SECRET_KEY bug
```
