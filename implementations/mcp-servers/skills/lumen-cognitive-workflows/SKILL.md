---
name: lumen-cognitive-workflows
description: 5 composable cognitive workflow patterns for Lumen Thinking's 22 tools — problem-solving, decision-validation, debugging, learning, and multi-session task tracking.
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, thinking, workflows, cognition, composition]
---

# Lumen Cognitive Workflows

Documented composition patterns for Lumen Thinking's 22 tools. These workflows
chain multiple cognitive tools into **proven decision-making and problem-solving
pipelines**. Copy, adapt, and compose them.

Each workflow is a **cognitive exoskeleton** — externalizing the metacognitive
operations that expert reasoners do internally but LLMs struggle with (tracking
assumptions, detecting contradictions, preserving context across turns).

---

## Quick Reference: The 7 Cognitive Subsystems

| Subsystem | Tools | Role |
|-----------|-------|------|
| Reasoning Chain Engine | `sequential_thinking`, `thought_similarity`, `thought_contradiction`, `thought_summarize`, `thought_to_plan`, `thought_evaluate`, `thought_bridge` | Structured reasoning, revision, cross-chain insight |
| Assumption Tracker | `assume`, `list_assumptions`, `check_assumption` | Surface hidden premises, detect overconfidence |
| Mental Model Builder | `model_add`, `model_query`, `model_stats`, `model_map`, `model_remove` | Persistent entity-relation graph across sessions |
| Context Preservation | `context_preserve`, `context_check` | Anchor critical info against decay |
| Work Tracking | `work_start`, `work_block`, `work_done`, `work_log` | Multi-session task state |
| Context Estimation | `context_estimate` | Pre-flight token planning |

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

**When**: Work spanning multiple chat sessions (coding features, research projects)

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

## Composing Beyond the Patterns

These 5 workflows are **primitives** — compose them:

- **Learning → Debug**: `model_add(pattern)` → `context_preserve(bug)` → `sequential_thinking(match pattern to symptoms)`
- **Task → Decision**: `work_start` → hit blocker → `assume(cause)` → `check_assumption` → `work_block(revised approach)`
- **Cross-session Insight**: `thought_bridge("security patterns")` → finds past reasoning → `model_query(relevant pattern)` → `sequential_thinking(adapt to current context)`

## Safety Principle

These workflows **EXPAND perception** — they show more information, they don't replace judgment.

- ✅ SAFE: Assumption Tracker shows blind spots; Mental Model Builder exposes knowledge gaps; Context Decay Detector retrieves lost info
- ❌ UNSAFE: A tool that says "choose option A because confidence is 92%" — this replaces judgment. Use `thought_evaluate` to SEE scores, then YOU decide.

## Pitfalls

- **Over-chaining**: Not every problem needs 10-step thinking. Simple tasks → 2 tools max.
- **Chain pollution**: Start a new `chainId` per problem. Don't mix unrelated reasoning in one chain.
- **Model staleness**: When files/projects are deleted, call `model_remove`. Dependencies auto-update.
- **Assumption overconfidence**: Ignoring the >80% confirmed warning leads to blind decisions.
- **Work log drift**: `work_done` MUST be called per block. Pending blocks accumulate → inflated WIP.
