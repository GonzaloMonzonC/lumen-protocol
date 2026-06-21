# LUMEN Sequential Thinking Server

A structured reasoning engine for LLMs. External "notebook" that persists thoughts
outside the context window — enabling revision, branching, and analysis.

## Why this matters

LLMs think inside their context window. Context gets compressed → thoughts get lost.
Sequential Thinking keeps thoughts external — they survive compression, can be revised,
branched, clustered, and bridged across sessions.

## Tools (58+ total — 37 exposed as MCP tools + internal handlers)

### 🧠 Reasoning Chain Engine (7)
| Tool | Description | Wire Savings |
|------|-------------|-------------|
| `sequential_thinking` | Record thoughts, revisions, branches. Chain persists across turns. | 60-80% |
| `thought_similarity` | Find semantically similar thoughts via TF-IDF cosine similarity. | 50-70% |
| `thought_contradiction` | Detect thoughts that contradict earlier ones (sentiment-aware, EN+ES). | 40-60% |
| `thought_summarize` | Cluster thoughts by theme (agglomerative clustering). | 55-75% |
| `thought_to_plan` | Convert reasoning chain to actionable markdown/JSON plan. | 50-70% |
| `thought_evaluate` | Score thought quality (specificity, actionability, concreteness). | 40-60% |
| `thought_bridge` | Cross-chain: find related thoughts from different sessions. | 40-60% |

### 🔍 Assumption Tracker (3)
| Tool | Description |
|------|-------------|
| `assume` | Record an assumption with category. Surfaces hidden premises. |
| `list_assumptions` | List all assumptions with filtering by status/category. |
| `check_assumption` | Validate assumption against evidence. Tracks confirmation rate. |

### 🗺️ Mental Model Builder (6)
| Tool | Description |
|------|-------------|
| `model_add` | Add entity with role, dependencies, notes, and arbitrary properties. |
| `model_query` | Query model: "deps of X", "all", "role=X", "impact of X". |
| `model_stats` | Show entity counts, roles, most-connected files. |
| `model_map` | Visualize entity-relationship graph. |
| `model_remove` | Remove entity. Dependents auto-update. |
| `model_scan` | Scan filesystem for new entities (depth-limited, 8ms). |

### 💾 Context Preservation (3)
| Tool | Description |
|------|-------------|
| `context_preserve` | Anchor critical info with label and optional TTL. |
| `context_check` | Check decay risk of preserved items. |
| `context_estimate` | Pre-flight token usage estimation. |

### 📋 Work Tracking (4)
| Tool | Description |
|------|-------------|
| `work_start` | Start a multi-session work item. |
| `work_block` | Mark block as in_progress. |
| `work_done` | Mark block as completed. |
| `work_log` | View work history across sessions. |

### 👥 Session Management (2)
| Tool | Description |
|------|-------------|
| `session_init` | Create isolated session for multi-agent use. |
| `session_list` | List active sessions with stats + collision warnings. |

### 🧩 Pattern Memory (2)
| Tool | Description |
|------|-------------|
| `pattern_record` | Record bug pattern. Auto-saved to global store (cross-session). |
| `pattern_match` | Match patterns via Jaccard/TF-IDF. Searches local + global. |

### 📝 Decision Log (2)
| Tool | Description |
|------|-------------|
| `decision_log` | Record architecture decision with alternatives + revisit trigger. |
| `decision_list` | List decisions by category. |

### 📬 Cross-Session Communication (3)
| Tool | Description |
|------|-------------|
| `agent_message` | Send message to another agent session. Enables coordination. |
| `agent_inbox` | Read messages sent to this session. |
| `collision_check` | Detect files touched by multiple sessions (5-min window). |

### ⚡ Token-Efficient Tools (4) 🆕
| Tool | Description |
|------|-------------|
| `tool_cache` | Cache expensive results with TTL. GET/SET pattern. |
| `batch_call` | Execute multiple tools in sequence, return ONE compact output line. |
| `chain_diff` | Show only what changed between two points in a reasoning chain. |
| `thought_compress` | Compress a reasoning chain to N key thoughts (default 3). |
| `state_snapshot` | Ultra-compact system health snapshot (1 line). |

### 📋 Kanban / Niche / Task Board (11) 🆕
| Tool | Description |
|------|-------------|
| `kanban_stats` | Show kanban statistics per niche. |
| `niche_create` | Create a new cognitive niche (project/area) with color. |
| `niche_list` | List all cognitive niches. |
| `niche_update` | Update niche properties (name, desc, color, archive). |
| `task_create` | Create a new task in a niche with priority/tags/assignee. |
| `task_move` | Move a task between columns or edit fields. |
| `task_list` | List tasks with filtering by niche/status/tag/search. |
| `task_delete` | Delete a task permanently. |
| `task_link` | Link a task to cognitive objects (chain, pattern, wiki). |
| `task_link_url` | Link a URL to a task. |
| `task_search` | Search tasks across niches by title, description, tags. |

### ❓ Q&A Cognitive Artifacts (3) 🆕
| Tool | Description |
|------|-------------|
| `qa_ask` | Ask a question and store as cognitive artifact. |
| `qa_list` | List stored Q&A pairs by tags. |
| `qa_link` | Link a Q&A pair to a kanban task or reasoning chain. |

### 🌐 Web Snapshot (2) 🆕
| Tool | Description |
|------|-------------|
| `web_snapshot` | Extract web page and save as cognitive snapshot (word_count). |
| `web_snapshots_list` | List saved web snapshots. |

### 🧠 Unified Search (1) 🆕
| Tool | Description |
|------|-------------|
| `unified_search` | Search across ALL cognitive subsystems simultaneously (chains, patterns, decisions, wiki, snapshots, Q&A, model). |

### 🩺 Cognitive Integrity (1) 🆕
| Tool | Description |
|------|-------------|
| `cognitive_integrity` | Check cognitive system health: unlinked tasks, unanswered Q&A, stale decisions. Health score 0-100. |

### 📚 Wiki (4) 🆕
| Tool | Description |
|------|-------------|
| `wiki_create` | Create a wiki page with markdown content. |
| `wiki_list` | List all wiki pages with metadata. |
| `wiki_read` | Read a wiki page by title. |
| `wiki_update` | Update wiki page content.

## Quick Start

```bash
python server.py
```

## Hermes Config

```yaml
mcp_servers:
  lumen_thinking:
    command: "python"
    args: ["implementations/mcp-servers/thinking/server.py"]
    transport: lumen
    lumen_force_json_rpc: true
```

## Example Session

```
LLM: I need to plan a DB migration. Let me think step by step.

#1: "Analyze current schema — 23 tables, 4 views"
#2: "Risk: foreign keys between users↔orders"
#3: "REVISION: orders also FK to payments → add to analysis"
#4: "BRANCH: alternative approach using pg_upgrade"

→ thought_similarity("migration strategy")  → finds related thoughts
→ thought_contradiction("pg_upgrade is safe") → detects if contradicts
→ thought_summarize() → 3 themes: schema, risks, strategy
→ thought_to_plan() → actionable plan in markdown
→ thought_bridge("database migration") → connect with past sessions
```

## Performance

- **30-thought chain**: 4ms to build, 15ms to summarize
- **TF-IDF engine**: pure Python stdlib, zero dependencies
- **Wire savings**: 60-80% (highly structured thought metadata)

## Test

```bash
python test_suite.py
# → 34/34 tests passed (11 categories)
```

## Cognitive Workflow Skills

Ready-to-use composition patterns and integration guides for these tools:

| Skill | Description |
|-------|-------------|
| **[Lumen Control](../skills/lumen-control/SKILL.md)** | Dashboard, benchmarks, troubleshooting |
| **[Cognitive Workflows](../skills/lumen-cognitive-workflows/SKILL.md)** | 5 proven workflows (Problem→Plan→Execute, Decision→Validation→Learning, Scientific Debugging, Structured Learning, Multi-Session Task) |
| **[Hermes Integration](../skills/lumen-thinking-hermes-integration/SKILL.md)** | Auto-context hooks, plan bridge plugin, subagent usage |
| **[Cognitive Safety](../skills/lumen-cognitive-safety/SKILL.md)** | SAFE vs UNSAFE taxonomy, audit checklist, implementation rule |
| **[Native Server Dev](../skills/lumen-thinking-server-dev/SKILL.md)** | STREAM_DATA streaming, MUX channels, Windows-safe frame I/O |
| **[Cognitive State Sync](../skills/lumen-cognitive-state-sync/SKILL.md)** | Multi-agent shared mental models via MUX 🚀 |
| **[MCP Server](../skills/lumen-mcp-server/SKILL.md)** | Templates, architecture, benchmarking |
| **[MCP Server Pattern](../skills/lumen-mcp-server-pattern/SKILL.md)** | Proven patterns, shared_tools, security |
| **[Server Development](../skills/lumen-server-development/SKILL.md)** | Canonical guide, PROBE handshake, pitfalls |
