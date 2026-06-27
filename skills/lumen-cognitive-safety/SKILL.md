---
name: lumen-cognitive-safety
description: '👽 Ethical and technical guardrail for LUMEN cognitive tools — SAFE vs UNSAFE taxonomy, audit checklist, implementation rule, regression tests. All LUMEN tools prefixed 👽.'
version: 1.0.0
author: Cadences Lab
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [lumen, cognition, safety, ethics, audit]
---

# Lumen Cognitive Safety

> **Core Principle**: Tools must EXPAND perception, never REPLACE judgment.

Lumen Thinking includes 22 cognitive tools. Some surface blind spots; others could,
if misdesigned, automate decisions and introduce bias. This skill codifies the
safety taxonomy, audit process, and implementation rules that govern ALL Lumen
cognitive tools.

---

## Taxonomy: SAFE vs UNSAFE

### ✅ SAFE: Perception Expanders

Tools that **show more information** — the agent/user decides what to do with it:
- `assume` / `list_assumptions` / `check_assumption` — surfaces hidden premises
- `model_add` / `model_query` / `model_stats` / `model_map` / `model_remove` — factual graph
- `context_preserve` / `context_check` — retrieves lost info
- `context_estimate` — token count
- `thought_similarity`, `thought_summarize`, `thought_bridge`, `thought_to_plan` — informational

**Safety signature**: No recommendation, no ranking beyond objective metrics.

### ❌ UNSAFE: Judgment Replacers (DO NOT BUILD)

- Decision Journal, Confidence Tracker, Auto-Planner, Risk Calculator, Priority Ranker, Bias Detector

**Danger signature**: Output CONTAINS a recommendation, ranking, or decision dressed as fact.

### ⚠️ BORDERLINE: Extra Care Required

- `thought_evaluate` — scores are heuristics, label explicitly
- `thought_contradiction` — return strength 0-1, not binary
- `sequential_thinking` — chains expire (72h), never treat last thought as final

---

## Audit Checklist (7 Gates)

| # | Gate | Question |
|---|------|----------|
| 1 | Perception Test | Does tool SHOW (✅) or TELL (❌)? |
| 2 | Objectivity Test | Verifiable facts or subjective evaluations? |
| 3 | Authority Test | Could user treat output as authoritative? Add disclaimers. |
| 4 | Bias Amplification | Does it normalize past patterns into recommendations? |
| 5 | Overconfidence Test | Single number without error bars? Add uncertainty. |
| 6 | Reversibility | Can user easily override/ignore output? |
| 7 | Transparency | Algorithm documented? Steps inspectable? |

---

## Implementation Rule

```python
def safe_cognitive_tool_handler(args: dict) -> dict:
    result = compute_factual_output(args)
    disclaimer = {
        "_safety": "perception_expander",
        "_note": "This tool shows information. It does not make decisions. You are the decision-maker."
    }
    return {"content": [...], "data": result, "disclaimer": disclaimer}
    # ❌ NEVER: return {"recommendation": "Use option A", "confidence": 0.92}
```

---

## Governance

- New tools: pass 7-gate audit BEFORE implementation
- Existing tools: re-audited on major version bumps
- Safety regressions in CI
- Violations: tool blocked from registration