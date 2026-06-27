# Game-Based Testing — Practical Tool Diagnosis

*Technique developed in session 2026-06-17.*

## The Pattern

Create a simulated project with known bugs/flaws, then use LUMEN tools to find them.
This tests tools in their REAL usage context while also stress-testing edge cases.

## Recipe

1. **Create a mini-project** with intentional flaws:
   - 5-10 files across 2-3 directories
   - Mix of roles: auth, db, api, config, tests
   - Include 3-5 known bugs (security, logic, config)
   - Use realistic content (not toy examples)

2. **Play 3 rounds** with increasing tool complexity:

| Round | Tools Tested | Goal |
|-------|-------------|------|
| 1: Exploration | `list_directory`, `model_add`, `assume` | Build mental model, register hypotheses |
| 2: Inspection | `search_with_context`, `read_files`, `context_preserve` | Find bugs, preserve findings |
| 3: Reasoning | `sequential_thinking`, `thought_to_plan`, `model_query` | Analyze, plan fixes |

3. **Diagnose after each round**:
   - Which tools worked? Which didn't?
   - Any unexpected behavior?
   - Compare LUMEN vs built-in where applicable

## What This Found

In the 2026-06-17 session, this technique discovered:
- 🐛 `read_files` returned "NOT FOUND" on Windows paths (fixed: `os.path.normpath()`)
- ✅ `search_with_context` with `>>>` marker was highlighted as "chulo" (cool) by Gonzalo
- ✅ `context_preserve` + `context_check` kept critical findings visible
- ⚠️ `check_assumption` IDs reset between server restarts (by design, in-memory)

## Why This Works

- **Real usage**: Tools are tested as the LLM would actually use them
- **Edge cases**: Windows paths, server restarts, empty models
- **User engagement**: Gonzalo described it as "un juego" (a game)
- **Self-diagnosing**: The tools find bugs in the tools
