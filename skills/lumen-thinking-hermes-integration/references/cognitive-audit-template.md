# Cognitive Audit Template

Example of a full LUMEN-powered dashboard audit (session 2026-06-19).

## Workflow

```
work_start → sequential_thinking (chain) → thought_evaluate → thought_to_plan → pattern_record → work_done
```

## Real Example: Dashboard Audit

### 1. Work Tracking
```
work_start: "Auditoría exhaustiva punto por punto del dashboard usando tools LUMEN" (category: audit)
Result: Work #10, completed in ~30min
```

### 2. Reasoning Chain
Chain: `chain_11_1781907202` — 6 thoughts analyzing every panel:
- Thought 1: Methodology (read code → identify data sources → validate API → test with curl → check JS)
- Thought 2: Cross-check — branches/revisions always 0 because features aren't exercised
- Thought 3: BUG #1 — model entities in totals but no list in /metrics
- Thought 4: BUG #2 — assumptions invisible
- Thought 5: BUG #3 — decisions invisible
- Thought 6: Summary + plan

### 3. Thought Evaluation
Scores: 7.7/10 (thought #2 — needed more actionability)

### 4. Actionable Plan (thought_to_plan)
6-step plan extracted from chain:
1. Audit methodology
2. Cross-check totals vs exposed arrays
3. Expose model[] in /metrics + add panel
4. Expose assumptions[] in /metrics + add panel
5. Expose decisions[] in /metrics + add panel
6. Final gap analysis

### 5. Bugs Recorded (pattern_record)
Pattern #11: `metrics-missing-detail-arrays` — Data stored in session but only exposed as counters, not detailed lists.

### 6. Fix Applied
Server: Added model[], assumptions[], decisions[] to /metrics return dict.
Dashboard: Added 3 panels — 🧠 Model, 📋 Decisions, ⏳ Assumptions with status colors.

### 7. Verification
```bash
curl -s http://localhost:9876/metrics | python -c "import sys,json; d=json.load(sys.stdin); print(len(d.get('model',[])), 'model entities')"
```

## Key Insight
The audit workflow turns LUMEN from passive tools into active cognitive infrastructure:
- Chain survives context compression (persistent reasoning)
- Patterns accumulate across sessions (compound interest)
- Wiki documents findings (institutional memory)
- Work log tracks time (ROI measurement)
