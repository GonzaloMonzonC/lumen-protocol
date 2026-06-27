# LUMEN Tools Guide — When to Use Each Tool

Practical decision guide for all 90 LUMEN MCP tools across 4 servers.
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


## Kanban (Project Management)

### `niche_create`
**Case**: Start a new project area.
**Example**: "Create a niche for the auth refactor."
**Why**: Organizes tasks into columns (Backlog, In Progress, Review, Done, Blocked).

### `task_create`
**Case**: Add a task to a niche.
**Example**: "Create task to implement JWT validation in the auth niche."
**Why**: Tasks live in PDB, persist across sessions, linkable to reasoning chains.

### `task_move`
**Case**: Change task status or priority.
**Example**: "Move the JWT task to In Progress."

### `task_list` / `task_search`
**Case**: See what's pending or find a specific task.
**Example**: "Show all high-priority tasks."

### `task_link`
**Case**: Connect a task to its reasoning chain or pattern.
**Example**: "Link this task to the chain where we designed the fix."

### `niche_list` / `niche_update` / `task_delete`
**Case**: Manage projects — archive old ones, delete stale tasks.

---

## Wiki (Institutional Knowledge)

### `wiki_create`
**Case**: Document architecture, decisions, or guides.
**Example**: "Create a wiki page explaining the PDB persistence architecture."
**Why**: Wiki pages are permanent and survive server restarts (PDB-backed).

### `wiki_read` / `wiki_update` / `wiki_list` / `wiki_delete`
**Case**: Reference or maintain institutional knowledge.
**Tip**: Use `wiki_update(mode="append")` for accumulating session logs.

---

## Patterns, Decisions & Q&A (Knowledge Artifacts)

### `pattern_record`
**Case**: Save a bug fix with reproduction steps for future reference.
**Example**: "Record the SHM timeout fix as a pattern."

### `pattern_match` / `pattern_suggest`
**Case**: Check if a current problem matches a known pattern.
**Why**: The system auto-suggests patterns with >30% keyword overlap.

### `decision_log`
**Case**: Document an architectural decision with rationale and alternatives.
**Example**: "Log the decision to use PDB over JSON persistence."

### `qa_ask`
**Case**: Store a factual question and answer for quick reference.
**Example**: "What port does the dashboard use?" -> ":9876"

### `qa_list` / `qa_link`
**Case**: Browse knowledge or link Q&A to a task/chain.

---

## Objectives (Agent Loop)

### `objective_create`
**Case**: Define a high-level goal with acceptance criteria.
**Example**: "Create objective to implement OAuth2 with 3 criteria."
**Phases**: BUILDER -> BUILDING -> TESTING -> DONE.

### `objective_judge`
**Case**: Evaluate objective quality and advance phases.
**Tip**: `mark_done=true` auto-completes all tasks and criteria in one call.

### `objective_plan`
**Case**: Decompose an objective into subtasks.
**Called after**: The objective passes judge in BUILDING phase.

### `objective_status`
**Case**: Check progress — phase, score, task completion bar.

### `objective_task_done`
**Case**: Mark a specific subtask as completed.

---

## Cognitive State & Session Management

### `state_snapshot`
**Case**: Quick health check — chains, thoughts, works, tool calls in 1 line.
**Best for**: Session start baseline.

### `state_feeling`
**Case**: Record your cognitive state (mood, confidence, energy).
**Why**: Persists to PDB and shows in the dashboard.

### `cognitive_integrity`
**Case**: Full system health audit — linked tasks, stale decisions, orphaned Q&A.
**Target**: Score >=80/100.

### `cognitive_pulse`
**Case**: Detect stagnation — "Have I been stuck for 30+ minutes?"

### `work_start` / `work_done` / `work_block` / `work_log`
**Case**: Track multi-session work items.
**Note**: `work_done` auto-triggers `session_end` when all works are complete.

### `session_end`
**Case**: Close a session with summary and cleanup ritual.

---

## Mental Model

### `model_add`
**Case**: Build a knowledge graph of entities and relationships.
**Example**: "Add Thinking Server with deps=[SHM, PDB]."

### `model_query` / `model_map` / `model_stats` / `model_remove` / `model_scan`
**Case**: Explore, visualize, or prune the mental model graph.

### `unified_search`
**Case**: Search across ALL subsystems at once (tasks, patterns, decisions, Q&A, model, snapshots).

---

## Utilities

### `context_preserve` / `context_check` / `context_estimate`
**Case**: Anchor critical context across context compressions.

### `assume` / `check_assumption` / `list_assumptions`
**Case**: Surface and validate hidden premises during decision-making.

### `tool_cache`
**Case**: Cache expensive results (GET/SET with TTL).

### `batch_call`
**Case**: Execute multiple tools in sequence, get 1 compact output.

---


## Golden Rule: LUMEN or Built-in?

**Use LUMEN when:**
- ✅ Operation repeats often (wire savings accumulate)
- ✅ Multi-agent workflow (1 server for all agents)
- ✅ Need exclusive features (bulk, context, thinking, Windows parity tools)
- ✅ Want zero API key dependencies (web without Firecrawl)
- ✅ On Windows (shell tools unreliable — LUMEN is native, structured, safe)

---

## Thinking Tools — Cross-Session Cognition

### Reasoning & Analysis
| Tool | When to Use | Example |
|------|-------------|---------|
| `sequential_thinking` | Complex multi-step problems | "Plan a DB migration with 10 steps" |
| `thought_contradiction` | Verify consistency | "Does this conclusion contradict earlier analysis?" |
| `thought_evaluate` | Quality check reasoning | "Score this plan: is it specific and actionable?" |
| `thought_similarity` | Avoid repeating reasoning | "Have I analyzed this before?" |
| `thought_summarize` | Distill long chains | "Summarize 50 thoughts into 3 themes" |
| `thought_to_plan` | Convert thinking to action | "Convert reasoning chain to markdown plan" |
| `thought_bridge` | Cross-session insight | "Connect this analysis with past sessions" |

### Institutional Memory
| Tool | When to Use | Example |
|------|-------------|---------|
| `pattern_record` | Capture bug fix | "Record null-check-async pattern" |
| `pattern_match` | Recall past solutions | "Have I seen this error before?" [18-38% Jaccard] |
| `decision_log` | Track design choices | "We chose SQLite. Revisit if >100 users." |
| `decision_list` | Review past decisions | "What did we decide about auth?" |

### Mental Model (Knowledge Graph)
| Tool | When to Use | Example |
|------|-------------|---------|
| `model_add` | Add entity with deps | "Auth service depends on User DB, Cache" |
| `model_query` | Explore relationships | "What depends on User DB?" |
| `model_stats` | Overview | "How many entities in the model?" |
| `model_map` | Visualize | "Show full dependency graph" |

### Cross-Session Communication 🆕
| Tool | When to Use | Example |
|------|-------------|---------|
| `agent_message` | Coordinate with other agent | "Tell agent-b: PR approved, merge now" |
| `agent_inbox` | Check for messages | "Any messages from other sessions?" |
| `collision_check` | Detect file conflicts | "Is anyone else editing auth.py?" |

### Work Tracking & Context
| Tool | When to Use | Example |
|------|-------------|---------|
| `work_start/block/done` | Multi-session tasks | "Auth refactor: 3 blocks, 2 sessions" |
| `context_preserve` | Anchor critical info | "Preserve error stack trace for 24h" |
| `session_init` | Isolate parallel work | "Agent A and B: separate chains, no bleed" |
| `session_list` | See active agents | "Who's working on what?" [collision warnings] |

### DECISION: When to use Thinking Tools
```
Complex problem?    → sequential_thinking + thought_evaluate + thought_to_plan
Uncertain decision? → assume + check_assumption + decision_log
Recurring bug?      → pattern_record + pattern_match
Multi-agent work?   → session_init + agent_message + collision_check
Long task?          → work_start/block/done + context_preserve
```

**Use Built-in when:**
- ✅ One-off simple operation (read 1 small file)
- ✅ Professional web quality is critical (Firecrawl > DuckDuckGo)
