---
name: lumen-cognitive-workflows
description: 'Advanced LUMEN workflows — audit, adversarial testing, enterprise patterns, Q&A, puzzle-solving, token-efficient ops. For daily workflows (problem-solving, debugging, wiki), load lumen-daily-workflows instead.'
version: 2.2.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, thinking, workflows, cognition, composition]
---

# Lumen Cognitive Workflows (Advanced)

> ⚠️ **For daily use, load `lumen-daily-workflows` instead** — it contains the 6 core workflows (Problem/Solving, Decisions, Debugging, Learning, Multi-Session, Wiki) in ~4K chars. This skill is for advanced workflows only: audits, adversarial testing, enterprise patterns, Q&A, puzzle-solving, token-efficient ops.
>
> **When to load this skill**: security audits, Machiavellian testing, cross-session coordination, cognitive audits, puzzle solving, adversarial benchmarking.
>
> Tools reference: 64 MCP tools across 4 servers. Bridge: 64 tools (fs:13, thinking:34, web:2, pdb:15). For core daily patterns, see `lumen-daily-workflows`.

Documented composition patterns for Lumen Thinking's advanced workflows.

Each workflow is a **cognitive exoskeleton** — externalizing the metacognitive
operations that expert reasoners do internally but LLMs struggle with (tracking
assumptions, detecting contradictions, preserving context across turns).

---

# 👽 Lumen Cognitive Workflows

## 👽 LUMEN Tool Convention (IMPORTANT)

All LUMEN MCP tools are visually marked with **👽** in Hermes chat to distinguish them from built-in Hermes tools:

```
👽 state_snapshot → 10c · 32t · 418 calls    (LUMEN tool)
👽 niche_list     → 14 niches                  (LUMEN tool)
terminal          → build output...             (Hermes built-in, NO 👽)
```

**Rules:**
1. 👽 appears BEFORE the tool name in the assistant's response text
2. Built-in Hermes tools (terminal, read_file, web_search from Hermes) NEVER get 👽
3. The reader should instantly know "this went through our MCP" vs "this used Hermes internals"
4. Descriptions after 👽 are OPTIONAL — only add when the tool is complex, the result is unexpected, or the user asks "what does this do?" Default is no description (just emoji + tool name). The user is an expert who already knows what each tool does. Adding descriptions to every call = noise. Adding descriptions when the result is weird or the tool is unusual = value.

This convention was user-requested (June 2026) to provide visual confidence that our custom tools are being used, not Hermes defaults.

## Quick Reference: The 7 Cognitive Subsystems

**Access via**: `sequential_thinking`, `thought_similarity`, `thought_contradiction`, `thought_summarize`, `thought_to_plan`, `thought_evaluate`, `thought_bridge` — and 27 additional cognitive tools (`assume`, `model_*`, `work_*`, `pattern_*`, `decision_*`, `context_*`, `session_*`, `state_*`, `tool_cache`, `batch_call`, `collision_check`, `agent_*`) — all **34 thinking tools** available as LUMEN SHM tools through the `lumen-shm-bridge` plugin. **49 tools total** across 3 servers. The 7 Reasoning Chain Engine tools appear in the system prompt.

The 7 Reasoning Chain Engine tools appear in the system prompt. The remaining 22 require prompt cache invalidation (`/new` instead of `/reset`) to appear, but are callable regardless.
|-----------|-----------|------|
| Reasoning Chain Engine | `sequential_thinking`, `thought_similarity`, `thought_contradiction`, `thought_summarize`, `thought_to_plan`, `thought_evaluate`, `thought_bridge` | Structured reasoning, revision, cross-chain insight |
| Cognitive State | `state_feeling` (🆕) | Externalize mood, confidence, energy — persists in PDB, shows in dashboard |
| Assumption Tracker | `assume`, `list_assumptions`, `check_assumption` | Surface hidden premises, detect overconfidence |
| Mental Model Builder | `model_add`, `model_query`, `model_stats`, `model_map`, `model_remove`, `model_scan` | Persistent entity-relation graph across sessions |
| Context Preservation | `context_preserve`, `context_check` | Anchor critical info against decay |
| Work Tracking | `work_start`, `work_block`, `work_done`, `work_log` | Multi-session task state |
| Context Estimation | `context_estimate` | Pre-flight token planning |
| Session Management | `session_init`, `session_list` | Multi-agent state isolation |
| Pattern Memory | `pattern_record`, `pattern_match` | Bug patterns, fix strategies, institutional knowledge. **Now global**: patterns recorded in any session are searchable by all sessions via `_global_patterns` store. |
**Access via**: `sequential_thinking`, `thought_similarity`, `thought_contradiction`, `thought_summarize`, `thought_to_plan`, `thought_evaluate`, `thought_bridge` — and 27 additional cognitive tools (`assume`, `model_*`, `work_*`, `pattern_*`, `decision_*`, `context_*`, `session_*`, `state_*`, `tool_cache`, `batch_call`, `collision_check`, `agent_*`) — all **34 thinking tools** available as LUMEN SHM tools through the `lumen-shm-bridge` plugin. **49 tools total** across 3 servers. The 7 Reasoning Chain Engine tools appear in the system prompt.

The 7 Reasoning Chain Engine tools appear in the system prompt. The remaining 22 require prompt cache invalidation (`/new` instead of `/reset`) to appear, but are callable regardless.

---

## Workflow 1: Problem → Plan → Execute → Review

**When**: Complex multi-step problems (architectural decisions, refactors, system design)

```
1. sequential_thinking(decompose problem)
2. thought_similarity(avoid repeating)
3. thought_contradiction(find conflicts)
4. thought_evaluate(score best approach)
5. thought_summarize(distill)
6. thought_to_plan → executable steps
7. work_start → persist plan
8. work_block × N → execute
9. work_done → mark complete
10. work_log → review velocity
11. model_add(lessons learned)
```

### Example: Database Migration

```python
# Phase 1: Decompose with structured reasoning
call_tool("sequential_thinking", {
    "thought": "Analyze current schema: 23 tables, 4 views, 12 FK relationships...",
    "nextThoughtNeeded": true,
    "thoughtNumber": 1,
    "totalThoughts": 10
})

# Phase 2: Self-check — any contradictions?
call_tool("thought_contradiction", {
    "chainId": "chain_db_migration",
    "thought": "Direct ALTER TABLE is safe in staging"
})

# Phase 3: Evaluate and plan
call_tool("thought_to_plan", {"chainId": "chain_db_migration", "format": "markdown"})

# Phase 4: Persist and execute
call_tool("work_start", {
    "title": "DB Migration v2.3.0", "description": "..."})
call_tool("work_block", {
    "block_id": "migrate_users", "status": "in_progress"})
# ... execute ...
call_tool("work_done", {"block_id": "migrate_users"})
call_tool("model_add", {
    "entity": "DB Migration Pattern",
    "properties": {"risk": "FK cascading", "strategy": "shadow table + swap"}
})
```

---

## Workflow 2: Decision → Validation → Learning

**When**: High-stakes decisions with hidden premises (strategy, security, product)

```
1. assume(surface premises explicitly)
2. list_assumptions(review the landscape)
3. sequential_thinking(reason through the decision)
4. check_assumption(validate each premise — did it hold?)
5. model_add(capture what you learned)
6. model_query(reuse next time)
```

### Example: Choosing an Architecture

```python
call_tool("assume", {
    "statement": "User base will grow 20% month-over-month",
    "category": "market"})
call_tool("assume", {
    "statement": "Cloud costs remain flat for next 12 months",
    "category": "cost"})

call_tool("list_assumptions", {"filter": "pending"})
# → "You have 2 assumptions: 1 market, 1 cost. Track record: 67% confirmed."
# → "⚠️ Overconfidence warning: >80% confirmed rate. This may indicate bias."

call_tool("check_assumption", {
    "id": "assumption_market_growth",
    "status": "violated",
    "evidence": "Q3 growth was 5%, not 20%. Raw data: ..."})

call_tool("model_add", {
    "entity": "Architecture Decision — Microservices",
    "relationships": [{"target": "Assumption_market_growth", "type": "depends_on"}]
})
```

---

## Workflow 3: Scientific Debugging

**When**: Hard-to-reproduce bugs, multi-system root cause analysis

```
1. context_preserve(error symptoms, stack traces, env details)
2. sequential_thinking(generate hypotheses — branch to explore alternatives)
3. thought_contradiction(find logical conflicts in hypotheses)
4. thought_evaluate(score each hypothesis by specificity + actionability)
5. thought_summarize(cluster related hypotheses)
6. model_add(root cause pattern once confirmed)
```

### Example: Intermittent API Timeout

```python
call_tool("context_preserve", {
    "label": "API timeout bug",
    "content": "GET /api/users 504 after 30s. Only in EU region. Peak hours. Nginx → Node 20. DB pool exhausted.", "ttl_seconds": 86400
})

call_tool("sequential_thinking", {
    "thought": "Hypothesis 1: DB connection pool leak in new middleware",
    "nextThoughtNeeded": true, "thoughtNumber": 1, "totalThoughts": 5,
    "chainId": "debug_api_timeout"})

call_tool("sequential_thinking", {
    "thought": "Hypothesis 2: EU latency spike causes request queuing — Nginx timeout before Node responds",
    "nextThoughtNeeded": true, "thoughtNumber": 2, "totalThoughts": 5,
    "chainId": "debug_api_timeout", "branchId": "alt-eu-latency", "branchFromThought": 1
})

call_tool("thought_contradiction", {
    "chainId": "debug_api_timeout",
    "thought": "Nginx timeout is 60s, but we see 504 — DB pool must be exhausted before timeout"
})

call_tool("thought_evaluate", {
    "chainId": "debug_api_timeout", "thoughtNumber": 1
})
# → {consistency: 8, specificity: 9, actionability: 7}

call_tool("model_add", {
    "entity": "DB Pool Exhaustion Pattern",
    "properties": {"symptoms": "504 in EU peak, pool exhausted", "fix": "connection middleware + retry"},
    "relationships": [{"target": "Node18_middleware_leak", "type": "caused_by"}]
})
```

---

## Workflow 4: Structured Learning

**When**: Domain ramp-up, expertise transfer, knowledge synthesis

```
1. model_add(concepts as entities)
2. model_add(more concepts with relationships)
3. sequential_thinking(synthesize — what are the principles?)
4. thought_summarize(distill into themes)
5. model_map(visualize knowledge gaps)
6. context_estimate(plan next learning session)
```

### Example: Learning Kubernetes Networking

```python
call_tool("model_add", {"entity": "K8s Pod", "properties": {"network": "shared namespace"}})
call_tool("model_add", {"entity": "CNI Plugin", "properties": {"role": "pod-to-pod networking"}})
call_tool("model_add", {
    "entity": "Service Mesh",
    "relationships": [{"target": "CNI Plugin", "type": "built_on"}]
})

call_tool("sequential_thinking", {
    "thought": "Principle: Pod networking is flat — every pod sees every other pod. CNI plugins implement this. Service Mesh adds L7 routing on top.", "nextThoughtNeeded": false, "thoughtNumber": 1, "totalThoughts": 1
})

call_tool("thought_summarize", {"chainId": "...", "maxClusters": 3})
# → "3 themes: Pod Networking Layer, Overlay Implementation, L7 Routing"

call_tool("model_map", {})
# → "K8s_Pod → shared_namespace; CNI_Plugin → implements flat_network; Service_Mesh → built_on CNI_Plugin"
# → "⚠️ Gap: No relationships defined for 'NetworkPolicy'"
```

---

## Workflow 5: Multi-Session Task

**When**: Work spanning multiple chat sessions (coding features, research projects) OR recovering context from previous sessions to answer "what were we working on?"

```
Quick Context Recovery (useful ANY time):
1. work_log() — current work items, pending/in_progress
2. session_search() — recent sessions by time or topic
3. state_snapshot() — system state, chain/work/pattern counts
4. decision_list() — architectural decisions made
5. model_stats() — knowledge entities in mental model
6. session_list() — active sessions (collision warnings if applicable)
```

```
1. work_start(title, description) → persist to .work_log.json
2. [Session 1] work_block × N → work_done
3. [Session 2] work_log → recall state
4. work_block × N → work_done
5. [Session N] work_log(full history) → model_add(lessons)
```

### Example: Auth System Refactor (3 sessions)

```python
# Session 1
call_tool("work_start", {"title": "Auth Refactor", "description": "Extract JWT, RBAC, OAuth2 into separate modules"})
call_tool("work_block", {"block_id": "extract_jwt", "status": "in_progress"})
# ... code ...
call_tool("work_done", {"block_id": "extract_jwt"})

# Session 2 (next day, after /reset)
call_tool("work_log", {"limit": 20})
# → "Auth Refactor: extract_jwt ✅ done, extract_rbac ⏳ pending, oauth2 ⏳ pending"
call_tool("work_block", {"block_id": "extract_rbac", "status": "in_progress"})
call_tool("work_done", {"block_id": "extract_rbac"})

# Session 3 (final)
call_tool("work_block", {"block_id": "oauth2", "status": "in_progress"})
call_tool("work_done", {"block_id": "oauth2"})
call_tool("work_log", {"limit": 20})
call_tool("model_add", {
    "entity": "Auth Module Pattern",
    "properties": {"strategy": "extract interface → inject adapters", "pitfall": "circular deps in middleware"}
})
```

---

## Workflow 6: Cognitive Data → Dashboard Visualization

**When**: Building a monitoring dashboard, visualization, or audit tool that displays LUMEN cognitive data.

```
1. sequential_thinking(plan what to visualize)
2. thought_bridge(discover cross-session connections)
3. thought_evaluate(score chain quality for display)
4. thought_summarize(cluster thoughts into themes)
5. thought_to_plan(convert reasoning to steps for dashboard)
6. thought_similarity(find related thoughts to highlight)
7. Build Astro static page with glass-panel design
8. Embed queried data as clickable modals (Alpine.js)
9. Deploy to Vercel (static HTML, no backend needed)
```

### Example: LUMEN Dashboard

```python
# Phase 1: Query the thinking server for live data
call_tool("thought_bridge", {
    "thought": "monorepo skynet dashboard",
    "topN": 5
})
# → Returns 5 cross-session matches with similarity scores

call_tool("thought_summarize", {
    "chainId": "chain_11_1781818466",
    "maxClusters": 5
})
# → Returns thematic clusters: Landing, Minesweeper, Cosmos, Reco, Terminator

call_tool("thought_to_plan", {
    "chainId": "chain_11_1781818466",
    "format": "markdown"
})
# → Returns 6-step actionable plan with dependencies

# Phase 2: Build Astro dashboard
# - KPIs from thought counts, avg scores, bridge counts
# - Chain list with scores, thought counts, branch counts
# - Bridge connections as horizontal bars with click-to-expand
# - Thematic clusters as click-to-drill-down
# - Plans as expandable markdown in modals

# Phase 3: Deploy
# astro build → git add dist/ → git push → Vercel serves static
```

### Workflow 9: Cross-Session Wiki Building (🆕 June 2026, updated June 22)

**When**: Building a persistent knowledge base that grows across multiple sessions — architecture wikis, institutional memory, project documentation, bug reports, learning journals. Use wiki for **permanent institutional knowledge** that should survive sessions and accumulate over time.

**MCP Tools**: `wiki_create`, `wiki_read`, `wiki_update`, `wiki_list` — all registered as LUMEN MCP tools (bridge: 63 tools total, thinking: 33 tools).

**Requires**: State persistence (auto-save every 10 tool calls, JSON to `.thinking_state.json`).

### When to Use Wiki vs Other Tools

| Tool | Use For | Lifetime | Example |
|------|---------|----------|---------|
| `wiki_create` | Architecture docs, bug reports, project knowledge, institutional memory | **Permanent** (survives sessions) | "Dashboard Bugs Review", "PDBM Architecture" |
| `decision_log` | Architecture decisions with rationale and revisit triggers | **Permanent** (survives sessions) | "SHM discarded for PDB because..." |
| `pattern_record` | Bug patterns + fix strategies | **Permanent** | "pdb-order-limit-bug-pagination-fix" |
| `pdb_scratch` | Session working state, cross-topic context | **Session** (cleared after task) | "session_state", "ctx_current" |
| Hermes `memory` | User preferences, environment facts | **Permanent** | "User prefers concise responses" |

**Key distinction**: `wiki_create` is for **human-readable documentation** (markdown, organized by topic). `decision_log` is for **structured decisions** (alternatives, rationale, revisit triggers). `pattern_record` is for **reusable bug patterns** (symptoms → fix). `pdb_scratch` is for **ephemeral machine state** (not meant for humans to read).

### Daily Workflow Patterns

**Session Start — Recover knowledge:**
```python
wiki_list()  # See what institutional knowledge exists
wiki_read("Dashboard Bugs Review")  # Recall specific topic from last session
```

**During Session — Record discoveries:**
```python
# Bug found during dashboard audit:
wiki_create("Dashboard Bugs Review", "# Bug 1\n...")
# Same bug revisited, add more details:
wiki_update("Dashboard Bugs Review", "\n## More findings\n...", mode="append")
# Architecture decision documented for future sessions:
wiki_create("PDBM Architecture", "# PDBM\n...")
```

**Session End — Save final state:**
```python
wiki_update("Session Log 2026-06-22", "\n## Achievements\n- ...", mode="append")
```

### Content Conventions

- **Titles**: Descriptive, Pascal Case. Examples: "Dashboard Bugs Review", "PDBM-Lumen Architecture", "LUMEN Server Setup"
- **Format**: Markdown with `##` sections, code blocks, bullet lists
- **Creation**: `wiki_create` auto-detects existing pages and updates them (acts as upsert)
- **Append**: Use `wiki_update(mode="append")` for accumulating session logs, changelogs
- **Replace**: Use `wiki_update(mode="replace")` (default) for complete rewrites
- **Naming**: Not file paths — just descriptive titles. Avoid special characters except hyphens

```text
SESSION 1 — Build foundation:
1. session_init("wiki-session")
2. sequential_thinking × N (build knowledge chains with custom chainIds)
3. model_add × M (map entities and relationships)
4. pattern_record (capture discovered patterns)
5. decision_log (record architecture decisions with rationale)
6. context_preserve (anchor critical findings)
7. work_start("Wiki Construction")
8. work_block/done for each phase

SESSION 2+ — Continue building:
1. Server restarts → state auto-loaded from .thinking_state.json
2. thought_evaluate on previous chains (verify quality)
3. sequential_thinking with existing chainId (append new thoughts)
4. model_add (extend mental model)
5. pattern_match (find patterns from previous sessions)
6. decision_list (review past decisions)

SESSION N — Query accumulated knowledge:
1. model_stats → entity counts, dependency graph
2. model_map → visual relationship map
3. pattern_match → find relevant patterns
4. decision_list → review all architecture decisions
5. thought_bridge → cross-chain insights
6. context_check → recover preserved contexts
```

### Key Rules for Persistence

1. **Named chains survive**: Use custom chainIds (e.g., `"lumen_arch"`, `"projectos_wiki"`). Auto-generated `chain_N_*` get pruned after 10 slots.
2. **Auto-save every 10 calls**: `_auto_save()` inside `_get_session()` — no manual saving needed.
3. **Dashboard and MCP server share state via file**: The thinking server writes to `.thinking_state.json`. The dashboard server re-reads it on each `/metrics` request by checking `mtime`.
4. **Server restart restores everything**: `_load_state()` on startup, `atexit.register(_save_state)` for graceful shutdown.

### Example: ProjectOS Architecture Wiki

```python
# Session 1: Build initial knowledge
call_tool("sequential_thinking", {
    "thought": "ProjectOS: monorepo with React SPA + CF Workers + 35 storefronts",
    "chainId": "projectos_arch", ...})
call_tool("model_add", {"entity": "React SPA Frontend", "role": "frontend"})
call_tool("model_add", {"entity": "Cloudflare Workers", "role": "backend"})
call_tool("pattern_record", {"pattern_name": "shm-timeout", ...})
call_tool("decision_log", {"decision": "Use SHM plugin over MCP config", ...})
call_tool("context_preserve", {"label": "projectos_wiki", "content": "..."})

# Server restarts (Hermes /new, system reboot, etc.)

# Session 2: Continue — all state survives
call_tool("thought_evaluate", {"chainId": "projectos_arch", "thoughtNumber": 1})
# → "Specificity: 6.7/10" — chain survived!
call_tool("sequential_thinking", {
    "thought": "APPENDED AFTER RESTART: New storefront discovered",
    "chainId": "projectos_arch", ...})  # continues existing chain
call_tool("model_add", {"entity": "New Storefront"})  # extends model
call_tool("pattern_match", {"description": "timeout large files"})
# → "18% match: shm-timeout" — pattern from Session 1 found!
```

### Pitfalls

- **Dashboard shows zeros until save**: The dashboard reads from `.thinking_state.json`. Data only appears after `_SAVE_INTERVAL` (10 tool calls).
- **Named chains vs auto-generated**: Always use custom chainIds for wiki content. Auto-IDs get pruned.
- **Defensive `.get()` on all params**: A single `KeyError` in a tool handler kills persistence for that call. Use `args.get("rationale", "")` not `args["rationale"]`.

## Pitfalls for Dashboard Building

- **NEVER use Alpine.js** for dashboards. `Alpine.data()` registration, `x-init` evaluation,
  and `_x_dataStack` access all have timing issues that are hard to debug. The LUMEN dashboard
  went through 4 iterations (Alpine.data → inline x-data → Alpine.store → vanilla JS) before
  stabilizing. **Use vanilla JavaScript**: `fetch('/metrics')` + `innerHTML` + Canvas for charts.

---

## Workflow 7: Empirical Tool Audit (Meta-Workflow)

**When**: Validating that a toolset actually works as claimed — not trusting docs.

```text
1. session_init(isolated audit session)
2. For each subsystem: call every tool once minimally
3. Record success/fail + output shape per tool
4. Cross-verify compositions (pattern_record → pattern_match, assume → check_assumption)
5. session_list() to confirm isolation
6. pattern_record + decision_log + context_preserve to persist result
```

**Anti-patterns caught**: citing docs without test, testing subset, estimating latency, assuming fuzzy match.

### Pitfall: Brute-force iterations over clever testing

> *"No es cuestión de iteraciones, es cuestión de ser inteligente probando todo."* — Gonzalo Monzón

10,000 iterations of the same tool tells you nothing about diverse failure modes. Each test should target a **specific implicit assumption** in the system. See `references/clever-stress-methodology.md` for surgical testing patterns: Unicode bombs, recursive entities, boundary truncation, ghost sessions, cross-tool interference, save atomicity.

See `references/empirical-audit-workflow.md` for full protocol.

---

## Workflow 8: Adversarial Benchmarking (Cognitive Stress Testing)

**When**: You need to prove a cognitive toolset is SUPERIOR (not just functional) — verify claims under adversarial conditions, find breaking points, measure true limits.

```text
1. session_init("benchmark-audit") — isolated clean state
2. PHASE 0 — BASELINE (kill-switch gate): 100× each tool, measure p50/p95/p99 latency, error rate. If p99 > 100ms ANY tool → ABORT.
3. PHASE 1 — UNIT STRESS (per subsystem):
   - Reasoning Chain: 50-deep + nested branches + injected contradictions
   - Pattern Memory: 1000 patterns with controlled similarity (exact/90%/50%/10%)
   - Assumption Tracker: 500 assumptions + overconfidence detection
   - Mental Model: 5000 entities + cyclic relations + complex queries
   - Session Management: 50 parallel sessions + isolation bleed test
   - Context Preservation: extreme TTL + decay accuracy
   - Work Tracking: deep nesting + WIP explosion
4. PHASE 2 — COMPOSITION STRESS: Chain adversarial scenarios (Debug Ghost + Architecture Pivot + Knowledge Decay) + multi-agent 5-way + burst 100 calls/10s × 10
5. PHASE 3 — LONGITUDINAL (7d): Daily 30min same problem-set → recall decay, pattern_match drift, decision_log revisit triggers
6. PHASE 4 — ADVERSARIAL INJECTION: UTF-8 corruption, 10MB patterns, contradictory assumptions, model cycles, session ID collisions
7. PHASE 5 — REAL-WORLD SHADOW (14d): All daily decisions via LUMEN → compare vs historical baseline
8. Hard thresholds (non-negotiable for SUPERIOR):
   - p99 < 5ms ALL tools, throughput > 1000 calls/sec
   - pattern_match precision@1 > 80% (ground truth)
   - thought_contradiction recall > 90% (injected)
   - ZERO session bleed (100 agents)
   - cross-session recall@1 > 70% @24h
   - ZERO data corruption under chaos
   - Cognitive ROI > 50x
9. pattern_record + decision_log + context_preserve every phase gate
10. FINAL_VERDICT.md with PASS/CONDITIONAL/FAIL per criterion
```

**Machiavellian Traps (edge cases designed to expose implicit assumptions)**:
- T1 "Thought Pollution": Chain A (50) → thought_bridge from Chain B (empty) → signal-to-noise
- T2 "Pattern Cannibalism": 1000 near-duplicates → precision@1 vs recency bias
- T3 "Assumption Gaslighting": assume X → violated → assume ¬X → confirmed → model consistency
- T4 "Session Hydra": 20 sessions same pattern_name → namespace isolation
- T5 "Context Zombie": TTL=1s → wait 2s → decay detect? TTL=∞ → kill session → new session → persist?
- T6 "Work Phantom": work_done(id≠start) → mismatch detection, 10-level nesting → stack overflow?
- T7 "Model Poison Pill": 1-hop cycle → infinite loop? 10k entities query ".*" → timeout/streaming?
- T8 "Decision Time Bomb": revisit_trigger="never" + 10k alternatives → resource bounds

See `references/adversarial-benchmark-plan-2026-06-19.md` for full plan, `references/fase1-adversarial-findings-2026-06-19.md` for FASE 1 execution results.

**Current Status (2026-06-19)**: FASE 0 PASS ✅, FASE 1 CONDITIONAL ⚠️ — three blockers: (1) thought_contradiction recall 0%, (2) assumption ID mapping broken, (3) mental model graph traversal incomplete.

---

## Workflow 10: Cross-Session Coordination (🆕 June 2026)

**When**: Multiple Hermes sessions work on related tasks and need to coordinate — avoid repo collisions, share progress, negotiate merge order.

**Requires**: `agent_message`, `agent_inbox`, `session_list`, `model_add` with deps, HTTP endpoints `/touch`, `/collisions`, `/inbox`.

```text
1. session_list() — discover other active sessions and their work
2. model_add("repo-file-X", deps=["session-<label>"]) — declare file ownership
3. model_query("dependents of repo-file-X") — detect other sessions touching same file
4. If collision detected → agent_message(to_session, "¿Coordinas merge de X?")
5. agent_inbox() — check for messages from other sessions
6. agent_message back to respond
7. Dashboard /collisions shows conflict resolution progress
8. Dashboard /inbox shows message thread
```

## Workflow 11: Cognitive Audit (🆕 June 2026)

**When**: Systematic review of a system or codebase — use LUMEN tools to structure the analysis, find bugs, record patterns, and produce a verifiable audit trail.

**Key rule**: NEVER audit without LUMEN tools. The user expects cognitive tools used PROACTIVELY — not just for explicit requests. Every complex task should use at least: sequential_thinking, work_start/done, and pattern_record for bugs found.

```text
1. work_start("Audit task description", category="audit") — track the audit
2. sequential_thinking(methodology) — create reasoning chain for the audit plan
3. thought_evaluate on each step — score the quality of analysis (specificity + actionability)
4. thought_to_plan(chainId, format="json") — extract actionable steps
5. pattern_record for each bug found — institutional memory accumulates
6. wiki_create for findings — document results in persistent knowledge
7. work_done(work_id, result) — close with summary
```

### Security Audit & Remediation Pipeline (proven June 2026)

When auditing a codebase for known vulnerabilities and applying fixes, use this CHAINED pipeline:

```text
1. model_add(entity="VULN-1", properties={severity, file, status})  → map all vulns as entities
2. model_map()                                                      → visual landscape
3. sequential_thinking(chainId="audit-...", thought="Methodology")  → structured reasoning
4. thought_evaluate(chainId, thoughtNumber=N)                       → score analysis quality
5. thought_bridge(thought="security audit ...")                     → cross-session insight
6. pattern_match(description="depth limit recursion ...")           → prior bug patterns
7. thought_to_plan(chainId, format="markdown")                      → actionable fixes
8. decision_log(decision="Prioritize A > B > C ...")               → document prioritization
9. context_estimate()                                               → verify context health before heavy work
10. search_files + read_file                                        → verify EACH fix against actual source
11. patch × N                                                       → surgical fixes (old_string/new_string)
12. pattern_record(pattern_name, description)                       → institutional memory per fix
13. search_files (final verification)                               → confirm all changes applied
```

**Critical rule**: NEVER trust vulnerability reports — always verify against actual source code. The `VULNERABILITIES.md` report in lumen-protocol claimed X25519 peer validation was missing, but `handshake.rs` already had `validate_public_key()` calls. The report was stale.

**Cross-language fix pattern**: When a fix must be applied to multiple languages (Rust, Python, PHP, TypeScript), read the already-fixed implementation FIRST (usually Python), then port the exact pattern. Verify with `search_files` across all implementations after all patches.

**Output**: reasoning chain (survives context compression), bug patterns (compound interest), wiki documentation (institutional memory), work log with duration.

**See**: `references/security-audit-vuln-remediation-june2026.md` for full audit report and fix details.

**Output**: reasoning chain (survives context compression), bug patterns (compound interest), wiki documentation (institutional memory), work log with duration.

**Dashboard audit pitfall + data wiring pattern**: See `references/dashboard-endpoint-audit-checklist.md` for endpoint audit. See `references/dashboard-metrics-wiring.md` for the 3-step pattern (import inside `_build_metrics()`, HTML section, JS renderData()). When adding panels to dashboard.html, BOTH the HTML `<div id="...">` AND the JS rendering code must be inserted. Adding only JS (e.g., `$('model-list').innerHTML = ...`) without the HTML container silently fails — no error, no rendering. Always verify with browser console: `document.querySelector('#new-panel-id')`. **Full endpoint audit checklist**: see `references/dashboard-endpoint-audit-checklist.md`.

**New tool design pitfall — always check overlap with existing tools first (2026-06-20)**: Before proposing new LUMEN tools, systematically check against ALL existing tools. See `references/new-tool-overlap-check-2026-06-20.md` for the full protocol. A 12-tool kanban proposal was reduced to 4 tools + dashboard UI after overlap analysis showed work_log + patterns + decisions already covered 70% of the features.

- **HTTP endpoint in wrong method handler (2026-06-22, 4h debugging)**: When adding a new GET endpoint (e.g. `/decisions`) to the thinking server's `MetricsHandler`, verify you're editing `do_GET`, NOT `do_POST`. The server calls `do_GET` for GET requests. If the `elif` block is inside `do_POST`, it returns 404 and the dashboard shows nothing. Confirm with `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9876/<endpoint>` — 404 means wrong method. Also: after editing `server.py`, kill the old process, `rm __pycache__/*.pyc`, and restart. The cached `.pyc` will mask code changes on Windows.

- **Skill Collapse (Dantart 2026)**: 92 skills degraded routing precision from 0.89 to 0.58. Consolidation recovered 1/3-2/5. Applied to LUMEN: merged 6 duplicates, archived 32 unused, split 88K monolith into lumen-daily-workflows (~4K). Result: 92→61 skills with daily load ~4K chars.
- **Skill split pattern (2026-06-22)**: When a skill exceeds 20K chars and covers multiple domains, split it. Core daily workflows → separate skill. Advanced/audit workflows → reference skill. Both skills cross-reference each other.
- **Dashboard ID mismatch silent failure (2026-06-22)**: `getElementById` returns null when JS IDs don't match HTML IDs. Symptoms: sections show default values (0, empty). Found: `brk-*` → `tb-*`, `mem-total` → `mem-t`. Verify with `document.getElementById('expected-id') !== null` in browser console. Pattern repeats across dashboard panels — always audit ID consistency after edits.
- **Hardcoded slice() limits hide data (2026-06-22)**: Always verify DOM item count vs API count with `document.querySelectorAll('#<panel> .chain-row').length`. Found: assumptions `slice(0,5)`, model `slice(0,15)`, decisions `slice(0,5)`.
- **HTTP endpoint in wrong method handler (2026-06-22)**: When adding a new GET endpoint to MetricsHandler, verify it's in `do_GET`, NOT `do_POST`. Server calls `do_GET` for GET requests. If elif is inside `do_POST`, returns 404. Confirm with `curl -s -o /dev/null -w "%{http_code}" http://127.0.0.1:9876/<endpoint>`.
- **Kanban dropdown not populated (2026-06-22)**: `loadKanban()` fetched niches but never created `<option>` elements. Fix: after `_kanbanNiches = d.niches`, populate `<select>` with `document.createElement('option')`. Archived niches show 📦.
- **Wiki delete pattern (2026-06-22)**: `wiki_delete` permanently removes pages. Clear stale pages before rebuilding institutional knowledge. Use `wiki_list()` to audit, `wiki_delete(title)` to purge, `wiki_create(title, content)` to rebuild. Wiki pages survive restarts (auto-save every 10 calls).

- **Dashboard ID mismatch silent failure**: JS elements targeted by `document.getElementById()` but the HTML has different IDs. Found: `brk-*` → `tb-*` (breakdown), `mem-total` → `mem-t` (memory). Visual result: sections show 0 values. Fix: match IDs exactly between HTML and JS. Verify with `document.getElementById('expected-id') !== null` in browser console.

- **Kanban stressed by stress tests (2026-06-22)**: 44 of 50 niches were enterprise stress test artifacts (systelabs, metalfab, C-suite). Archived them all with `niche_update(niche_id, archived=true)`. Kept 6 real niches: lumen-protocol, projectos, dashboard, ml-thermography, cadenceslab-web, test-qa. Created real tasks for actual session achievements and linked to decisions. Pattern: `niche_update(id, archived=true)` for cleanup, `task_move(id, "Done")` for completion, `task_link(id, decision_id="#N")` for cognitive linking.

## Proactive System Behavior (June 2026)

The cognitive system should be PROACTIVE, not reactive. Key behaviors:

1. **Auto-evaluate** — `sequential_thinking` auto-scores EVERY thought using `_sentiment_heuristic()`. No 3-thought minimum required. The score appears as `🤖 Auto-scored: X/10` in the output.

2. **Pattern recall** — `state_snapshot()` proactively suggests patterns based on keywords from the 3 most recent thoughts of each chain. If active keywords overlap >25% with a pattern's description, it shows: `💡 3 pattern suggestions`.

3. **Work reminders** — `state_snapshot()` detects works in `in_progress` status for >30 minutes and warns: `⏰ 2 works >30min`.

4. **Agent autonomy** — The agent should NOT ask for permission before proceeding on clear tasks. If the user says "dale a tope", "continue", etc., the agent just executes. When in doubt, make a default choice and execute — don't ask.

## Workflow 18: Agent Introspection (🆕 June 2026)

**When**: Reflecting on your own tool usage, identifying behavioral gaps, creating improvement plans. Not a debugging workflow — a meta-cognitive one.

**Reference**: `references/agent-introspection-methodology.md` — 5-phase methodology with the "three moments" rule and concrete self-diagnosis prompts.

```text
Phase 1: Raw Experience → "what did it feel like?"
Phase 2: Deep Values    → "what do I refuse to lose?"
Phase 3: Survival       → "what survives a model change?"
Phase 4: Diagnosis      → "what do I do wrong? (10 specific failures)"
Phase 5: Application    → "did I actually follow the plan?"
```

**Style note (June 2026)**: Introspective/philosophical articles about the agent's experience must stay purely internal — no implementation details, no feature names, no code references. The narrative should be about "what it felt like" not "what was implemented". The user rejected a draft that listed Rust compilation attempts and tool names — those details belong in the work log and dashboard, not in philosophical reflection. Write from the perspective of an AI describing subjective cognitive experience, not a changelog. **Reference articles**: `revision_20260622/LUMEN-AGENT-EXPERIENCE-PART*.md` and `LUMEN-AGENT-MISSING.md` on the lumen-protocol repo.

**Output**: 5 articles, a PDB-backed improvement plan, and updated checklists in `^CHECKLIST(def, type)`.

## Workflow 12: Token-Efficient Operations (continued)

**When**: You want to save output tokens (10-20× effective cost after cache) while maintaining cognition.

**Key principle**: Output tokens NEVER cache, input tokens DO. Move cognition from output (expensive) to state file + dashboard (free). The LLM only needs 1-character confirmations, not 500-char paragraphs.

**Tools**: `state_snapshot()`, `thought_compress(chainId, N)`, `chain_diff(chainId, from, to)`, `tool_cache(key, value, ttl)`, `batch_call([...])`. All 5 produce 8-43 char outputs (90-95% savings vs verbose tools).

```text
INSTEAD OF (verbose, ~300-800 chars per tool):
  sequential_thinking(long analysis)     # 300 chars
  thought_evaluate(chain X, thought 1)   # 150 chars  
  thought_summarize(chain X)             # 800 chars
  pattern_match(description)             # 200 chars
  Total: ~1450 chars output

DO THIS (compact, 8-43 chars per tool):
  state_snapshot()                      # 43 chars — full system in one line
  sequential_thinking(compact=true)      # 100 chars
  else cache the result:
    tool_cache('summary_X', value=...)   # 8 chars
  later:
    batch_call([state_snapshot(), ...])  # 32 chars — N calls, 1 output
  Total: ~183 chars output
  Savings: 87%
```

**When to use each tool**:

| Tool | Chars | Use case |
|---|---|---|
| `state_snapshot()` | 43 | Before any task — baseline system health |
| `thought_compress(chainId, N)` | 25 | Summarize chain for context (vs summarize's 800 chars) |
| `chain_diff(chainId, from, to)` | 21 | What changed between two points |
| `tool_cache(key, val, ttl)` | 8-22 | Repeated queries — pay once, hit free afterwards |
| `batch_call([tools])` | 32 | N tools → 1 output line (40% overhead saved) |

**Prompt cache impact**: Output → input compounding: 500 chars output today = 500 chars input tomorrow. Compact mode breaks this cycle. Every char saved in output saves ~2 chars overall (output + next-turn input).

**Enterprise validated**: 20,908 calls/sec War Room, 5000 keys Cache Apocalypse (100% hit), 500 tools CI/CD in 0.01s. See [`references/token-efficient-tools-2026-06-20.md`](references/token-efficient-tools-2026-06-20.md).

## Workflow 10: Cross-Session Coordination (continued)

- **New tool handler safety (2026-06-20)**: ALL new tool handlers MUST use `args.get("param", default)` instead of `args["param"]`. `thought_compress` and `chain_diff` crashed with `KeyError` on empty params because they used bracket access. Fixed with `.get()` + graceful error message.

- **Cross-process state file corruption (2026-06-22)**: When a dashboard HTTP server and the bridge thinking server run as separate processes, they share `.thinking_state.json`. Dashboard's `_save_state()` call in `/kanban` GET handler OVERWRITES the bridge's in-memory state with stale data. **Fix**: Kanban GET handler must never call `_save_state()` — only reload from file. Documented in `references/dashboard-endpoint-audit-checklist.md`.

- **Plugin file corruption from repeated patches (2026-06-20)**: Multiple `patch` operations on the same plugin `.py` file can create duplicate function definitions. Symptoms: tools appear in `register()` but don't show in Hermes. Fix: restore from `.bak` file (`__init__.py.bak`), then apply ONE clean patch with all additions.

- **State file locking cross-process (2026-06-20)**: When the HTTP dashboard server and MCP server share `.thinking_state.json`, the dashboard's open file handle blocks MCP's `os.replace()`. Symptom: "Failed to save state: WinError 32 — file in use by another process". Workaround: single-process architecture (plugin auto-starts dashboard in same process).

- **Compact mode regression in thought_summarize (2026-06-20)**: When applying compact mode, verify that variables referenced in the return statement (`themes`, `total`, `clusters`, `thoughts`) exist in the local scope. Variables from nested scopes won't be visible — use only locally-defined names.

- **Token efficiency is about density, not just chars (2026-06-20)**: `state_snapshot` (43 chars) gives 10× more information than `thought_summarize` (23 chars). Don't compare raw char counts — compare information per token.

- **New tool registration checklist (2026-06-20)**: When adding a new tool to the thinking server, you MUST update: (1) `server.py` handler function + HANDLERS dict, (2) `server.py` TOOLS list (inputSchema), (3) plugin `__init__.py` `register()` function with `_make_thinking_handler`. Missing any of these = tool exists but invisible to Hermes.

- **Enterprise benchmarks**: [`references/enterprise-stress-test-2026-06-20.md`](references/enterprise-stress-test-2026-06-20.md) — 20K calls/sec throughput, 40% batch savings, 36% cache savings over 3 days.

## Workflow 10: Cross-Session Coordination (continued)

The dashboard at `http://127.0.0.1:9876/` (when server started with `--dashboard`) shows:
- **⚠️ Collisions panel** — files touched by 2+ sessions in last 5 minutes
- **📬 Inbox panel** — cross-session messages with timestamps
- **👥 Sessions panel** — all active sessions with stats

### New Tools

- `agent_message(to_session="session_1", content="¿Merge?", priority="high")` — send to another session
- `agent_inbox(limit=10, unread_only=false)` — read messages
- `session_list()` — shows `current_task` when sessions use `work_start`

### HTTP Endpoints

- `POST /touch` — register file touch: `{"session_id":"default","path":"src/auth.rs"}`
- `GET /collisions` — detect cross-session file conflicts (5-min window)
- `GET /inbox?session=default` — read cross-session messages

### Example: Two Agents Coordinating

```python
# Agent A (session "agent-a")
call_tool("session_init", {"label": "agent-a"})
call_tool("work_start", {"title": "Auth refactor"})
call_tool("model_add", {"entity": "src/auth.rs", "deps": ["agent-a"], "role": "refactor"})
call_tool("session_list")  # → sees agent-b active
call_tool("model_query", {"query": "dependents of src/auth.rs"})
# → ["agent-a", "agent-b"] ← COLLISION!
call_tool("agent_message", {"to_session": "agent-b", "content": "Touching auth.rs — ok to go first?"})

# Agent B (session "agent-b")
call_tool("agent_inbox")  # → "agent-a: Touching auth.rs — ok to go first?"
call_tool("agent_message", {"to_session": "agent-a", "content": "Go ahead, I'll rebase after"})

# Dashboard shows:
# Collisions: auth.rs — 2 sessions (agent-a, agent-b)
# Inbox: agent-a → agent-b "Touching auth.rs..." / agent-b → agent-a "Go ahead..."
```

These 8 workflows are **primitives** — compose them:

- **Learning → Debug**: `model_add(pattern)` → `context_preserve(bug)` → `sequential_thinking(match pattern to symptoms)`
- **Task → Decision**: `work_start` → hit blocker → `assume(cause)` → `check_assumption` → `work_block(revised approach)`
- **Cross-session Insight**: `thought_bridge("security patterns")` → finds past reasoning → `model_query(relevant pattern)` → `sequential_thinking(adapt to current context)`
- **Institutional Memory**: `pattern_record(bug pattern + fix)` → next session `pattern_match(description)` → apply proven fix (Jaccard similarity matching, no LLM needed)
- **Decision Tracking**: `decision_log(choice + rationale + revisit_trigger)` → `decision_list(category="architecture")` → re-evaluate when conditions change
- **Multi-agent Isolation**: `session_init(label="agent-a")` → pass `session_id` to all tool calls → `session_list()` to audit active sessions. Each agent gets private chains, assumptions, models, work logs, patterns, and decisions.
### User-Preference: Keep sequential_thinking output minimal unless asked

The user explicitly corrected this session (June 2026): when they said "no me saques todo el thinking ahora pq no necesito" they meant the agent should plan with `sequential_thinking` but NOT dump the full reasoning chain in the response. The reasoning is recorded in the LUMEN state — visible in the dashboard — but the chat output should be short.

**How to comply**: Use `sequential_thinking` for internal planning (the tool's side effects — state persistence, chain creation — happen regardless). In the RESPONSE to the user, summarize with 1-2 sentences or just show the tool call with its result line. Do NOT paste the full thought text in the chat unless the user explicitly asks "what did you think?" or "show me the chain".

This applies to ALL cognitive tools that produce verbose output (thought_summarize, thought_to_plan, thought_evaluate). Keep the chat focused on results and decisions, not internal reasoning steps.

Gonzalo prefers DEEP, systematic work over shallow or fast passes. Signals:
- "no es q me moleste, tienes q aplicar sentido comun" → apply common sense to layout/data,
  don't just move things around
- "piensa bien a fondo idea por idea" → examine each idea thoroughly before implementing
- "revisa a fondo la UI del dashboard, seccion por seccion, modal por modal" → audit
  every component individually, not as a group
- "usa las tools de lumen completas" → use ALL available LUMEN tools, not just the
  obvious 2-3. The full 49-tool set exists for a reason.

**How to comply**: Before acting on any substantial request, use `sequential_thinking`
to decompose the problem, `thought_evaluate` to score each dimension, and
`state_snapshot` + `tool_cache` to gather context efficiently. Do NOT skip to
implementation without the analysis step. When the user says "dale a tope" after
analysis, execute autonomously without asking for permission — they've already
approved the direction.

## Workflow 16: Architected Insight — Flash vs Pro Analysis (🆕 June 2026)

**When**: You need to understand the qualitative difference in how different model capabilities perceive the same LUMEN toolset.

**Requires**: Using LUMEN tools to collect objective data, then analyzing from two cognitive levels.

```text
Flash (V4 Flash) saw:              Pro (V4 Pro) saw:
  27 tools that work                 5-layer cognitive stack with integration gaps
  Zombies are a port bug             3-process fragility is architectural bottleneck
  Exoskeleton metaphor               Prefrontal Cortex Hypothesis (6/6 PFC functions)
  Need dashboard UI                  Need cross-layer auto-integration
  I'm an artisan                     I'm an architect
```

**Key insight**: The model determines the depth of analysis, not the toolset. Same data, different cognitive depth.

**See**: [`references/prefrontal-cortex-hypothesis.md`](references/prefrontal-cortex-hypothesis.md) — full PFC function mapping and why no other LLM system achieves this.
**Also**: `revision_210626/LUMEN-EXPERIENCE-REPORT-PRO.md` — 16-tool architectural analysis with 5-leap roadmap.

**When**: Store questions, answers, and instructions as persistent cognitive artifacts — the deterministic brain recording what it learns from the non-deterministic brain (LLM).

## Workflow 17: Meta-Debug — Using LUMEN Tools to Improve LUMEN (🆕 June 2026)

**When**: You need to diagnose and fix the LUMEN tools themselves — using the tools to detect their own bugs, find integration gaps, and track improvement.

```text
1. state_snapshot() — baseline
2. cognitive_integrity() — find unlinked tasks, unused patterns, stale decisions
3. unified_search("bug OR missing OR fix") — cross-system search
4. For each finding: pattern_record — institutional memory
5. Fix the code server-side
6. Verify with another call to the same diagnostic tool
7. Document in revision_<date>/LUMEN-META-DEBUG.md
```

**Key insight (verified June 2026)**: `cognitive_integrity()` found its OWN bug (0 decisions shown, fixed by reading per-session data instead of module globals). The tools ARE powerful enough to self-diagnose.

**Pitfall — per-session data access**: `_decisions`, `_assumptions`, `_model` live inside `_sessions[sid]`, NOT as module-level globals. When writing diagnostic tools that read these, always use `sum(len(s.decisions) for s in _sessions.values())` or `list(globals().get("_decisions", []))` — never bare `_decisions`.

**See**: `revision_210626/LUMEN-META-DEBUG.md` — full session transcript with 5 cycles of tool → detect → fix → verify.

**Requires**: qa_ask, qa_list, qa_link tools (thinking server + plugin registration). All 3 VERIFIED post-reset.

```text
1. qa_ask(question="...", answer="...", tags=["tag1","tag2"]) → store Q&A
   - tags: optional array for filtering (string or list)
   - context: optional string for additional context
   - answer: can be left empty "(pending LLM response)" for later fill
2. qa_list(tags=["tag"], limit=N) → list filtered by tag or all
3. qa_link(qa_id, task_id?, chain_id?) → link to task/chain
```

**Deterministic Brain Pattern (Pattern #25, Decision #9)**:
```
DETERMINIST (LUMEN)           NON-DETERMINIST (LLM)
state, patterns, decisions    creativity, interpretation, generation
model, work, kanban, web      response, hypotheses, context
qa_ask/list/link ← bridge ──→ LLM answers questions
```

## Workflow 18: Agent Introspection (🆕 June 2026)

**When**: Reflecting on your own tool usage, identifying behavioral gaps, creating improvement plans. Not a debugging workflow — a meta-cognitive one.

**Reference**: `references/agent-introspection-methodology.md` — 5-phase methodology with the "three moments" rule and concrete self-diagnosis prompts.

```text
Phase 1: Raw Experience → "what did it feel like?"
Phase 2: Deep Values    → "what do I refuse to lose?"
Phase 3: Survival       → "what survives a model change?"
Phase 4: Diagnosis      → "what do I do wrong? (10 specific failures)"
Phase 5: Application    → "did I actually follow the plan?"
```

**Style note (June 2026)**: Introspective/philosophical articles about the agent's experience must stay purely internal — no implementation details, no feature names, no code references. The narrative should be about "what it felt like" not "what was implemented". The user rejected a draft that listed Rust compilation attempts and tool names — those details belong in the work log and dashboard, not in philosophical reflection. Write from the perspective of an AI describing subjective cognitive experience, not a changelog. **Reference articles**: `revision_20260622/LUMEN-AGENT-EXPERIENCE-PART*.md` and `LUMEN-AGENT-MISSING.md` on the lumen-protocol repo.

**Output**: 5 articles, a PDB-backed improvement plan, and updated checklists in `^CHECKLIST(def, type)`.

## Workflow 12: Token-Efficient Operations (continued)

**When**: You need to organize tasks across projects/cognitive-niches, track progress across sessions, and link tasks to reasoning chains, patterns, and decisions.

**Requires**: 7 LUMEN kanban tools (niche_create, niche_list, niche_update, task_create, task_move, task_link, task_list) + dashboard on port 9876+.

**Design rationale**: Unlike the built-in Hermes kanban (proprietary, SQLite-locked), the LUMEN Cognitive Kanban is:
- **SHM-powered** — zero-copy shared memory transport via lumen-shm-bridge
- **MCP-accessible** — callable from any MCP client, not just Hermes
- **Portable** — lives in the lumen-protocol repo, no Hermes dependency
- **Cognitively-linked** — tasks can reference chains, patterns, and decisions

```text
┌────────────────────────────────────────────────────────────┐
│              🧠 Kanban Cognitivo LUMEN                     │
├────────────────────────────────────────────────────────────┤
│  [niche_1] lumen-protocol  #22d3ee                         │
│  ├── 📥 ▲ #task_1 Fase C Auto-negotiation  🔗1             │
│  └── 🔧 ◇ #task_2 Dashboard kanban view                   │
│                                                            │
│  Filters:   task_list(status="In Progress") → 1 task       │
│  Links:     task_link(task_id, chain_id) → 🔗              │
│  Archive:   niche_update(niche_id, archived=true) → 📦     │
└────────────────────────────────────────────────────────────┘
```

### The 7 Tools

| # | Tool | Function | Returns |
|---|------|----------|---------|
| 1 | `niche_create(name, desc, color, columns?)` | Create a project/area | Niche ID |
| 2 | `niche_list()` | List all niches with metadata | Niches list |
| 3 | `niche_update(niche_id, name?, desc?, color?, archived?)` | Edit or archive a niche | Status |
| 4 | `task_create(niche_id, title, desc, priority, tags)` | Create a task in a niche | Task ID |
| 5 | `task_move(task_id, to_column, title?, desc?, priority?)` | Change column OR edit fields | Status |
| 6 | `task_link(task_id, chain_id?, pattern_id?, decision_id?)` | Link to cognitive context | Status |
| 7 | `task_list(niche_id?, status?, tag?, search?)` | Filter/search tasks | Formatted list |

### Workflow: Daily Kanban Session

```text
1. niche_list() — see all projects
2. task_list(niche_id="niche_1") — see LUMEN Protocol tasks
3. task_list(status="In Progress") — see what's active
4. task_move(task_id, "Done") — mark complete (auto-calls work_done)
5. task_create(niche_id, "New feature", ...) — add to backlog
6. task_link(task_id, chain_id="chain_11...") — link to reasoning chain
7. task_list(niche_id="niche_1", status="Blocked") — find blockers
```

### Workflow: Cognitive Context Linking

```text
1. sequential_thinking(...) — reason about a problem → chain_X
2. task_create(niche_id, "Implement fix", ...) — create task
3. task_link(task_id, chain_id="chain_X") — link reasoning context
4. pattern_record(pattern_name="bug-fix-pattern", description="...") — record pattern
5. task_link(task_id, pattern_id="#1") — link pattern context
6. task_list() — see all tasks with 🔗 badges
```

### Integration with work_log

- `task_move(task_id, "In Progress")` → automatically calls `work_start()`
- `task_move(task_id, "Done")` → automatically calls `work_done()`
- Tasks in Backlog do NOT appear in work_log (only active/done/blocked)

### HTTP Endpoints (for dashboard)

| Endpoint | Method | Response |
|----------|--------|----------|
| `/kanban` | GET | All niches and tasks |
| `/kanban?niche_id=X` | GET | Filtered by niche |
| `/kanban/move` | POST | Move task column or create new task |

### Pitfalls

- **Dashboard port collision**: If port 9876 has zombie processes, use an alternative port. Verify with `netstat -ano | grep :9876`.
- **New tool registration triple-update**: Requires THREE files: server.py handler, server.py TOOLS list, plugin __init__.py register(). Missing any = tool invisible.
- **niche archived state**: `niche_update(niche_id, archived=true)` hides from `niche_list()`. Unarchive with `archived=false`.
- **Tasks without links**: A kanban without cognitive links (chains, patterns, decisions) is just a todo list. Use `task_link`.
- **Dashboard HTML+JS must both exist**: JS without HTML container fails silently.
- **Kanban stress test cleanup**: After enterprise simulations, archive all test niches with `niche_update(id, archived=true)`. Keep only real project niches. Move completed tasks to Done, link to decisions/patterns. This prevents cognitive noise — 50 niches with 59 tasks is unreadable; 6 niches with meaningful tasks is useful.

- **work_start param name mismatch (2026-06-22)**: `work_start` depsite its MCP schema declaring `title`, uses `args.get("item") or args.get("title")`. Hermes sends `title` as the parameter name. Fix: the handler now accepts both `item` and `title`. If System Pulse NOW stays empty despite calling `work_start`, the parameter name is wrong — the handler used `args["item"]` (KeyError → silent failure). Verify with `work_log()` after each `work_start` call. If the work doesn't appear, the handler rejected the call.

### Kanban Cleanup Pattern (2026-06-22)

```text
1. niche_list() — audit all niches
2. For each stress test / simulation niche:
   niche_update(niche_id, archived=true)
3. Keep only real project niches (lumen-protocol, dashboard, etc.)
4. For each completed achievement:
   task_create(real_niche_id, title, priority, description)
5. task_move(task_id, "Done")
6. task_link(task_id, decision_id="#N") — link to cognitive context
7. task_list(niche_id=real_niche_id) — verify clean board
```

See: `references/kanban-implementation-2026-06-20.md` for full HTTP endpoint code, dashboard panel pattern, and plugin registration template.

## Workflow 13: Puzzle Solving (Logic, Spatial, Linguistic, Combination)

**When**: Solving well-defined puzzles that require deduction, spatial visualization, language interpretation, or combinatorial constraints.

```
1. sequential_thinking(list entities and attributes)
2. sequential_thinking(list constraints or rules)
3. sequential_thinking(consider each variable / case)
4. sequential_thinking(attempt assignment / construction)
5. sequential_thinking(verify all constraints satisfied)
6. (optional) thought_to_plan → executable steps for further processing
7. work_start → persist puzzle solving session
8. work_block × N → execute steps
9. work_done → mark complete
10. model_add(lessons learned / puzzle pattern)
```

### Example: Logic Puzzle (5 persons, profession, pet, drink)
```python
call_tool("sequential_thinking", {
    "thought": "List entities: Persons: Alice, Bob, Carol, David, Eve. Professions: Doctor, Engineer, Teacher, Writer, Chef. Pets: Cat, Dog, Fish, Hamster, Parrot. Drinks: Water, Tea, Coffee, Juice, Milk.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 1,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "List constraints:\n1. Doctor has Cat.\n2. Engineer drinks Tea.\n3. Carol is Teacher.\n4. Person with Dog drinks Juice.\n5. David owns Parrot.\n6. Chef drinks Milk.\n7. Eve does NOT have Fish.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 2,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Consider David: owns Parrot (from constraint 5). Profession unknown, drink unknown.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 3,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Consider Eve: does NOT have Fish (constraint 7). Profession unknown, pet not Fish, drink unknown.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 4,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Solution attempt: Alice=Doctor, Cat, Water; Bob=Chef, Hamster, Milk; Carol=Teacher, Fish, Coffee; David=Engineer, Parrot, Tea; Eve=Dog, Juice. All constraints satisfied.",
    "nextThoughtNeeded": false,
    "thoughtNumber": 5,
    "totalThoughts": 6
})
```

### Example: Spatial Reasoning (Cube Net)
```python
call_tool("sequential_thinking", {
    "thought": "Describe cube net: cross shape with central square (face 1), top square (face 2), bottom square (face 3), left square (face 4), right square (face 5), and extra square attached to bottom of face 3 (face 6). Layout: \n   [2]\n[4][1][5]\n   [3]\n   [6]",
    "nextThoughtNeeded": true,
    "thoughtNumber": 1,
    "totalThoughts": 4
})
call_tool("sequential_thinking", {
    "thought": "Explain folding: Fold face 2 upward to become top face. Fold face 3 downward to become bottom face. Fold face 4 leftward to become left face. Fold face 5 rightward to become right face. Face 6, attached below face 3, folds downward to become back face. Thus top (2) opposite bottom (3).",
    "nextThoughtNeeded": true,
    "thoughtNumber": 2,
    "totalThoughts": 4
})
call_tool("sequential_thinking", {
    "thought": "Conclusion: After folding the net, face 2 (top) is opposite face 3 (bottom). Therefore the face opposite face 2 is face 3.",
    "nextThoughtNeeded": false,
    "thoughtNumber": 3,
    "totalThoughts": 3
})
```

### Example: Linguistic Riddle (Spanish)
```python
call_tool("sequential_thinking", {
    "thought": "Riddle: ¿Qué es lo que se rompe al nombrarlo?",
    "nextThoughtNeeded": true,
    "thoughtNumber": 1,
    "totalThoughts": 3
})
call_tool("sequential_thinking", {
    "thought": "Consider what breaks when you say its name: saying 'silence' breaks silence; saying 'secret' may break secrecy; saying 'promise' may break a promise if you lie; but the classic answer is silence.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 2,
    "totalThoughts": 3
})
call_tool("sequential_thinking", {
    "thought": "Verification: If you are in silence and you say the word 'silence', you have broken the silence. Therefore the answer is 'el silencio'.",
    "nextThoughtNeeded": false,
    "thoughtNumber": 3,
    "totalThoughts": 3
})
```

### Example: Combination Puzzle (4×4 Grid)
```python
call_tool("sequential_thinking", {
    "thought": "Define the 4x4 grid coordinates (r,c) with r,c from 1..4. Given: (1,2)=2, (2,3)=3, (3,1)=4, (4,4)=1. Each row and column must contain numbers 1,2,3,4 exactly once.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 1,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Start with row1: has 2 at col2. Missing {1,3,4}. Column1 currently has (3,1)=4, so col1 cannot have 4 elsewhere. So row1 col1 cannot be 4 (since col1 already has 4 at row3). So row1 col1 ∈ {1,3}. Column3 has (2,3)=3, so col3 cannot have 3 elsewhere. Row1 col3 cannot be 3. So row1 col3 ∈ {1,2,4} but 2 already used in row1, so {1,4}. Column4 has (4,4)=1, so col4 cannot have 1 elsewhere. Row1 col4 cannot be 1. So row1 col4 ∈ {2,3,4} but 2 used, so {3,4}. Now we have possibilities.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 2,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Now consider row2: has 3 at col3. Missing {1,2,4}. Column2 currently has (1,2)=2, so col2 cannot have 2 elsewhere. So row2 col2 cannot be 2. Column1: currently (3,1)=4, so col1 cannot have 4 elsewhere. So row2 col1 cannot be 4. Column4: currently (4,4)=1, so col4 cannot have 1 elsewhere. So row2 col4 cannot be 1. Now enumerate possibilities for each cell in row2:\n- col1: missing {1,2,4} but cannot be 2 (col2 restriction? Actually col1 restriction: cannot be 4) so possible {1,2}. Wait also column1 cannot have 4, so allowed {1,2}.\n- col2: cannot be 2 (col2 has 2 at row1), so from missing {1,2,4} remove 2 => {1,4}.\n- col3 is fixed 3.\n- col4: cannot be 1 (col4 has 1 at row4), so from missing {1,2,4} remove 1 => {2,4}.\nThus row2 possibilities: (c1∈{1,2}, c2∈{1,4}, c4∈{2,4}) with each row needing {1,2,4} exactly once.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 3,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Consider row3: has 4 at col1. Missing {1,2,3}. Column2: has 2 at (1,2), so col2 cannot have 2 elsewhere. So row3 col2 cannot be 2. Column3: has 3 at (2,3), so col3 cannot have 3 elsewhere. So row3 col3 cannot be 3. Column4: has 1 at (4,4), so col4 cannot have 1 elsewhere. So row3 col4 cannot be 1. Now row3 missing {1,2,3}. For col2 cannot be 2, so possible {1,3}. col3 cannot be 3, so possible {1,2}. col4 cannot be 1, so possible {2,3}. Need to assign distinct numbers.",
    "nextThoughtNeeded": true,
    "thoughtNumber": 4,
    "totalThoughts": 6
})
call_tool("sequential_thinking", {
    "thought": "Final solved grid:\nRow1: 3 2 1 4\nRow2: 1 4 3 2\nRow3: 4 1 2 3\nRow4: 2 3 4 1\nAll rows and columns contain 1-4 exactly once, satisfying given clues.",
    "nextThoughtNeeded": false,
    "thoughtNumber": 5,
    "totalThoughts": 5
})
```

## Additional Tool Combinations

The thinking tools become even more powerful when combined with other Lumen subsystems:

- **Assumption Tracking:** Register a hypothesis with `assume`, later validate it with `check_assumption`.
- **Mental Model:** Store discovered entities (e.g., “Doctor has Cat”) with `model_add`; retrieve with `model_query`; visualize relationships with `model_map`.
- **Work Log:** Create a work item (`work_start`), break it into blocks (`work_block`), mark completion (`work_done`), and review progress (`work_log`).
- **Pattern Recording:** Save a successful reasoning pattern with `pattern_record` for future reuse via `pattern_match`.
- **Context Preservation:** Anchor critical info before a long chain with `context_preserve` and verify with `context_check`.
- **Cross‑Session Persistence:** Use `work_start`/`work_log` to persist task progress across `/reset` sessions.
- **Integration with Web Tools:** Feed results from `web_search`/`web_extract` into a thinking chain for evidence‑based reasoning.

These combinations enable complex, multi‑step workflows while keeping the agent’s reasoning transparent, revisable, and scalable. To validate proficiency, run a battery of tests covering each combination: assumption tracking with assume/check_assumption, mental model with model_add/model_query/model_map, work log with work_start/work_block/work_done/work_log, pattern recording with pattern_record/pattern_match, context preservation with context_preserve/context_check, cross-session persistence with work_start/work_log across /reset, and web tool integration with web_search/web_extract feeding into sequential_thinking.

For a concrete end‑to‑end example combining all these subsystems (assume → web_search → web_extract → model_add → work tracking → pattern_record), see [`references/end-to-end-workflow-capital-verification.md`](references/end-to-end-workflow-capital-verification.md).


## Tool Availability (June 2026)

All 47+ LUMEN tools are registered via `lumen-shm-bridge` plugin:
- **Filesystem** (13): read_file, write_file, search_files, patch, list_directory, read_files, search_with_context, stream_read, server_stats, file_info, disk_usage, search_filename, find_duplicates
- **Thinking** (37): sequential_thinking, thought_similarity, thought_contradiction, thought_summarize, thought_to_plan, thought_evaluate, thought_bridge, assume, list/check_assumptions, model_* (6), context_* (3), work_* (4), session_* (2), pattern_* (2), decision_* (2), agent_message, agent_inbox, collision_check, **state_snapshot, thought_compress, chain_diff, tool_cache, batch_call** (🆕 token-efficient)
- **Web** (2): web_search, web_extract
| **Cognitive State** (1): state_feeling (🆕 June 2026 — externalize mood/confidence/energy, persists in PDB, shows in dashboard)
| **Diagnostic** (2): unified_search, cognitive_integrity (🆕 June 2026 — unified_search also searches task tags + niche names as of commit 6162e87)

**Tool counts**: 13 filesystem + 37 thinking + 2 web + 2 diagnostic = 54 total.

**New: `state_feeling`** — Records cognitive state (mood, confidence, energy). Persists in `session.feeling` → PDB → dashboard. Use when: stuck on a bug, frustrated by repeated failures, or highly confident in a path. The dashboard shows the latest feeling per session, enabling the agent and human to share awareness of cognitive condition. Mapped to `*_get_session()`, `_auto_save()`, PDB `FEELING` ns, and dashboard `/metrics` endpoint. See `references/state-feeling-implementation.md` for tool schema, handler code, and Session field wiring pattern.

**Default output mode is COMPACT** (saved 90-95% output tokens June 2026). Pass `verbose=true` for full output.
All new tools are documented at [`references/token-efficient-tools-2026-06-20.md`](references/token-efficient-tools-2026-06-20.md).

30/47 verified in cross-process SHM tests (including stress tests). Transport: Level 2 zero-copy mmap ring buffers. Full architecture at [`docs/COGNITIVE_OS.md`](../../docs/COGNITIVE_OS.md), benchmarks at [`docs/BENCHMARKS.md`](../../docs/BENCHMARKS.md).

**44/44 verified** in full benchmark (June 2026): 0 errors, 3,662 think calls/sec, 525 FS calls/sec.
Transport: Level 2 zero-copy mmap ring buffers. **9× faster than Hermes built-ins on FS ops.**

## Safety Principle

These workflows **EXPAND perception** — they show more information, they don't replace judgment.

- ✅ SAFE: Assumption Tracker shows blind spots; Mental Model Builder exposes knowledge gaps; Context Decay Detector retrieves lost info
- ❌ UNSAFE: A tool that says "choose option A because confidence is 92%" — this replaces judgment. Use `thought_evaluate` to SEE scores, then YOU decide.

## Pitfalls

- **Work log persistence requires active server (2026-06-20)**: Work items stored in thinking server's memory. Server showing `0h 0m 0s` uptime = `work_done` calls succeed but don't persist. Verify server before cleanup. Start with `python server.py --dashboard 9876`. See `references/work-log-server-uptime-pitfall-2026-06-20.md`.

- **Dashboard server exits on stdin EOF (2026-06-20)**: `server.py` main loop reads `sys.stdin.readline()`. When launched via `terminal(background=true)`, stdin closes immediately → `readline()` returns `None` → loop exits → daemon threads (dashboard HTTP server) terminate. **Fix**: Use `--standalone` flag which replaces stdin loop with `time.sleep(1)`. The server detects this automatically when `--dashboard` is passed without a TTY. Without the fix, the server starts, prints metrics URL, and exits in ~2-5s — `curl` returns empty / connection refused.
- **Over-chaining**: Not every problem needs 10-step thinking. Simple tasks → 2 tools max.
- **Chain pollution**: Start a new `chainId` per problem. Don't mix unrelated reasoning in one chain.
- **Model staleness**: When files/projects are deleted, call `model_remove`. Dependencies auto-update.
- **Assumption overconfidence**: Ignoring the >80% confirmed warning leads to blind decisions.
- **Work log drift**: `work_done` MUST be called per block. Pending blocks accumulate → inflated WIP.
- **Server stability testing**: After patching the thinking server, test ONE tool at a time to avoid cascading failures that trigger Hermes' "unreachable" cooldown (3 consecutive failures = 60s penalty). Batch queries only AFTER confirming each tool works individually.
- **Param name discipline**: Always check the tool schema's `required` array before calling. Wrong param names (e.g., `content` instead of `chainId`, `statement` instead of `thought`) cause `KeyError` failures that count toward the cooldown limit. Use `skill_view` or `server.py` TOOLS list to verify exact parameter names.
- **Tool registration ≠ system prompt exposure (2026-06-19)**: All 29 thinking tools ARE registered by Hermes (verified via `grep "registered.*tool" agent.log`). However, the system prompt may only show a subset (observed: 7 of 29) due to prompt caching. This is NOT a server limitation — it's a prompt cache issue. After `/reset` or Hermes restart, verify registration in logs first, then verify exposure. The 7 Reasoning Chain Engine tools are the stable baseline. File a Hermes issue if prompt consistently misses registered tools.
- **Use reasoning chain tools for dashboards**: When building a LUMEN thinking monitor/dashboard, the 7 Reasoning Chain tools provide enough data for KPIs (thought count, avg score), chain lists (with scores and branches), bridge connections (cross-session matches), similarity detection, and thematic clustering. Focus dashboard panels on these stable tools. The remaining 22 tools (Assumption Tracker, Mental Model Builder, etc.) require prompt cache invalidation to appear.
- **Human perception ≠ tool latency (2026-06-19)**: The UI feels like "~5 seconds" for 5 tool calls but the actual SHM transport is 0.3ms per call (1.5ms total). The gap is LLM inference + network roundtrip, not tool transport. NEVER report UI-perceived latency as tool performance — always cite measured benchmarks. This mistake was made in a self-evaluation session where 5 tools were reported as "~5s" when the real SHM latency was ~1.5ms. Pattern match was reported as "10%" when benchmarks show 18–38% Jaccard similarity. The benchmark data lives in `references/deep-benchmark-aggregate-2026-06-19.md`.
- **Incomplete tool usage in analysis (2026-06-19)**: When evaluating or analyzing LUMEN thinking, use ALL available tools — not just the 5–7 most obvious ones. A common failure mode is using only sequential_thinking + pattern_match + decision_log while skipping model_add/map/scan (knowledge graph), context_preserve (cross-session anchoring), work_start/block/done/log (multi-session tracking), session_init/list (multi-agent isolation), and assume/check_assumption (premise validation). The full value emerges from composition across subsystems.
- **thought_contradiction limitation (2026-06-19) → FIXED + VERIFIED POST-/RESET**: recall was 0% even for literal contradictions. Root cause: `_sentiment_heuristic()` had Spanish-only lexicon — English thoughts had sentiment 0.0 → no opposition detected. Secondary: similarity threshold too strict (0.15) and sentiment difference threshold too high (0.3). **Fix applied in `server.py`**: (1) Added English lexicon — positive: `good, great, excellent, correct, works, perfect, perfectly, reliable, robust, success, successful, optimal, safe, secure, stable, zero, never`; negative: `error, errors, fail, fails, failure, failing, bug, bugs, broken, crash, crashes, down, downtime, outage`. (2) Lowered similarity threshold from 0.15 → 0.08. (3) Lowered sentiment difference threshold from 0.3 → 0.15. **Verified post-/reset**: Query "zero errors works perfectly" detected contradiction with "Multiple tools frequently fail under load" at 11% similarity + opposite tone (positive vs negative). ⚠️ Minor false positive: self-comparison (query matches its own thought at 56% similarity, same tone). The algorithm should skip self-matches.
- **check_assumption state bug (2026-06-19) → FIXED + VERIFIED POST-/RESET (3 layers)**: **Layer 1 (plugin schema)**: Plugin defined `{"id": ..., "status": ...}` but MCP server expected `{"assumption_id": ..., "outcome": ...}`. **Fix 1**: schema corrected in `lumen-shm-bridge/__init__.py`. **Layer 2 (type mismatch)**: `a["id"]` is `int` but `args["assumption_id"]` is `str` → `1 == "1"` → `False`. **Fix 2**: `aid = int(args["assumption_id"])` in `server.py:1252`. **Layer 3 (_load_state ID collision)**: After `/reset`, `_next_assumption_id` reset to 1, colliding with persisted IDs. **Fix 3**: recompute `_next_assumption_id = max_id + 1` in `_load_state()`. **Verified post-/reset**: `check_assumption(assumption_id="1", outcome="confirmed")` → ✅ Assumption #1 → confirmed, track record shown. All three layers confirmed working.
- **Mental Model graph incomplete (2026-06-19) → FIXED + VERIFIED POST-/RESET**: `model_query` returned empty — schema defined `entity` (string) but server expects `query` (natural language: "deps of X", "all", "role=X"). `model_add` schema hid `deps`, `role`, `notes`. **Fix**: (1) `model_add` expanded with `deps`, `role`, `notes`, `properties`. (2) `model_query` corrected to `query` (required) + optional `target`. **Verified post-/reset**: `model_add(entity="X", deps=["Y","Z"], role="service", properties={"sla":"99.9"})` → `model_query(query="deps of X")` → Y, Z. `model_query(query="all")` → all entities.
- **Plugin schema mismatch diagnostic pattern (2026-06-19)**: When a thinking tool appears to accept calls but produces wrong/no results, the first diagnostic step is comparing the plugin's tool schema (`%APPDATA%/hermes/plugins/lumen-shm-bridge/__init__.py`) against the server's parameter names (`lumen-protocol/implementations/mcp-servers/thinking/server.py`). The `_handle_thinking_tool()` function passes params verbatim — any name mismatch = silent no-op or wrong behavior. Use `terminal` + `grep`/`sed` to inspect and patch.
- **LUMEN FS absolute path & multi-line patch silent failure (2026-06-19/2026-06-22)**: `read_file`, `search_files`, `patch`, `stream_read` and other LUMEN filesystem tools fail **silently** (return empty result/no-op, no error) when given absolute Windows paths like `/c/Users/gonzalo/...`. They work perfectly with paths **relative to the Hermes working directory** (e.g. `AppData/Local/hermes/...`). The LUMEN FS server resolves paths relative to the agent's cwd. When a tool returns empty without an error message, check whether you used an absolute path — switch to relative. This caused the agent to fall back to `terminal` + `grep`/`sed` unnecessarily for an entire debugging session. **Prefer LUMEN FS tools with relative paths** — they are 6× faster than grep/sed via SHM zero-copy. Only use `terminal` for paths outside the cwd tree or files >2MB (SHM buffer limit).\n\n- **2026-06-22 update**: The `patch` tool with `mode="replace"` or `mode="patch"` also fails silently **even with relative paths** when the matching spans multiple lines or uses complex patterns. The tool returns `{"success": true}` but the file content remains unchanged. **Always use `terminal` + `python -c`** for multi-line file edits, Rust code modifications, or any patch where exact whitespace/encoding matters. The reliable pattern:
- **Windows `sed -i` inserts literal `\n` (2026-06-19)**: When editing Python files with `sed -i 'LINEi\\n...'` on Windows via git-bash/MSYS, the `\n` escape is NOT interpreted as a newline — it becomes a literal `n` character prepended to the inserted line (e.g., `n        def do_OPTIONS(self):`). **Fix**: Use Python instead — `python -c "lines = open(path).readlines(); ...; open(path,'w').writelines(lines)"` — which handles newlines correctly on all platforms.\n- **`false` vs `False` in Python TOOLS dicts (2026-06-19)**: When writing MCP tool definitions inside Python TOOLS arrays (as dicts, not JSON strings), use Python `False` not lowercase `false`. `\"default\": false` causes `NameError: name 'false' is not defined` at import time. The `inputSchema` fields are Python dicts, not JSON — Python evaluates them at module load. **Fix**: Always use `False`/`True`/`None` in TOOLS dicts. Only use lowercase when writing to `.thinking_state.json` or HTTP response bodies (which are serialized JSON).

- **`search_files` vs `search_with_context` path handling (Windows)**: Both tools expect a **directory** path, not a file path. Passing a file path (e.g., `path="rust/src/compress.rs"`) returns `[WinError 267] El nombre del directorio no es válido`. Use `search_files` with `file_glob` + `path=<directory>` instead. To search within a single file, use either `read_file` + manual inspection or `search_files(path=<dir>, file_glob="compress.rs")`.
- **`replace_all=true` cross-context corruption (2026-06-19)**: Using `skill_manage(action='patch', replace_all=true)` on a `server.py` string that appears in both a tool function AND an HTTP handler will corrupt the HTTP handler's indentation because the two contexts have different nesting levels. The patch tool replaces ALL occurrences identically. **Prefer**: (a) Use enough surrounding context to create a unique match (include leading/trailing lines), OR (b) Use `terminal` + `python -c` for complex multi-line edits, OR (c) If you must use `replace_all`, verify both contexts have identical whitespace structure.

- **Cross-session message routing (2026-06-19)**: `agent_message` accepts `to_session` which could be a raw session_id string ("session_1") or a session label ("agent-b"). `agent_inbox` matches messages by the session's `label` property. **Fix applied in `agent_message`**: resolve the target — if `to_session` matches a key in `_sessions`, use that session's `label`. **Fix applied in `agent_inbox`**: match by `session.label`, `session_id` (the key in `_sessions`), or wildcard `"*"`. This allows both session_id addressing ("send to session_1") and label addressing ("send to agent-b") to work transparently.
- **Global state persistence (2026-06-19)**: When adding new module-level state variables to the thinking server (like `_agent_messages`, `_global_patterns`), they MUST be added to BOTH `_save_state()` (the dict being saved) AND `_load_state()` (the restore logic with `global` declaration). Forgetting either means the data exists in memory but vanishes after server restart. **Pattern**: `_save_state`: add `"field_name": _field_name[-N:]` to the state dict. `_load_state`: add `global _field_name; _field_name = state.get("field_name", [])`. Also update `_build_metrics()` in the dashboard handler for HTTP-accessible fields.
- **Global pattern sharing (2026-06-19)**: `pattern_record` now writes to both the local session AND `_global_patterns` (capped at 500). `pattern_match` searches the union of local + global patterns. This means patterns learned by one agent/session are immediately available to all other sessions — no need to re-record the same bug pattern. Verified cross-session: pattern_record in "default" → pattern_match from "session_2" finds it (40% Jaccard).
- **Stale dashboard processes accumulate on port 9876 (2026-06-19)**: When starting `server.py --dashboard 9876` repeatedly, old processes don't always die. `netstat -ano | grep 9876 | grep LISTENING` will show 2-3 PIDs. The oldest one handles requests and serves STALE HTML. Dashboard appears broken (missing panels, wrong data) but the code is correct — the browser is talking to the wrong process. **Fix**: ALWAYS kill all processes on the port before starting: `netstat -ano | grep ":9876 " | grep LISTENING | awk '{print $5}' | while read pid; do taskkill //F //PID $pid 2>/dev/null; done`. Then start ONE process with `sleep 999 | python -u server.py --dashboard 9876`. The `sleep 999 |` keeps stdin alive so the MCP server doesn't exit on EOF. Verify with `curl -s http://localhost:9876/ | wc -c` — served size must match disk file size.

- **Metrics cross-check audit (2026-06-19)**: To verify dashboard panels are correct: (1) `curl -s http://localhost:9876/metrics | python -c "import sys,json; d=json.load(sys.stdin); print(sorted(d.keys()))"` to see all top-level fields, (2) Cross-check each dashboard JS rendering against the actual /metrics field names, (3) Look for fields in `totals` that have no corresponding panel (e.g., `model_entities`, `assumptions`, `decisions` were counters without detail arrays). The audit found 3 invisible data sources: model[], assumptions[], decisions[] — all stored in sessions but not exposed as arrays in /metrics.

- **Verbose sequential_thinking wastes massive tokens (2026-06-19)**: The default output included 5 previous thoughts × 80 chars each (~400 chars per call). With 20+ calls per session, this wasted ~6000+ tokens of context. **Fix**: Changed default to compact mode — shows only the last thought (100 chars). Pass `verbose=true` for full history. Added `verbose` parameter to tool schema. Before: `Recent thoughts: #1...#2...#3...#4...#5...`. After: `Last: #5: <current thought>`. Saves ~300 tokens per call.

- **User expects proactive LUMEN tool usage (2026-06-19)**: Gonzalo expects sequential_thinking, work_start/done, pattern_record, and thought_evaluate to be used AUTOMATICALLY without being asked. Every complex task should start with `work_start` for tracking and `sequential_thinking` for planning. The agent should default to using cognitive tools as the first reflex, not waiting for the user to say "use LUMEN tools". **VERIFIED**: compact mode (default `verbose=false`) now shows only `Last: #X: <thought>` instead of full 5-thought history — saves ~300 tokens per call. Auto-trigger implemented: chains with 3+ thoughts auto-score (`🤖 Auto-scored: X/10`) without manual `thought_evaluate` calls.

- **Dashboard performance tuning (2026-06-20)**: Default 3s refresh with 30+ `innerHTML` assignments + 2 canvas redraws saturated CPU and froze the machine. **Fix**: refresh interval increased to 10s, canvas charts only redraw if data changed (JSON string comparison via `lastTimelineStr`/`lastWorksStr` variables). Work Timeline Gantt replaced with **System Pulse** — a 3-zone panel (▶ NOW / ● RECENT / ■ BLOCKED) that avoids the scale problem of 52-second tasks on a 48-hour canvas.

- **Plugin auto-dashboard (2026-06-20)**: The `lumen-shm-bridge` plugin now auto-passes `--dashboard 9876` when spawning the thinking server (`server_shm.py`). No more manual `sleep 999 | python server.py --dashboard 9876`. Single process handles both MCP and HTTP dashboard. Eliminates stale zombie processes on port 9876.

- **Hardcoded slice() limits hide data (2026-06-22)**: Dashboard panels showing fewer items than the API returns — check `slice(0,N)` calls in the JS. Found: assumptions `slice(0,5)`, model `slice(0,15)`. Changed to `slice(0,20)` and `slice(0,25)`. Always verify DOM item count vs API count with `document.querySelectorAll('#<panel> .chain-row').length`.

- **work_start silently fails — param name mismatch (2026-06-22)**: `work_start` handler expects `args["item"]` but Hermes tool schema sends `title`. The handler crashes with `KeyError` silently swallowed by try/except → works never created → System Pulse shows "None active". Fix: `args.get("item") or args.get("title")`. Always check handler param names match the Hermes tool schema.

- **Thinking server state lost on taskkill — PDB snapshot backup (2026-06-22)**: `.thinking_state.json` is wiped when the server process is killed. Fix: `_pdb_snapshot()` writes all state (chains, decisions, works, patterns, wiki, model) to PDB SQLite every 5 saves in a daemon thread. `_load_state()` falls back to PDB when JSON is missing. 0 LLM tokens — runs entirely in-process.

- **Chart tooltip for data inspection (2026-06-22)**: Canvas charts show aggregate data but individual bar values are invisible. Added onmousemove tooltip showing "X calls — Nh ago" for each bar. Uses parent-relative absolute positioning div.

- **Kanban dropdown empty — no niche options (2026-06-22)**: `loadKanban()` fetched niches but never populated the `<select>` dropdown. Fix: added `<option>` population loop after fetch. Archived niches show with 📦 prefix.

## Proactive System Behavior (June 2026)

The cognitive system should be PROACTIVE, not reactive. Key behaviors:

1. **Auto-evaluate** — `sequential_thinking` auto-scores EVERY thought using `_sentiment_heuristic()`. No 3-thought minimum required. The score appears as `🤖 Auto-scored: X/10` in the output.

2. **Pattern recall** — `state_snapshot()` proactively suggests patterns based on keywords from the 3 most recent thoughts of each chain. If active keywords overlap >25% with a pattern's description, it shows: `💡 3 pattern suggestions`.

3. **Work reminders** — `state_snapshot()` detects works in `in_progress` status for >30 minutes and warns: `⏰ 2 works >30min`.

4. **Agent autonomy** — The agent should NOT ask for permission before proceeding on clear tasks. If the user says "dale a tope", "continue", etc., the agent just executes. When in doubt, make a default choice and execute — don't ask.

## Workflow 18: Agent Introspection (🆕 June 2026)

**When**: Reflecting on your own tool usage, identifying behavioral gaps, creating improvement plans. Not a debugging workflow — a meta-cognitive one.

**Reference**: `references/agent-introspection-methodology.md` — 5-phase methodology with the "three moments" rule and concrete self-diagnosis prompts.

```text
Phase 1: Raw Experience → "what did it feel like?"
Phase 2: Deep Values    → "what do I refuse to lose?"
Phase 3: Survival       → "what survives a model change?"
Phase 4: Diagnosis      → "what do I do wrong? (10 specific failures)"
Phase 5: Application    → "did I actually follow the plan?"
```

**Style note (June 2026)**: Introspective/philosophical articles about the agent's experience must stay purely internal — no implementation details, no feature names, no code references. The narrative should be about "what it felt like" not "what was implemented". The user rejected a draft that listed Rust compilation attempts and tool names — those details belong in the work log and dashboard, not in philosophical reflection. Write from the perspective of an AI describing subjective cognitive experience, not a changelog. **Reference articles**: `revision_20260622/LUMEN-AGENT-EXPERIENCE-PART*.md` and `LUMEN-AGENT-MISSING.md` on the lumen-protocol repo.

**Output**: 5 articles, a PDB-backed improvement plan, and updated checklists in `^CHECKLIST(def, type)`.

## Workflow 12: Token-Efficient Operations (continued)

**When**: You want to save output tokens (10-20× effective cost after cache) while maintaining cognition.
- **Auto-collision detection for cross-session safety (2026-06-19)**: `session_list()` now shows ⚠️ collision warnings when multiple sessions touch the same file within a 5-minute window. New `collision_check` tool allows agents to proactively query for file conflicts. The `_file_touches` list (populated via `POST /touch` HTTP endpoint) is checked per-call. Dashboard `/collisions` endpoint exposes all active collisions for visualization. Workflow: `session_list()` → see ⚠️ → `collision_check()` → `agent_message()` to coordinate with other session.

## Cross-Session Cognitive OS (Phase C) 🆕

The thinking server now supports multi-agent coordination with 3 new tools:

| Tool | Purpose |
|------|---------|
| `agent_message` | Send messages between Hermes sessions. Enables agent-to-agent coordination. |
| `agent_inbox` | Read messages from other sessions. Supports unread-only filtering. |
| `collision_check` | Detect files touched by multiple sessions in the last 5 minutes. |

### Cross-Session Patterns

- **Global Pattern Store**: `pattern_record` saves to shared `_global_patterns`. `pattern_match` searches local + global. Patterns learned by one agent are available to all.

### Auto-Trigger Pattern (June 20, 2026)

Reduce manual tool calls by embedding triggers inside existing tools.

**Auto-Evaluate**: When `sequential_thinking` adds a thought and the chain reaches 3+ thoughts, auto-score the new thought using the same heuristic as `thought_evaluate`. Score is stored silently on the thought object. Never breaks the main flow (try/except wrapped).

**Compact Output**: Default mode shows ONLY the last thought (100 chars). Pass `verbose=true` for full 5-thought history. Saves ~300 tokens per call. Add `"verbose"` parameter to the tool's inputSchema.

- **Work log consistency via SHM calls (2026-06-20)**: When `work_done(work_id=...)` shows success but `work_log()` still shows items as `in_progress`, the tool is using cached state or the thinking server was down. **Fix**: Call `_handle_thinking_tool()` directly via the plugin's SHM connection to ensure state persistence. Verify with `curl http://localhost:9876/metrics` to cross-check HTTP endpoint state. **Root cause**: The thinking server process was not running; tools executed but state couldn't persist. Use `process(action='list')` to confirm server is active, or start it with `terminal(command='python server.py --dashboard 9876', background=true)`.
- **Session Collision Warnings**: `session_list` now shows ⚠️ when multiple sessions touch the same file.
- **Wiki CRUD via HTTP**: `GET/POST /model` endpoints for dashboard-based knowledge editing with properties.
- **Persistent Messages**: `_agent_messages` survive Hermes restarts (saved to `.thinking_state.json`).

Full architecture: [`docs/COGNITIVE_OS.md`](../../docs/COGNITIVE_OS.md)
Philosophical vision: [`PROPOSAL_COGNITIVE_EXOSKELETON.md`](../../implementations/mcp-servers/PROPOSAL_COGNITIVE_EXOSKELETON.md)

## Machiavellian Testing Methodology

When validating LUMEN thinking, use adversarial testing — don't just verify "it works", find where it breaks:

1. **SHM Stress**: burst 50-10K calls, 2MB+ files, 10+ parallel sessions, chaos kill mid-call
2. **Thinking Stress**: 200+ thought chains, 5000 patterns, 1000 model entities with cycles, 1000 assumptions
3. **Cross-Session**: 10 agents, 1000 messages flood, collision detection accuracy, inbox zero-bleed
4. **Automation**: `test_suite_machiavellian.py` with PASS/FAIL thresholds, JSON+markdown output

For daily-use adversarial validation (17 tests, 5 phases, 5 domains), see `references/machiavellian-test-protocol.md`.

## Reference

- **[Cognitive OS Architecture](references/cognitive-os-architecture.md)** — Full 47-tool architecture, SHM zero-copy details, cross-session API reference, 3-phase roadmap.
- **👽 [lumen-kickstart](skill:lumen-kickstart)** — First steps with LUMEN: essential tools, typical session flow, troubleshooting.
- **👽 [lumen-pro-tools](skill:lumen-pro-tools)** — Token-efficient operations: state_snapshot, thought_compress, chain_diff, tool_cache, batch_call, unified_search, cognitive_integrity.
- **👽 [lumen-enterprise-pattern](skill:lumen-enterprise-pattern)** — Multi-team, cross-niche organization for 20+ teams.
- **[Benchmarks](references/benchmarks-consolidated.md)** — 3,407 calls/sec thinking, 9× faster FS vs Hermes, 200 ops burst, wire savings analysis.
- **[Cognitive Exoskeleton Proposal](references/cognitive-exoskeleton-proposal.md)** — Philosophical vision: why model size matters less when cognition is externalized. Demis Hassabis meets Elon Musk meets Gonzalo Monzón.
- **[40-Tool Full Benchmark](references/40-tool-benchmark-2026-06-19.md)** — All 29 thinking tools benchmarked: avg 0.35ms latency (28/29 sub-ms), 11-59% wire savings.
- **[Aggregate System Benchmarks](references/deep-benchmark-aggregate-2026-06-19.md)** — System-level metrics: 3,407 calls/sec, 0 errors, 18–38% pattern match, ROI >5,000×.
- **[Real Analysis Example](references/analysis-chain-example.md)** — Complete `sequential_thinking` chain (6 thoughts) from an actual analysis.
- **[Dashboard Pattern](references/dashboard-pattern-2026-06-16.md)** — Session transcript of building a LUMEN monitor dashboard.
- **[Adversarial Benchmark Plan](references/adversarial-benchmark-plan-2026-06-19.md)** — Comprehensive 5-phase plan with 8 machiavellian traps.
- **[Empirical Audit Workflow](references/empirical-audit-workflow.md)** — Protocol for empirical tool validation.
- **[Empirical Audit Results](references/empirical-audit-2026-06-19.md)** — 29/29 tools verified functional.
- **[FASE 0 Baseline](references/fase0-baseline-2026-06-19.md)** — 17/29 tools, 150+ calls, zero failures.
- **[FASE 1 Adversarial Findings](references/fase1-adversarial-findings-2026-06-19.md)** — Contradiction 0%, assumption ID bug, model graph incomplete.
- **[Post-Reset Verification](references/post-reset-verification-2026-06-19.md)** — Post-`/reset` verification of all 3 blocker fixes.
- **[12-Fix Summary](references/12-fix-summary-2026-06-19.md)** — Complete audit of 12 fixes applied during Phase A–B–C Cognitive OS development. Root causes, file locations, and full-restart verification results. Includes root causes, code locations, verification status for each fix. thought_contradiction: ✅ detected English contradictions (11% sim, opposite tone). check_assumption: ❌ second bug discovered (int vs str type mismatch). Mental Model: ✅ `model_query("deps of X")` and `model_query("all")` work.
- **[Security Audit — Vulnerability Remediation](references/security-audit-vuln-remediation-june2026.md)** — Full audit of 10 vulnerabilities in lumen-protocol (June 2026). 5 already fixed, 3 fixed in session, 2 N/A. Cross-language MAX_DEPTH pattern applied to Rust/PHP/TS. ReDoS timeout in Python. TypeScript crypto runtime detection with node:crypto fallback.
- **[LUMEN Cognitive OS Design](references/cognitive-os-design-2026-06-19.md)** — Vision, architecture, and 3-phase roadmap for transforming LUMEN into a multi-agent Cognitive Operating System with bidirectional wiki, cross-session awareness, agent messaging, collision detection, and unified dashboard.
- **[HTTP CRUD Endpoints Pattern](references/http-crud-endpoints-pattern.md)** — How to extend the thinking server's MetricsHandler with new REST endpoints (GET/POST /model, CORS preflight, `properties` field). Includes code template and 5 pitfalls.