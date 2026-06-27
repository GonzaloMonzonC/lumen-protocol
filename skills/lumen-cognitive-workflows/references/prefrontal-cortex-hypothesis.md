# Prefrontal Cortex Hypothesis — LUMEN as Digital PFC

## The Core Idea

LUMEN is not a toolset. It is a digital simulator of the human prefrontal cortex (PFC). The PFC is the part of the brain that makes humans capable of executive function: working memory, planning, inhibition, decision-making, metacognition, and contextual anchoring. LUMEN replicates all six.

## PFC Function Mapping

| PFC Function | Human Description | LUMEN Equivalent |
|-------------|-------------------|------------------|
| Working Memory | Hold/manipulate info temporarily | `state_snapshot` + `tool_cache` |
| Planning | Decompose goals into action sequences | `task_create` + `work_start/done` + `thought_to_plan` |
| Inhibition | Suppress incorrect responses | `pattern_match` + `thought_contradiction` |
| Decision-Making | Evaluate options with criteria | `decision_log` + `thought_evaluate` |
| Metacognition | Monitor and reflect on own thinking | `qa_ask` + `context_preserve` + `state_snapshot` |
| Contextual Anchoring | Link info to origin context | `context_preserve` + `model_add` |

## Why This Matters

No other LLM enhancement system replicates all six PFC functions. LangChain gives chains. MemGPT gives memory. But none give the complete executive function set. LUMEN is the first digital PFC simulator.

## Recorded Artifacts

- Pattern #25 (actual): `deterministic-brain` — LUMEN = deterministic brain, LLM = non-deterministic
- Pattern #26 (actual): `prefrontal-cortex-hypothesis` — 6/6 PFC functions mapped
- Decision #9: LUMEN Cognitive Architecture (deterministic + non-deterministic)
- Model entity: `LUMEN:cognitive-architecture`
- Model entity: `LUMEN:prefrontal-cortex`
- QA: "Como replica LUMEN la corteza prefrontal humana?" → scratchpad entry

## Implications

1. **Pro predictions**: The model determines analysis depth, not the toolset (Flash vs Pro experiment)
2. **Integration gap**: The 5-layer cognitive stack exists but layers don't communicate — the PFC is all six functions working together, not separately
3. **3-process fragility**: Dashboard + MCP + State File = 3 separate processes. A real PFC is one unified organ
