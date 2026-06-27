---
name: lumen-kickstart
description: '👽 Quickstart guide for LUMEN Cognitive OS — first steps, typical session flow, essential tools, and common workflows. Start here if you are new to LUMEN tools.'
version: 1.0.0
author: Cadences Lab
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [lumen, quickstart, kickstart, first-steps, tutorial]
---

# 👽 LUMEN Kickstart — First Steps with Cognitive Tools

> Welcome to LUMEN. This skill is your **first contact**. It assumes nothing. Follow the steps in order.

---

## What is LUMEN?

LUMEN is a set of **cognitive tools** (MCP servers) that work alongside your LLM. They give you:

- **Permanent memory** across sessions (patterns, decisions, Q&A)
- **Project organization** by cognitive niches (kanban)
- **Reasoning chains** that survive context compression
- **Self-diagnosis** (health checks, unified search)

All LUMEN tools are marked with **👽** in the assistant's responses so you know when they're being used.

---

## Step 1: Know Your First 5 Tools

Don't learn all 30+ at once. Start with these 5:

| # | 👽 Tool | What it does | Say this |
|---|---------|-------------|----------|
| 1 | `state_snapshot` | Shows system health in one line | "state_snapshot" |
| 2 | `niche_list` | Shows all your projects/areas | "niche_list" |
| 3 | `task_list` | Shows all tasks across projects | "task_list" |
| 4 | `qa_ask` | Save a question+answer permanently | "qa_ask question='...' answer='...'" |
| 5 | `cognitive_integrity` | Check system health score | "cognitive_integrity" |

**Try them now.** Call each one once. You can't break anything.

---

## Step 2: Create Your First Project (Niche)

A **niche** is a project area. Create one for anything:

```
niche_create(name="my-first-project", color="#22d3ee", desc="Learning LUMEN")
```

Then add tasks:

```
task_create(niche_id="niche_X", title="Learn task_create", priority="high")
task_create(niche_id="niche_X", title="Learn task_move", priority="medium")
```

**Tip:** Use `task_move(task_id, "In Progress")` to start working on a task.
Use `task_move(task_id, "Done")` to complete it.

---

## Step 3: Save Your First Knowledge

**Patterns** (bug fixes, lessons learned):

```
pattern_record(pattern_name="my-first-pattern", description="What I learned")
```

**Decisions** (architectural choices):

```
decision_log(decision="Why I chose X over Y")
```

**Q&A** (questions with answers):

```
qa_ask(question="What is a niche?", answer="A project area in LUMEN", tags=["basics"])
```

---

## Step 4: Search Everything

```
unified_search(query="learning")
```

This searches across tasks, patterns, decisions, Q&A, model, and web snapshots at once.

```
cognitive_integrity()
```

This checks the health of your LUMEN system. Score >80 is good.

---

## Step 5: Typical Session Flow

Every session can follow this pattern:

```
1. state_snapshot              → baseline: know the state
2. task_list(status="In Progress") → what's active?
3. task_search(priority="critical") → what's urgent?
4. [work on things, use tools]
5. qa_ask(question="...")     → save what you learned
6. pattern_record(...)         → save patterns
7. state_snapshot              → end baseline
```

---

## Troubleshooting: First Session

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `state_snapshot` returns data | Normal! LUMEN is already running | Nothing to do |
| Tools return "not found" | Hermes needs reset | Reset Hermes |
| Dashboard `:9876` not loading | Server not started | Ask assistant to start it |
| All KPIs show 0 | Browser cache | `Ctrl+Shift+R` hard refresh |

---

## Quick Reference Card

```text
ORGANIZE:   niche_create → task_create → task_move → task_list
LEARN:      pattern_record → decision_log → qa_ask
SEARCH:     task_search → unified_search
HEALTH:     state_snapshot → cognitive_integrity
ADVANCED:   sequential_thinking → thought_evaluate → thought_to_plan
WEB:        web_snapshot → web_snapshots_list → task_link_url
```

---

## What's Next?

Once you've mastered these, explore:
- `sequential_thinking` — reasoning chains for complex problems
- `web_snapshot` — save web research permanently
- `thought_evaluate` — score your reasoning quality
- `model_add` — build a mental model of your domain
- `kanban_stats` — KPIs across all projects
