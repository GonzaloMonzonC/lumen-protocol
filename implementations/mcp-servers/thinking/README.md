# LUMEN Sequential Thinking Server

A structured reasoning engine for LLMs. External "notebook" that persists thoughts
outside the context window — enabling revision, branching, and analysis.

## Why this matters

LLMs think inside their context window. Context gets compressed → thoughts get lost.
Sequential Thinking keeps thoughts external — they survive compression, can be revised,
branched, clustered, and bridged across sessions.

## Tools

| Tool | Description | Wire Savings |
|------|-------------|-------------|
| `sequential_thinking` | Record thoughts, revisions, branches. Chain persists across turns. | 60-80% |
| `thought_similarity` | Find semantically similar thoughts via TF-IDF cosine similarity. | 50-70% |
| `thought_contradiction` | Detect thoughts that contradict earlier ones (sentiment-aware). | 40-60% |
| `thought_summarize` | Cluster thoughts by theme (agglomerative clustering). | 55-75% |
| `thought_to_plan` | Convert reasoning chain to actionable markdown/JSON plan. | 50-70% |
| `thought_evaluate` | Score thought quality (specificity, actionability, concreteness). | 40-60% |
| `thought_bridge` | Cross-chain: find related thoughts from different sessions. | 40-60% |

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
