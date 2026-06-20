# Lumen Thinking Tools – Usage Examples

This document demonstrates how to use the Lumen thinking tools (`sequential_thinking`, `assume`, `check_assumption`, `model_*`, `work_*`, `pattern_*`, etc.) to solve various types of problems. All examples were executed using only the Lumen toolset, without external lookup or internal reasoning outside the tool chain.

---

## Table of Contents
1. [Overview](#overview)
2. [Example 1 – Logic Puzzle (5 persons, profession, pet, drink)](#example-1--logic-puzzle)
3. [Example 2 – Spatial Reasoning (Cube Net)](#example-2--spatial-reasoning)
3. [Example 3 – Linguistic Riddle (Spanish)](#example-3--linguistic-riddle)
4. [Example 4 – Combination Puzzle (4×4 Sudoku‑like)](#example-4--combination-puzzle)
5. [How to Run the Examples](#how-to-run-the-examples)
6. [Additional Tool Combinations](#additional-tool-combinations)
7. [References](#references)

---

## Overview
Lumen thinking tools externalize the reasoning process, allowing the agent to:
- Keep chains of thoughts outside the context window (`sequential_thinking`).
- Record and validate hypotheses (`assume`, `check_assumption`).
- Build and query a persistent mental model (`model_*`).
- Track work items across sessions (`work_*`).
- Record and reuse bug/insight patterns (`pattern_*`).
- Preserve critical information across context compaction (`context_preserve`).

The examples below show each tool in action.

---

## Example 1 – Logic Puzzle
**Puzzle:** Five persons (Alice, Bob, Carol, David, Eve). Each has a distinct profession (Doctor, Engineer, Teacher, Writer, Chef), a distinct pet (Cat, Dog, Fish, Hamster, Parrot), and a distinct drink (Water, Tea, Coffee, Juice, Milk).  
Constraints:
1. Doctor has Cat.  
2. Engineer drinks Tea.  
3. Carol is Teacher.  
4. Person with Dog drinks Juice.  
5. David owns Parrot.  
6. Chef drinks Milk.  
7. Eve does NOT have Fish.

**Solution (one valid assignment):**
| Person | Profession | Pet    | Drink |
|--------|------------|--------|-------|
| Alice  | Doctor     | Cat    | Water |
| Bob    | Chef       | Hamster| Milk  |
| Carol  | Teacher    | Fish   | Coffee|
| David  | Engineer   | Parrot | Tea   |
| Eve    | –          | Dog    | Juice |

**Lumen Thinking Steps** (chain `puzzle1_chain`):
1. List entities (persons, professions, pets, drinks).  
2. List constraints.  
3. Consider David (Parrot).  
4. Consider Eve (no Fish).  
5. Attempt assignment satisfying all constraints.  
6. Final solution.

All steps were performed with `sequential_thinking` calls; no other thinking tools were needed for this deduction.

---

## Example 2 – Spatial Reasoning
**Puzzle:** Given a cube net (cross shape) with faces numbered as follows:
```
   [2]
[4][1][5]
   [3]
   [6]
```
When folded into a cube, which face is opposite face 2 (the top face)?

**Solution:** Face 2 (top) is opposite face 3 (bottom).

**Lumen Thinking Steps** (chain `puzzle2_chain`):
1. Describe the net layout.  
2. Explain folding: face 2 up → top, face 3 down → bottom, face 4 left → left, face 5 right → right, face 6 below face 3 folds down → back.  
3. Conclude that opposite of face 2 is face 3.

---

## Example 3 – Linguistic Riddle (Spanish)
**Riddle:** *¿Qué es lo que se rompe al nombrarlo?*  
**Answer:** *El silencio* (silence). Saying the word “silence” breaks the silence.

**Lumen Thinking Steps** (chain `puzzle3_chain`):
1. State the riddle.  
2. Consider what breaks when named (silence, secret, promise).  
3. Verify that naming silence breaks it → answer is silence.

---

## Example 4 – Combination Puzzle (4×4 Grid)
**Puzzle:** Fill a 4×4 grid with numbers 1‑4 such that each row and column contains each number exactly once. Given:
- (1,2) = 2  
- (2,3) = 3  
- (3,1) = 4  
- (4,4) = 1  

**Solution:**
```
3 2 1 4
1 4 3 2
4 1 2 3
2 3 4 1
```

**Lumen Thinking Steps** (chain `puzzle4_chain`):
1. Define coordinates and given values.  
2. Deduce possibilities for row 1, row 2, row 3 using column constraints.  
3. Iteratively eliminate options until a consistent grid emerges.  
4. Present the solved grid.

All deductions were performed with `sequential_thinking` calls.

---

## How to Run the Examples
Each example corresponds to a `sequential_thinking` chain stored in the session’s thinking server. To reproduce:
1. Start a Lumen thinking server (if not already running):
   ```bash
   python implementations/mcp-servers/thinking/server.py
   ```
2. Use the `sequential_thinking` tool to invoke each thought in order, setting `nextThoughtNeeded` appropriately and providing the `chainId` to continue the chain.
3. Optionally, verify intermediate results with `thought_evaluate`, `thought_contradiction`, or `model_add`/`model_query` for mental‑model integration.

For a quick test, you can run the full chain via a script that iteratively calls `sequential_thinking` with the thoughts shown above.

---

## Additional Tool Combinations
The thinking tools become even more powerful when combined with other Lumen subsystems:

- **Assumption Tracking:** Register a hypothesis with `assume`, later validate it with `check_assumption`.  
- **Mental Model:** Store discovered entities (e.g., “Doctor has Cat”) with `model_add`; retrieve with `model_query`; visualize relationships with `model_map`.  
- **Work Log:** Create a work item (`work_start`), break it into blocks (`work_block`), mark completion (`work_done`), and review progress (`work_log`).  
- **Pattern Recording:** Save a successful reasoning pattern with `pattern_record` for future reuse via `pattern_match`.  
- **Context Preservation:** Anchor critical info before a long chain with `context_preserve` and verify with `context_check`.  
- **Cross‑Session Persistence:** Use `work_start`/`work_log` to persist task progress across `/reset` sessions.  
- **Integration with Web Tools:** Feed results from `web_search`/`web_extract` into a thinking chain for evidence‑based reasoning.

These combinations enable complex, multi‑step workflows while keeping the agent’s reasoning transparent, revisable, and scalable.


## Example 5 – End‑to‑end workflow: hypothesis → web evidence → mental model → work tracking → pattern

**Goal:** Verify a factual hypothesis (e.g., "The capital of France is Paris") using web evidence, store the fact in the mental model, track the work, and record a reusable pattern.

**Steps:**

1. **Assume** a hypothesis with `assume`.
   ```text
   assume(statement="The capital of France is Paris.", category="integration")
   ```

2. **Web search** for confirmation (optional if you already know a source).
   ```text
   web_search(query="capital of France", limit=1)
   ```

3. **Web extract** the relevant page (e.g., Wikipedia) to obtain the source text.
   ```text
   web_extract(urls=["https://en.wikipedia.org/wiki/Paris"])
   ```

4. **Model add** store the fact in the mental model.
   ```text
   model_add(entity="CapitalOfFrance", properties={value="Paris", source="Wikipedia", fact="Paris is the capital and largest city of France"})
   ```

5. **Work tracking** – start a work item, create a block, and mark it done.
   ```text
   work_start(title="Verify capital of France", description="Check that the capital of France is Paris using web evidence and record in mental model.")
   work_block(block_id="verify_capital", status="in_progress")
   work_done(block_id="verify_capital")
   ```

6. **Pattern recording** – save the whole sequence as a reusable pattern.
   ```text
   pattern_record(pattern_name="CapitalVerification", description="Workflow: assume hypothesis about capital, web_search for confirmation, web_extract to get source, model_add to store fact, work_start/work_block/work_done to track task.")
   ```

All steps were performed using only Lumen tools, demonstrating how the thinking tools can be combined with web tools, mental model, work log, and pattern recording to build complex, evidence‑based workflows.


---

## References
- Lumen Thinking Server README: `implementations/mcp-servers/thinking/README.md`  
- Cognitive Workflows skill: `skills/lumen-cognitive-workflows/SKILL.md`  
- Benchmarks and performance data: `docs/benchmarks/internal/thinking-deep-benchmark-2026-06-19.md`  
- Acta de Revisión 1 (first evaluation): `acta_revision_1_2026-06-20.md`

--- 
*This document was generated using only Lumen thinking tools (`write_file`).*
