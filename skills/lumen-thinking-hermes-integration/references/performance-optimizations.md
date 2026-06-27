# Performance Optimizations for LUMEN Thinking + Hermes Integration
# Added June 20, 2026

## Compact sequential_thinking Output

Default mode shows ONLY the last thought (100 chars). Pass `verbose: true` for full 5-thought history.
Token savings: ~300 tokens/call, ~6000 tokens per 20-call session.

Implementation in `tool_sequential_thinking`:
```python
verbose = args.get("verbose", False)
if verbose and chain["thoughts"]:
    # Show full recent history (5 thoughts)
elif chain["thoughts"]:
    last = chain["thoughts"][-1]
    summary_lines.append(f"   Last: #{last['number']}: {last['thought'][:100]}")
```

Add to tool inputSchema:
```json
{"verbose": {"type": "boolean", "description": "Show full recent history", "default": false}}
```

## Auto-Evaluate on Chains with 3+ Thoughts

When a chain reaches 3+ thoughts, `tool_sequential_thinking` auto-scores the new thought.
Same heuristic as `thought_evaluate`:
- specificity = min(thought_length / 200, 1.0) * 10
- action_verbs = 10 if thought contains action keywords, else 3
- numbers = 10 if thought contains digits, else 5
- score = average of the three

Score stored silently on thought object (`new_thought["score"] = score`).
Visible in dashboard chain modals and `/metrics` scores. 
Never breaks main tool flow (try/except wrapped).

## Dashboard Refresh Performance

- Interval: 10s (was 3s — caused CPU saturation with 30+ innerHTML assignments per cycle)
- Canvas ID comparison: only redraws if `JSON.stringify(newData) !== lastStr`
- System Pulse: only updates if `works[]` array changed

## Plugin Auto-Dashboard

The Hermes plugin spawns `server_shm.py` with `--dashboard 9876`.
Dashboard HTTP server runs inside the same subprocess.
Eliminates zombie port conflicts — single process, no stale ports.

Plugin spawn code:
```python
cmd = [_HERMES_VENV_PYTHON, "-u", self.server_path]
if "thinking" in str(self.server_path):
    cmd.extend(["--dashboard", "9876"])
```

## Cluster Clickable Modals

Clusters from `thought_summarize` are stored per-session, NOT per-chain.
The `/chain?chain_id=X` endpoint returns `thoughts[]` but not `clusters[]`.

Fix: use in-memory `window._lastClusters` populated during refresh:
```javascript
window._lastClusters = d.clusters || [];
// Modal accesses: window._lastClusters.filter(c => c.chain_id === cid)
```
