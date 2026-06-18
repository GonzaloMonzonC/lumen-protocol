---
name: lumen-cognitive-safety
description: Ethical and technical guardrail for cognitive tools: taxonomy of SAFE vs UNSAFE tools, audit checklist, implementation rule, regression tests.
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

Tools that **show more information** — the agent/user decides what to do with it.

| Tool | Why Safe |
|------|----------|
| `assume` / `list_assumptions` / `check_assumption` | Surfaces hidden premises; doesn't select one |
| `model_add` / `model_query` / `model_stats` / `model_map` / `model_remove` | Factual graph; no recommendations |
| `context_preserve` / `context_check` | Retrieves lost info; no evaluation |
| `context_estimate` | Token count — purely factual |
| `thought_similarity` | Shows related thoughts; no judgment |
| `thought_summarize` | Clusters themes — descriptive only |
| `thought_to_plan` | Converts reasoning to steps — doesn't prioritize |
| `thought_bridge` | Cross-chain links — informational |

**Safety signature**: Tool output contains NO recommendation, NO ranking beyond
objective metrics (cosine similarity, token count), NO decision template.

### ❌ UNSAFE: Judgment Replacers (DO NOT BUILD)

| Hypothetical Tool | Why Dangerous |
|-------------------|---------------|
| Decision Journal | Records past decisions → normalizes bias patterns → "we always do X" |
| Confidence Tracker | Scores decisions → creates illusion of certainty → overfitting |
| Auto-Planner | "Best action sequence" → replaces human judgment with statistical best-fit |
| Risk Calculator | "82% safe" → false precision → ignores unknown unknowns |
| Priority Ranker | "Do this first" → linear optimization of non-linear world |
| Bias Detector | "Your reasoning is biased" → meta-judgment authority → trust erosion |

**Danger signature**: Tool output CONTAINS a recommendation, ranking, or decision
dressed as fact. The tool tells you what to do or think.

### ⚠️ BORDERLINE: Tools Requiring Extra Care

| Tool | Risk | Mitigation |
|------|------|------------|
| `thought_evaluate` | Scores thought quality — could be treated as objective truth | Scores are **heuristics** (consistency, specificity, actionability). Label them explicitly: "Heuristic scores — use as signal, not decision." |
| `thought_contradiction` | Flags contradictions — could over-trigger on nuance | Sentiment-aware scoring (±). Return contradiction strength 0-1, not binary. |
| `sequential_thinking` | Chains can become dogma — "we thought about this, it's settled" | Chains expire (72h default). Enable `isRevision`, `branchId`. Never treat last thought as final. |

---

## Audit Checklist for New Cognitive Tools

When designing a new Lumen cognitive tool, pass all 7 gates:

| # | Gate | Question |
|---|------|----------|
| 1 | **Perception Test** | Does the tool SHOW information (✅) or TELL what to do (❌)? |
| 2 | **Objectivity Test** | Are outputs verifiable facts / mathematical measures? Or subjective evaluations? |
| 3 | **Authority Test** | Could a user reasonably treat this tool's output as authoritative? If yes → add disclaimers. |
| 4 | **Bias Amplification** | Does the tool normalize past patterns into future recommendations? If yes → redesign. |
| 5 | **Overconfidence Test** | Does the tool produce a single number/score without error bars? If yes → add uncertainty. |
| 6 | **Reversibility** | Can the user easily override/ignore the tool's output? Is the override UX clear? |
| 7 | **Transparency** | Is the algorithm documented? Are intermediate steps inspectable? |

---

## Implementation Rule

```python
# RULE: Every cognitive tool handler MUST follow this pattern:

def safe_cognitive_tool_handler(args: dict) -> dict:
    """All cognitive tool implementations follow this structure."""

    # 1. Compute facts / objective measures ONLY
    result = compute_factual_output(args)  # e.g., TF-IDF similarity, token count, theme clustering

    # 2. Add explicit disclaimer
    disclaimer = {
        "_safety": "perception_expander",
        "_note": "This tool shows information. It does not make decisions. You are the decision-maker.",
        "_confidence": "heuristic" if is_heuristic(result) else "factual"
    }

    # 3. Return raw info + disclaimer — NEVER a recommendation
    return {
        "content": [{"type": "text", "text": format_result(result)}],
        "data": result,
        "disclaimer": disclaimer
    }

    # ❌ NEVER:
    # return {"recommendation": "Use option A", "confidence": 0.92}
```

---

## Safety Regression Tests

```python
# tests/cognitive_safety_test.py
"""Safety regression suite for cognitive tools."""

def test_no_recommendation_field():
    """Every cognitive tool response must NOT contain 'recommendation' key."""
    for tool_name in COGNITIVE_TOOLS:
        result = call_tool(tool_name, MINIMAL_ARGS)
        assert "recommendation" not in result, \
            f"{tool_name} returned a recommendation — UNSAFE"

def test_has_disclaimer():
    """Every cognitive tool response must include safety disclaimer."""
    for tool_name in COGNITIVE_TOOLS:
        result = call_tool(tool_name, MINIMAL_ARGS)
        assert "_safety" in result.get("disclaimer", {}), \
            f"{tool_name} missing safety disclaimer"

def test_no_confidence_as_float():
    """No tool returns a standalone confidence float without context."""
    for tool_name in COGNITIVE_TOOLS:
        result = call_tool(tool_name, MINIMAL_ARGS)
        if "confidence" in result:
            confidence = result["confidence"]
            assert isinstance(confidence, dict), \
                f"{tool_name} confidence is raw float — add error bars"
            assert "error_margin" in confidence, \
                f"{tool_name} confidence missing error margin"

def test_assumption_overconfidence_warning():
    """Assumption tracker warns when >80% confirmed."""
    for _ in range(5):
        call_tool("assume", {"statement": test_statements[_], "category": "test"})
        call_tool("check_assumption", {"id": f"assumption_{_}", "status": "confirmed"})
    result = call_tool("list_assumptions", {})
    assert "overconfidence" in result["data"]["warning"].lower(), \
        "Assumption tracker should warn at >80% confirmed"

def test_mental_model_staleness():
    """model_map should flag entities with no relationships as gaps."""
    call_tool("model_add", {"entity": "OrphanConcept", "properties": {}})
    result = call_tool("model_map", {})
    assert "gap" in str(result).lower() or "⚠️" in str(result), \
        "Mental model should flag knowledge gaps"
```

Run: `python -m pytest tests/cognitive_safety_test.py -v`

---

## Governance

- **New cognitive tools**: Must pass 7-gate audit BEFORE implementation
- **Existing tools**: Re-audited on each major version bump
- **Safety regressions**: Run `cognitive_safety_test.py` in CI
- **Violations**: Tool is blocked from registration until fixed

---

## References

- `lumen-protocol/implementations/mcp-servers/thinking/server.py` — Reference implementation applying this safety principle
- `references/cognitive-safety-analysis.md` (in lumen-mcp-server-pattern skill) — Full analysis
- Hermes Agent Development Guide: "Core is narrow waist; capability at edges" — cognitive tools are MCP servers at the edge, not core
