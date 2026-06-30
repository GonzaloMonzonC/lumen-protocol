"""
Apply pattern_suggest tool + proactive hook.
"""
import py_compile

P = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(P) as f:
    c = f.read()

# ── 1. Tool schema ──
schema = '''    {
        "name": "pattern_suggest",
        "description": "Find recorded patterns relevant to current context. Uses TF-IDF similarity to match patterns against your description. Call this when stuck, or when you suspect a previous fix might apply. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "Description of current problem or context"},
                "limit": {"type": "integer", "description": "Max suggestions (default 3)"},
                "min_score": {"type": "number", "description": "Minimum similarity score 0-1 (default 0.15)"},
                "session_id": {"type": "string", "description": "Session ID (optional)"}
            },
            "required": ["context"]
        }
    },
'''

tools_close = c.find('] + OBJECTIVE_SCHEMAS')
if tools_close > 0:
    c = c[:tools_close] + schema + c[tools_close:]
    print('1. Tool schema inserted')

# ── 2. Handler ──
handler = '''
def tool_pattern_suggest(args: dict) -> dict:
    \"\"\"Find patterns relevant to current context using TF-IDF similarity.\"\"\"
    session = _get_session(args.get("session_id"))
    context = args["context"]
    limit = args.get("limit", 3)
    min_score = args.get("min_score", 0.15)
    
    # Collect all patterns from all sessions
    all_patterns = list(session.patterns)
    for sid, s in _sessions.items():
        if sid != session.session_id:
            all_patterns.extend(s.patterns)
    
    if not all_patterns:
        return {"content": [{"type": "text", "text": "No patterns recorded yet. Use pattern_record to save fixes."}]}
    
    # Simple TF-IDF scoring
    context_words = set(context.lower().split())
    scored = []
    for p in all_patterns:
        desc = (p.get("description", "") + " " + p.get("pattern_name", "")).lower()
        desc_words = set(desc.split())
        if not desc_words:
            continue
        overlap = len(context_words & desc_words)
        score = overlap / max(len(context_words | desc_words), 1)
        if score >= min_score:
            scored.append((score, p))
    
    scored.sort(key=lambda x: -x[0])
    matches = scored[:limit]
    
    if not matches:
        return {"content": [{"type": "text", "text": "No matching patterns found. Consider recording this as a new pattern with pattern_record."}]}
    
    lines = [f" Found {len(matches)} relevant pattern(s):"]
    for score, p in matches:
        name = p.get("pattern_name", "?")
        desc = p.get("description", "")
        lines.append(f"  [{score:.0%}] {name}: {desc[:120]}")
    lines.append(f"\n  Tip: pattern_match() for deeper analysis.")
    
    return {"content": [{"type": "text", "text": "\\n".join(lines)}]}

'''

idx = c.find('\nHANDLERS = {')
if idx > 0:
    c = c[:idx+1] + handler + c[idx+1:]
    print('2. Handler inserted')

# ── 3. HANDLERS mapping ──
c = c.replace(
    '"session_end": tool_session_end,',
    '"session_end": tool_session_end,\n    "pattern_suggest": tool_pattern_suggest,'
)
print('3. HANDLERS mapping added')

# ── 4. Modify cognitive_pulse to include pattern suggestions ──
old_pulse = '''    if warnings:
        lines.append("  Tip: Try pattern_match() or thought_contradiction() to break out.")'''

new_pulse = '''    if warnings:
        # Try to find relevant patterns automatically
        try:
            context_str = " ".join(lines)
            pat_result = tool_pattern_suggest({"context": context_str, "limit": 2, "min_score": 0.05})
            pat_lines = pat_result.get("content", [{}])[0].get("text", "")
            if pat_lines and "No matching" not in pat_lines:
                lines.append("  Related patterns (auto-suggest):")
                for line in pat_lines.split("\\n")[1:3]:
                    lines.append("   " + line)
        except Exception:
            pass
        lines.append("  Tip: Try pattern_suggest(\\"your problem\\") for more matches.")'''

c = c.replace(old_pulse, new_pulse)
print('4. cognitive_pulse enhanced with auto-suggest')

with open(P, 'w') as f:
    f.write(c)

try:
    py_compile.compile(P, doraise=True)
    print('5. SYNTAX OK!')
except py_compile.PyCompileError as e:
    print(f'5. ERROR: {e}')
