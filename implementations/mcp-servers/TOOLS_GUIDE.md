# LUMEN Tools Guide — When to Use Each Tool

Practical decision guide for all 44 LUMEN MCP tools across 3 servers.
Use this to choose the right tool for every scenario.

---

## Reading Files

### `read_file`
**Case**: Read 1 file, ≤2000 lines.
**Example**: "Read config.yaml to check the settings."
**Why not built-in**: 100K char guard protects LLM context from flooding.

### `read_files` 🔥
**Case**: Inspect MULTIPLE files at once.
**Example**: "Show me auth.py, models.py, and views.py."
**Advantage**: 1 round-trip instead of N. The LLM saves turns.
**Built-in**: ❌ does not exist.

### `stream_read` 🔥
**Case**: File >2000 lines or >100KB.
**Example**: "Review the 50MB production log."
**Advantage**: Chunk-by-chunk pagination. Does not flood context.
**Built-in**: ❌ does not exist. read_file caps at 2000 lines.

**DECISION:**
```
1 file <2000 lines? → read_file
2-20 small files?   → read_files 🔥
Huge file?          → stream_read 🔥
```

---

## Searching

### `search_files`
**Case**: Find ALL occurrences of something.
**Example**: "Find all TODOs in the project."
**Extra modes**: `files_only` (just names), `count` (statistics).
**Built-in**: exists but no output_mode or offset.

### `search_with_context` 🔥
**Case**: Understand the CONTEXT around a match.
**Example**: "How is the process() function used in this file?"
**Advantage**: ±N lines around match, `>>>` marks the hit line.
**Built-in**: ❌ does not exist.

**DECISION:**
```
List of matches?     → search_files
Understand context?  → search_with_context 🔥
```

---

## Writing & Editing

### `write_file`
**Case**: Create or overwrite a file.
**Example**: "Write this content to config.yaml."
**Advantage**: Auto-creates parent directories.

### `patch`
**Case**: Targeted find-and-replace in a file.
**Example**: "Change 'localhost' to '0.0.0.0' in server.py."
**Advantage**: Safe — reports if string not found or multiple matches.
**Built-in**: exists (sed-like), but LUMEN has safer error reporting.

---

## Directory Operations

### `list_directory` 🔥
**Case**: List files and directories with sizes.
**Example**: "What's in the src/ directory?"
**Advantage**: Structured output with [DIR]/[FILE] markers and sizes. No shell `ls` parsing.
**Built-in**: ❌ does not exist. Requires `ls -la` via terminal.

---

## File Info & Disk (Windows Parity) 🆕

### `file_info` 🔥
**Case**: Get detailed metadata about a file or directory.
**Example**: "What's the size, encoding, and last modified date of config.yaml?"
**Advantage**: Structured output with encoding detection. Replaces fragile `stat`/`ls -la` on Windows.
**Built-in**: ❌ does not exist. Hermes relies on shell `ls -la` (fragile on Windows).

### `disk_usage` 🔥
**Case**: Calculate total size of a directory tree.
**Example**: "How much space does node_modules/ take?"
**Advantage**: Windows has no native `du` command — this fills that gap. Skips ignored dirs (node_modules, .git).
**Built-in**: ❌ does not exist. Requires PowerShell on Windows.

### `search_filename` 🔥
**Case**: Find files by name using regex patterns.
**Example**: "Find all files with 'shm' or 'frame' in the name."
**Advantage**: Full regex support, not just globs. `search_files(target='files')` only supports glob patterns.
**Built-in**: ❌ does not exist as regex. `find -name` only supports globs.

### `find_duplicates` 🔥
**Case**: Find duplicate files by content hash (SHA-256).
**Example**: "Are there any duplicate files wasting space in this project?"
**Advantage**: Two-pass detection (size filter → SHA-256 hash). Reports wasted space per group.
**Built-in**: ❌ does not exist. Requires complex shell pipeline.

**DECISION:**
```
File metadata?            → file_info 🔥
Directory size?           → disk_usage 🔥 (especially on Windows!)
Regex filename search?    → search_filename 🔥
Duplicate detection?      → find_duplicates 🔥
```

---

## Web

### `web_search`
**Case**: Search the web.
**Example**: "Search for Python async best practices."
**Advantage**: Zero API keys. Uses DuckDuckGo with HTML fallback.
**Built-in**: exists (Firecrawl, Brave), but LUMEN needs no keys.

### `web_extract`
**Case**: Extract content from a URL.
**Example**: "Get the content of this documentation page."
**Advantage**: Combined with search in 1 unified toolchain.
**Built-in**: exists (Firecrawl).

---

## Thinking (Cognitive Operations)

### `sequential_thinking`
**Case**: Break down complex problems step by step.
**Example**: "I need to design a new API. Let me think through it."
**Advantage**: Externalized reasoning chain with branches and revisions.
**Built-in**: ❌ does not exist.

### `thought_evaluate` 🔥
**Case**: Score the quality of a reasoning step.
**Example**: "Is my third thought specific enough?"
**Advantage**: Quantifies specificity, actionability, concreteness.
**Built-in**: ❌ does not exist.

### `thought_similarity` 🔥
**Case**: Find semantically similar thoughts in a chain.
**Example**: "Am I repeating myself across these 10 thoughts?"
**Advantage**: TF-IDF cosine similarity within stdlib. No external deps.
**Built-in**: ❌ does not exist.

### `thought_contradiction` 🔥
**Case**: Detect logical contradictions in reasoning.
**Example**: "Does thought #7 contradict what I said in thought #2?"
**Advantage**: Semantic contradiction detection. Prevents inconsistent plans.
**Built-in**: ❌ does not exist.

### `thought_summarize`
**Case**: Cluster reasoning chain into thematic groups.
**Example**: "Summarize my 30-thought chain into 5 key themes."
**Advantage**: Compresses long chains for context window efficiency.
**Built-in**: ❌ does not exist.

### `thought_to_plan`
**Case**: Convert reasoning chain into actionable steps.
**Example**: "Turn my design thinking into a concrete implementation plan."
**Advantage**: Generates steps with dependencies. Markdown or JSON output.
**Built-in**: ❌ does not exist.

### `thought_bridge` 🔥
**Case**: Find cross-chain connections between reasoning sessions.
**Example**: "Did we discuss this architecture pattern in a previous session?"
**Advantage**: Cross-session knowledge discovery. Institutional memory.
**Built-in**: ❌ does not exist.

### `assume` + `list_assumptions` + `check_assumption`
**Case**: Track assumptions, surface blind spots.
**Example**: "What am I assuming about the database schema?"
**Advantage**: Exposes hidden premises. Confirms or refutes with evidence.
**Built-in**: ❌ does not exist.

### `model_add` + `model_query` + `model_stats` + `model_map` + `model_remove` + `model_scan`
**Case**: Build a mental model of a codebase or project.
**Example**: "Map out the architecture of this 500K-file monorepo."
**Advantage**: Dependency graph, role classification, auto-scan. Visual relationship map.
**Built-in**: ❌ does not exist.

### `pattern_record` + `pattern_match`
**Case**: Capture bug patterns and solutions for institutional memory.
**Example**: "We've seen this SHM timeout before — what was the fix?"
**Advantage**: Jaccard similarity matching. Cross-session pattern library.
**Built-in**: ❌ does not exist.

### `decision_log` + `decision_list`
**Case**: Record architecture decisions with rationale.
**Example**: "Why did we choose SHM over MCP config for LUMEN transport?"
**Advantage**: Decision journal with alternatives considered. Prevents revisiting resolved debates.
**Built-in**: ❌ does not exist.

### `work_start` + `work_block` + `work_done` + `work_log`
**Case**: Track multi-step work across sessions.
**Example**: "What did we complete yesterday and what's left?"
**Advantage**: Persistent work tracking. Survives context compression.
**Built-in**: ❌ does not exist.

### `context_preserve` + `context_check`
**Case**: Anchor critical info against context decay.
**Example**: "Don't forget: the API key is in .env.production not .env."
**Advantage**: Priority-tagged preservation. Critical info survives long conversations.
**Built-in**: ❌ does not exist.

### `session_init` + `session_list`
**Case**: Multi-agent session isolation.
**Example**: "Create a separate thinking space for the frontend team."
**Advantage**: Isolated chains, models, and assumptions per session.
**Built-in**: ❌ does not exist.

**DECISION:**
```
Complex problem?        → sequential_thinking
Check reasoning quality?→ thought_evaluate + thought_contradiction
Cross-session knowledge?→ thought_bridge + pattern_match
Track assumptions?      → assume + list_assumptions
Build mental model?     → model_add + model_map + model_scan
Record decisions?       → decision_log
Multi-step work?        → work_start/block/done/log
Prevent context decay?  → context_preserve
```

---

## Monitoring

### `server_stats` 🔥
**Case**: Is the LUMEN server healthy?
**Example**: "How many operations has it processed today?"
**Built-in**: ❌ does not exist.

---

## Golden Rule: LUMEN or Built-in?

**Use LUMEN when:**
- ✅ Operation repeats often (wire savings accumulate)
- ✅ Multi-agent workflow (1 server for all agents)
- ✅ Need exclusive features (bulk, context, thinking, Windows parity tools)
- ✅ Want zero API key dependencies (web without Firecrawl)
- ✅ On Windows (shell tools unreliable — LUMEN is native, structured, safe)

**Use Built-in when:**
- ✅ One-off simple operation (read 1 small file)
- ✅ Professional web quality is critical (Firecrawl > DuckDuckGo)
