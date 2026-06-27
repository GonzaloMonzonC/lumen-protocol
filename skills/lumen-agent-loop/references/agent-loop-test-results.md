# Agent Loop — Verified End-to-End Test (June 2026)

Test objective: "Test Agent Loop — mini agente autónomo"
Acceptance criteria: 4 items (create, judge, plan, status)
Tools tested: objective_create, objective_judge, objective_plan, objective_status
Thinking server: active on :9876 (PID 8968/27884), bridge plugin registered all 4 tools.

## Test Sequence

### 1. objective_create

```
Input:  {title, description, criteria=[4 items]}
Output: 🎯 Objective #goal_1: Test Agent Loop — mini agente autónomo
           Phase: BUILDER | Score: 8/10
           Clarity score 8/10. Ready to plan.
```
- Score 8/10 → verdict READY (triggers BUILDER→BUILDING transition on next judge)
- Phase stays BUILDER during create; transition happens in objective_judge

### 2. objective_judge

```
Input:  {goal_id: "goal_1"}
Output: ⚖️ Judge — Test Agent Loop — mini agente autónomo
           Phase: BUILDING | Score: 8/10
           Verdict: READY
           Clarity score 8/10. Ready to plan.
```
- Transitions phase BUILDER → BUILDING when score ≥ 8
- Verdict READY means objective is clear enough to plan

### 3. objective_plan

```
Input:  {goal_id: "goal_1"}
Output: 📋 Planner — Test Agent Loop — mini agente autónomo
           5 tasks created:
           • Implement: Recibir confirmación de que objective_create funciona
           • Implement: objective_judge devuelve score y verdict
           • Implement: objective_plan genera subtareas de los criteria
           • Implement: objective_status muestra barra de progreso
           • Verify all criteria for: Test Agent Loop — mini agente autónomo
```
- 1 task per criterion + 1 verification task = N+1 tasks
- Tasks are internal objects (obj["tasks"]) — NOT kanban MCP tasks
- Planner only runs when phase is "building" or "testing"

### 4. objective_status

```
Input:  {goal_id: "goal_1"}
Output: ⚙️ goal_1: Test Agent Loop — mini agente autónomo
           Phase: BUILDING | Score: 8/10
           Tasks: ░░░░░░░░░░ 0/5
```
- Bar: █=done, ░=pending. 10 segments.
- Works with or without goal_id (omitting shows all objectives)

## Key Behavioral Notes

| Aspect | Behaviour |
|--------|-----------|
| Phase transition | `objective_judge` moves phases, not `objective_create` |
| Score heuristic | Clarity (0-5) + criteria count (0-3) + examples (0-2) = 0-10 |
| Building judge | `completion * 7 + verified_criteria * 3` — score < 8 → LOOP |
| Testing judge | `(passed/total) * 10` — score < 10 → FIX |
| Tasks created | Internal `obj["tasks"]` dict, not MCP kanban tasks |
| State persistence | Via `get_objective_state()` / `load_objective_state()` in server.py save/load cycle |
| Dashboard panel | Pending (not yet implemented) |

## Architecture

```
objective_loop.py (317 lines)
  ├── _judge_objective() — heuristic scorer (0 LLM tokens)
  ├── tool_objective_create()
  ├── tool_objective_judge()
  ├── tool_objective_plan()
  ├── tool_objective_status()
  └── OBJECTIVE_HANDLERS, OBJECTIVE_SCHEMAS, get/load_objective_state()

server.py:
  Line 36:  from objective_loop import ...
  Line 1012: TOOLS = [...] + OBJECTIVE_SCHEMAS
  Line 3429: HANDLERS = {..., **OBJECTIVE_HANDLERS}

bridge __init__.py:
  Lines 1402-1419: 4 tools registered with _make_thinking_handler("objective_*")
  Toolset: lumen-shm
```
