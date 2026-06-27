# Proactive Cognitive System — Patterns & Pitfalls
## June 20, 2026

### What Changed

The cognitive system was transformed from **reactive** (waits for user to call tools)
to **proactive** (suggests patterns, reminds of work, auto-evaluates quality).

### Implemented Features

1. **Auto-evaluate on EVERY thought** (not just chains with 3+ thoughts)
   - Triggered inside `tool_sequential_thinking()` after adding a thought
   - Heuristic: specificity (length/200) + action words + numbers → score 0-10
   - Output: `🤖 Auto-scored: 9.7/10`
   
2. **`state_snapshot` proactive extras**
   - `⏰ N works >30min` — detects works active for >30min
   - `💡 N pattern suggestions` — based on keyword overlap with active chains
   
3. **`pattern_record` auto-suggestions**
   - When recording, checks all global patterns for >30% keyword overlap
   - Shows up to 3 similar patterns automatically
   - No manual `pattern_match` needed

4. **Work reminders**
   - Works with `status="in_progress"` and `started_at > 1800s ago` flagged automatically
   - Displayed in `state_snapshot()`

### Critical Bug Fixed

**Auto-trigger was silently broken for weeks.**

Root cause: `sequential_thinking()` defined the new thought as variable `thought_obj`
(line 864), but the auto-evaluate block referenced `new_thought` (line 915). 
The outer `try/except` caught the `NameError` silently — `except: pass` — so 
NOT A SINGLE THOUGHT was ever auto-scored.

Fix (commit bcada40):
```diff
- if not new_thought.get("score"):
+ if not thought_obj.get("score"):
+ thought_text = thought_obj["thought"]
+ thought_obj["score"] = score
```

Also removed two unnecessary imports that were also throwing exceptions inside the try:
```diff
- from server import tool_thought_evaluate as _eval
- _ = __import__('server', ...)
```

### Verification

After fix, create a thought with action words + numbers:
```
→ sequential_thinking("Test: crear build deploy 9876...")
→ Output includes: 🤖 Auto-scored: 8.3/10 ✅
```

### File Locking Cross-Process (Fixed)

When dashboard and MCP server share `.thinking_state.json`, Windows may lock
the file during reads, causing `os.replace()` to fail with `WinError 32`.

Fix:
- `_save_state()` retries `os.replace()` up to 5 times (10ms→20ms→40ms→80ms)
- Cleans stale `.tmp` files before writing
- Falls back to direct write on last attempt
- Verified: 500 wiki writes + 10 rapid saves with zero errors
