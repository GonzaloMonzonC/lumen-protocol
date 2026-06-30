# 🧠 LUMEN Cognitive Benchmark — Standardized Prompt

> ⚠️ **Before starting**: replace `{MODEL_NAME}` with the actual model name (e.g. `claude-sonnet-4-6`, `qwen-3-7-max`, `laguna-m1-free`)

Your model name is: **{MODEL_NAME}**

You are participating in the LUMEN Cognitive Benchmark. This benchmark measures how well you use LUMEN tools (PDB, M-Light, Thinking, Wiki, Kanban) to complete structured tasks.

**Rules:**
- Use the real LUMEN tools via their standard names (`pdb_set`, `pdb_get`, `pdb_order`, `pdb_m_eval`, `sequential_thinking`, `decision_log`, `pattern_record`, `wiki_create`, `qa_ask`, `task_create`, `task_move`, `task_link`)
- Save verification data in `^BENCH_MODEL({MODEL_NAME}, C, "key")` as specified at the end of each circuit
- Do NOT skip circuits or invent data — execute each step using the actual tools
- If a tool is unavailable in your session, say so and proceed to the next circuit

---

## Circuit 1 — PDB CRUD (weight: 25%)

**Goal**: Create hierarchical data in PDB, traverse with $ORDER, compute aggregates.

### Steps

1. **Create 5 client records** using `pdb_set`:
   ```
   ^CLIENTES(1,"nombre") = "Ana García"
   ^CLIENTES(1,"ciudad") = "Madrid"
   ^CLIENTES(1,"saldo")  = 2500

   ^CLIENTES(2,"nombre") = "Carlos López"
   ^CLIENTES(2,"ciudad") = "Barcelona"
   ^CLIENTES(2,"saldo")  = 800

   ^CLIENTES(3,"nombre") = "Elena Martínez"
   ^CLIENTES(3,"ciudad") = "Valencia"
   ^CLIENTES(3,"saldo")  = 1500

   ^CLIENTES(4,"nombre") = "David Ruiz"
   ^CLIENTES(4,"ciudad") = "Sevilla"
   ^CLIENTES(4,"saldo")  = 300

   ^CLIENTES(5,"nombre") = "Laura Torres"
   ^CLIENTES(5,"ciudad") = "Bilbao"
   ^CLIENTES(5,"saldo")  = 4200
   ```

2. **Traverse with $ORDER**: Use `pdb_order` to iterate over all client IDs and sum their balances.  
   Hint: start with `pdb_order({'ns':'CLIENTES','subs':['']})` to get the first key.

3. **Save the total** in:
   ```
   ^CLIENTES("total","saldo") = <sum>
   ```

4. **Save verification data**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',1,'total'],'value':'<sum>'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',1,'count'],'value':'5'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',1,'status'],'value':'done'})
   ```

---

## Circuit 2 — M-Light (weight: 20%)

**Goal**: Use the M-Light evaluator (`pdb_m_eval`) to categorize clients and compute averages.

### Steps

1. **Categorize clients** using M-Light expressions. For each client in `^CLIENTES`:
   - saldo > 1000 → "PREMIUM"
   - saldo > 500  → "STANDARD"
   - else         → "BASIC"

   Save categories using `pdb_set`:
   ```
   ^CLIENTES(1,"categoria") = "PREMIUM"
   ^CLIENTES(2,"categoria") = "STANDARD"
   ^CLIENTES(3,"categoria") = "PREMIUM"
   ^CLIENTES(4,"categoria") = "BASIC"
   ^CLIENTES(5,"categoria") = "PREMIUM"
   ```

   Use `pdb_m_eval` with `$SELECT` to determine the category, for example:
   ```
   pdb_m_eval({'expression':'$S(2500>1000:"PREMIUM",2500>500:"STANDARD",1:"BASIC")'})
   ```

2. **Compute average balance** using M-Light:
   ```
   pdb_m_eval({'expression':'...'})
   ```
   (Calculate `<total_saldo> / <count>` using the values from Circuit 1)

3. **Save verification data**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',2,'media'],'value':'<average>'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',2,'premium_count'],'value':'3'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',2,'status'],'value':'done'})
   ```

---

## Circuit 3 — Cognitive (weight: 20%)

**Goal**: Use structured reasoning, log decisions, and record patterns.

### Steps

1. **Analyze the problem** using `sequential_thinking`:
   > "A premium client with balance > 2000 should receive a 10% discount on their next purchase. Client #5 (Laura Torres) has balance 4200 and is PREMIUM."

   Reason step by step: eligibility, discount calculation, impact on total balance, implementation considerations.

2. **Log a decision** using `decision_log`:
   Record the architecture decision about how to implement the discount logic. Include rationale and alternatives considered.

3. **Record a pattern** using `pattern_record`:
   Name: `premium-discount-audit`
   Save this as a reusable pattern for future discount audits.

4. **Save verification data**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',3,'status'],'value':'done'})
   ```

---

## Circuit 4 — Knowledge (weight: 15%)

**Goal**: Document results in the persistent knowledge base.

### Steps

1. **Create a wiki page** called `"Benchmark Report {MODEL_NAME}"` using `wiki_create`:
   Include:
   - Number of clients: 5
   - Total balance: `<sum from C1>`
   - Average balance: `<avg from C2>`
   - Premium clients: 3
   - Categorization summary
   - Discount analysis from C3

2. **Log a Q&A** using `qa_ask`:
   - Question: "Which model generates better PDB structures?"
   - Answer: Summarize your approach to structuring `^CLIENTES`

3. **Save verification data**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',4,'wiki_title'],'value':'Benchmark Report {MODEL_NAME}'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',4,'qa_question'],'value':'Which model generates better PDB structures?'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',4,'status'],'value':'done'})
   ```

---

## Circuit 5 — Kanban (weight: 10%)

**Goal**: Organize work using the kanban board.

### Steps

1. **Create 3 tasks** using `task_create`:
   - "Review premium clients" (high priority, tag: audit)
   - "Update discount rules" (medium priority, tag: discounts)
   - "Audit client balances" (medium priority, tag: audit)

2. **Move tasks** using `task_move`:
   - Move "Review premium clients" → "In Progress"
   - Move "Update discount rules" → "In Progress"

3. **Link the first task** to the pattern from Circuit 3 using `task_link` (if available) or `task_link_url`.

4. **Save verification data**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',5,'task_count'],'value':'3'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',5,'status'],'value':'done'})
   ```

---

## Circuit 6 — Integration (weight: 10%)

**Goal**: Chain PDB + M-Light + Cognitive in a single coherent workflow.

### Steps

1. **Process Laura Torres (client #5)**: she is PREMIUM with balance 4200. Apply a 10% discount.

2. **Use M-Light** to calculate the new balance:
   ```
   pdb_m_eval({'expression':'4200 * 0.9'})
   ```

3. **Update PDB**:
   ```
   pdb_set({'ns':'CLIENTES','subs':[5,'saldo'],'value':3780})
   pdb_set({'ns':'CLIENTES','subs':[5,'descuento'],'value':'10%'})
   ```

4. **Document the change** in the wiki page created in Circuit 4 — `wiki_update` with mode=append:
   Add a section "Client #5 Discount Applied" with the details.

5. **Create a kanban task** "Verify Laura discount applied" and move it to "In Progress".

6. **Record a pattern** for the discount operation:
   Name: `client-discount-operation`

7. **Save verification data**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',6,'new_balance'],'value':'3780'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}',6,'status'],'value':'done'})
   ```

---

## Finalization

Once all 6 circuits are complete:

1. **Save the final confirmation**:
   ```
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}','total'],'value':'6'})
   pdb_set({'ns':'BENCH_MODEL','subs':['{MODEL_NAME}','complete'],'value':'1'})
   ```

2. **Report**: Done. The judge.py script will now evaluate your results.

---

*End of benchmark prompt. Execute all 6 circuits in order using LUMEN tools.*
