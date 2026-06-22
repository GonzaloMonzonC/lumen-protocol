---
name: lumen-daily-workflows
description: 'Core daily LUMEN workflows — problem-solving, decision-making, debugging, learning, multi-session tasks, and wiki building. The 6 workflows you need every session.'
version: 1.1.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, workflows, daily, core]
---

# Lumen Daily Workflows

The 6 workflows you need every session. For advanced workflows (audit, enterprise, adversarial, Q&A, puzzle-solving), load `lumen-cognitive-workflows`.

## Quick Reference

| # | Workflow | When |
|---|----------|------|
| 1 | Problem → Plan → Execute | Complex multi-step tasks |
| 2 | Decision → Validation | High-stakes choices |
| 3 | Scientific Debugging | Root cause analysis |
| 4 | Structured Learning | Domain ramp-up |
| 5 | Multi-Session Task | Cross-session Work |
| 9 | Wiki Building | Institutional knowledge |

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

---

## Workflow 2: Decision → Validation → Learning

**When**: High-stakes decisions with hidden premises (strategy, security, product)

```
1. assume(surface premises explicitly)
2. list_assumptions(review the landscape)
3. sequential_thinking(reason through the decision)
4. check_assumption(validate each premise)
5. model_add(capture what you learned)
6. model_query(reuse next time)
```

---

## Workflow 3: Scientific Debugging

**When**: Hard-to-reproduce bugs, multi-system root cause analysis

```
1. context_preserve(error symptoms, stack traces, env details)
2. sequential_thinking(generate hypotheses — branch to explore alternatives)
3. thought_contradiction(find logical conflicts in hypotheses)
4. thought_evaluate(score each hypothesis)
5. thought_summarize(cluster related hypotheses)
6. model_add(root cause pattern once confirmed)
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

---

## Workflow 5: Multi-Session Task

**When**: Work spanning multiple chat sessions

```
Quick Context Recovery (useful ANY time):
1. work_log() — current work items, pending/in_progress
2. session_search() — recent sessions by time or topic
3. state_snapshot() — system state
4. decision_list() — architectural decisions made
5. model_stats() — knowledge entities
6. session_list() — active sessions

Session Start:
1. work_start(title, description) → persist
2. [Session 1] work_block × N → work_done
3. [Session 2] work_log → recall state
4. [Session N] work_log(full history) → model_add(lessons)
```

---

## Workflow 9: Wiki Building

**When**: Building persistent knowledge — architecture docs, bug reports, institutional memory.

**MCP Tools**: wiki_create, wiki_read, wiki_update, wiki_delete, wiki_list (64 MCP tools total, 5 wiki tools).

### When to Use Wiki vs Other Tools

| Tool | Use For | Lifetime |
|------|---------|----------|
| `wiki_create` | Architecture docs, bug reports, project knowledge | **Permanent** |
| `decision_log` | Architecture decisions with rationale and revisit triggers | **Permanent** |
| `pattern_record` | Bug patterns + fix strategies | **Permanent** |
| `pdb_scratch_set` | Session working state, cross-topic context | **Session** |
| Hermes `memory` | User preferences, environment facts | **Permanent** |

### Daily Patterns

**Session Start:**
```python
wiki_list()  # See institutional knowledge
wiki_read("Key Page")  # Recall specific topic
```

**During Session:**
```python
wiki_create("Architecture Doc", "# Title\n...")
wiki_update("Session Log", "\n## More\n...", mode="append")
```

**Session End:**
```python
wiki_update("Session Log", "\n## Achievements\n- ...", mode="append")
```

### Content Conventions

- **Titles**: Pascal Case ("Dashboard Bugs Review")
- **Format**: Markdown with `##` sections
- **Append**: `wiki_update(mode="append")` for accumulating logs
- **Replace**: `wiki_update(mode="replace")` for rewrites
- **Upsert**: `wiki_create` updates if exists, creates if not

---

## Session Start Routine

Every session starts with this sequence:

```python
# 1. Pre-flight checklist (PDB-backed)
checklist("session_start")  # work_log → objective_status → state_snapshot → decision_list

# 2. Load context
pdb_scratch_get("session_state")  # last session context

# 3. Choose checklist by task type (PDB-backed)
checklist("feature")   # for new features
checklist("bug_fix")   # for bug fixes  
checklist("research")  # for investigations
checklist("audit")     # for audits
```

The checklists live in PDB namespace `CHECKLIST("def", "{type}")` and persist across sessions.
Each item has: tool, description, phase (before/during/after), required (bool).

**Three moments — mandatory:**

| Moment | Required tools | Why |
|--------|---------------|-----|
| **Before** (pre-flight) | `work_start`, `sequential_thinking`, `context_preserve` | No empiezo sin registrar |
| **During** (findings) | `pattern_record`, `decision_log`, `model_add` | No descubro sin guardar |
| **After** (post-flight) | `work_done(work_id=N)`, `task_move(...)`, `pattern_record()` | No termino sin cerrar |

See `process-database` skill reference: `references/pdb-checklist-pattern.md` for full namespace docs and examples.

## Proactive System Behavior

1. **Auto-evaluate**: sequential_thinking auto-scores EVERY thought
2. **Agent autonomy**: Execute without asking on clear tasks
3. **Keep chat output short**: Internal reasoning stays in LUMEN state (dashboard)
4. **Use ALL available tools**: Not just the obvious 2-3

---

**See also:**
- `lumen-cognitive-workflows` — Advanced workflows (audit, enterprise, adversarial, Q&A)
- `process-database` — PDBM-Lumen architecture and daily usage
- `kanban-cognitive` — Kanban by cognitive niche with task management