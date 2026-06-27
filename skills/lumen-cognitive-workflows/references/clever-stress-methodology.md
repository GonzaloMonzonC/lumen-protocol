# Clever Stress Testing Methodology

> **Lesson**: "No es cuestión de iteraciones, es cuestión de ser inteligente probando todo." — Gonzalo Monzón

## Principle

Brute-force volume testing (1000 iterations of the same tool) tells you almost nothing about real-world robustness. Clever stress testing targets **specific failure modes** with surgical precision. Each test is designed to expose a particular implicit assumption in the system.

## Test Categories

### 1. Unicode Resilience
- **What**: Entity names with Japanese (サービス🔥), emojis, RTL text, zero-width joiners
- **Why**: MCP servers write to stdout (UTF-8), JSON serializes to files, dashboards render HTML. Any encoding breakage corrupts state.
- **How**: `model_add(entity="サービス🔥-测试")`, `pattern_record(description="日本語 RTL עברית emoji 🎉")`. Verify round-trip with `model_query` and `pattern_match`.

### 2. Recursive Self-Reference
- **What**: Entity that depends on itself (`deps=["ouroboros"]` on entity "ouroboros")
- **Why**: Graph traversal algorithms often assume DAG (no cycles). A self-referencing node can cause infinite loops.
- **How**: `model_add(entity="ouroboros", deps=["ouroboros"])`. Verify `model_query("deps of ouroboros")` returns gracefully. Verify `model_map` renders without stack overflow.

### 3. Boundary Truncation
- **What**: Fill collections exactly to their truncation limit and add one more element
- **Why**: Slice operations (`list[-200:]`) must correctly drop the oldest element while keeping the newest
- **How**: Fill `_agent_messages` to exactly 200, add message #201. Verify message #1 is gone and #201 is present. Same for `_global_patterns` (500) and `_file_touches` (200).

### 4. Ghost Sessions
- **What**: Create sessions, add data, then never touch them again
- **Why**: Idle sessions should not consume growing resources (memory leak). `session_list` must track idle time correctly.
- **How**: `session_init` × 5, add patterns/model data, wait. Verify `session_list` shows increasing idle times without memory growth.

### 5. Cross-Tool Interference
- **What**: Run two tools simultaneously that access the same shared state
- **Why**: Dashboard HTTP requests and MCP tool calls share the same `_sessions` dict. No locking mechanism exists.
- **How**: Open dashboard (GET /metrics every 3s) while rapidly calling MCP tools. Verify /metrics never returns partial/corrupt JSON.

### 6. Save Atomicity
- **What**: Read `.thinking_state.json` while `_save_state()` is writing to it
- **Why**: `_save_state` uses `tmp + os.replace()` for atomic writes. Reading during the write window should always get the complete old version, never a partial new one.
- **How**: Loop `json.load()` on the state file while rapidly calling tools. Verify no `JSONDecodeError` occurs.

## Anti-Patterns

- ❌ 10,000 iterations of the same tool — tells you nothing about diversity of failure modes
- ❌ Only testing happy paths — the system works, you need to find where it doesn't
- ❌ Testing one subsystem at a time — real failures happen at subsystem boundaries
- ❌ Assuming benchmarks from docs are accurate — always verify empirically

## Execution Pattern

```python
# Each test returns: {test_name, result: PASS/FAIL, evidence: str, latency_ms: float}
# Tests are composed, not iterated:
TESTS = [
    unicode_bomb_test(),
    recursive_entity_test(),
    boundary_truncation_test(),
    ghost_session_test(),
]
# Volume only matters for throughput measurement, not correctness.
```
