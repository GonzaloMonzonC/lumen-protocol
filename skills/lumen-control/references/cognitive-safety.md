# Cognitive Safety — Principles for LUMEN Thinking Tools

*Discovered in session 2026-06-17. Gonzalo raised the critical question.*

## The Core Principle

> **Tools must EXPAND the agent's perception — never REPLACE its judgment.**

A tool that makes decisions FOR the agent is dangerous.
A tool that shows the agent MORE information is safe.

## Dangerous Tools (REJECTED)

| Tool | Risk | Why Rejected |
|------|------|-------------|
| **Decision Journal** | Confirmation bias, over-generalization | "Postgres was good last time" → apply blindly to every project. 3 examples are not statistics. |
| **Confidence Tracker** | Dogmatism, overfitting | "I'm 80% accurate on auth bugs" → ignore other possibilities. Small samples mislead. |

These are dangerous because they **automate reasoning** — the tool decides what worked before and the agent follows blindly.

## Safe Tools (BUILT)

| Tool | What it does | Why safe |
|------|-------------|----------|
| **Assumption Tracker** (`assume`, `list_assumptions`, `check_assumption`) | Records explicit assumptions, shows blind spots | Shows what the agent DOESN'T know. The user sees and corrects. Expands awareness. |
| **Mental Model Builder** (`model_add`, `model_query`, `model_stats`, `model_map`, `model_remove`) | Builds factual graph of project: files, roles, dependencies | Purely factual — no opinions. Shows structure, not decisions. |
| **Context Decay Detector** (`context_preserve`, `context_check`) | Marks critical info to preserve from context compression | Shows what's at risk. The agent decides what to keep. |

## Safety Checklist for New Cognitive Tools

Before building a new cognitive tool, verify:

1. **Does it expand perception or replace judgment?**
   - EXPAND ✅: shows me blind spots, maps facts, warns of risks
   - REPLACE ❌: decides for me, automates choices, predicts outcomes

2. **Is it factual or opinionated?**
   - FACTUAL ✅: files, dependencies, timestamps, recorded statements
   - OPINIONATED ❌: "this was good", "you're 80% accurate", "optimal choice"

3. **Can it introduce bias?**
   - LOW RISK ✅: purely informational, no feedback loop
   - HIGH RISK ❌: learns from outcomes, creates self-fulfilling prophecies

4. **What happens with small samples?**
   - SAFE ✅: works the same with 3 or 300 items
   - DANGEROUS ❌: "learns" from 5 examples, overgeneralizes

## Recovery Path for Rejected Tools

Decision Journal and Confidence Tracker could be rescued as **manual reflection tools**:
- Used ONLY post-mortem, at user's request
- NEVER automatically triggered
- Results are shown to the user for discussion, not used by the agent

This was NOT implemented in this session — left for future consideration.
