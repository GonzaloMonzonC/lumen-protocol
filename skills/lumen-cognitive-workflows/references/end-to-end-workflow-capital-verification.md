# End‑to‑End Workflow: Hypothesis → Web Evidence → Mental Model → Work Tracking → Pattern

**Demonstrated**: June 2026, session evaluating LUMEN thinking tools.
**Pattern recorded**: #17 `CapitalVerification` (95% match via `pattern_match`).

## Workflow Steps

1. **Assume** — register a hypothesis with `assume`.
   ```
   assume(statement="The capital of France is Paris.", category="integration")
   ```

2. **Web search** (optional if source is known) — locate confirming evidence.
   ```
   web_search(query="capital of France", limit=1)
   ```

3. **Web extract** — pull the relevant page.
   ```
   web_extract(urls=["https://en.wikipedia.org/wiki/Paris"])
   ```

4. **Mental model** — store the confirmed fact.
   ```
   model_add(entity="CapitalOfFrance", properties={value:"Paris", source:"Wikipedia", fact:"Paris is the capital and largest city of France"})
   ```

5. **Work tracking** — track the verification task.
   ```
   work_start(title="Verify capital of France", description="Check that the capital of France is Paris using web evidence and record in mental model.")
   work_block(block_id="verify_capital", status="in_progress")
   work_done(block_id="verify_capital")
   ```

6. **Pattern recording** — save the whole sequence for reuse.
   ```
   pattern_record(pattern_name="CapitalVerification", description="Workflow: assume hypothesis about capital, web_search for confirmation, web_extract to get source, model_add to store fact, work_start/work_block/work_done to track task.")
   ```

## Key Lessons

- Patterns alone are **not documentation** — the user explicitly asked for a Markdown file when told the workflow was recorded as a pattern. Always write actual files to the repo (`docs/`, `acta_*.md`) when documenting workflows.
- After file writes, verify by reading the file back and showing the path.
- Commit-then-proceed: before starting a new task, commit and push changes.
- The `write_file` tool only writes to the user home directory (`C:\Users\gonzalo`) — use `terminal` + `cat heredoc` or Python to write files inside repo subdirectories.
- Cross-language fixes: read the already-fixed implementation first (usually Python), then port the pattern to other languages (Rust/PHP/TS). Verify with `search_files` across all implementations.
