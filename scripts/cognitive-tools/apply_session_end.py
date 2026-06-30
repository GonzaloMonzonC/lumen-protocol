"""
Apply session_end tool to server.py — clean single pass.
"""
import py_compile

P = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(P) as f:
    c = f.read()

# ── 1. Tool schema ──
tool_schema = '''    {
        "name": "session_end",
        "description": "End-of-session ritual. Verifies open works, suggests closing them, checks for unlogged decisions and unrecorded patterns. Creates a final state snapshot. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID (optional)"}
            }
        }
    },
'''

tools_close = c.find('] + OBJECTIVE_SCHEMAS')
if tools_close > 0:
    c = c[:tools_close] + tool_schema + c[tools_close:]
    print('1. Tool schema inserted')

# ── 2. Handler ──
handler = '''
def tool_session_end(args: dict) -> dict:
    """End-of-session ritual: verify works, decisions, patterns, snapshot."""
    session = _get_session(args.get("session_id"))
    lines = []
    warnings = 0

    # Check open works
    active = [w for w in session.works if w.get("status") == "in_progress"]
    if active:
        warnings += 1
        lines.append(f"  {len(active)} work(s) still in_progress:")
        for w in active:
            lines.append(f"    - #{w['id']}: {w.get('item', w.get('title', '?'))}")
        lines.append("  Suggestion: work_done(work_id=N) for each.")
    else:
        lines.append("  All works closed.")

    # Check decisions
    if session.decisions:
        lines.append(f"  {len(session.decisions)} decision(s) logged.")
    else:
        lines.append("  No decisions logged this session.")

    # Check patterns
    if session.patterns:
        lines.append(f"  {len(session.patterns)} pattern(s) recorded.")
    else:
        lines.append("  No patterns recorded this session.")

    # Snapshot
    _save_state()
    lines.append(f"  State snapshot saved.")

    summary = f" Session End: {warnings} item(s) need attention" if warnings else " Session End: clean"
    lines.insert(0, summary)
    return {"content": [{"type": "text", "text": "\\n".join(lines)}]}

'''

idx = c.find('\nHANDLERS = {')
if idx > 0:
    c = c[:idx+1] + handler + c[idx+1:]
    print('2. Handler inserted')

# ── 3. HANDLERS mapping ──
c = c.replace(
    '"cognitive_pulse": tool_cognitive_pulse,',
    '"cognitive_pulse": tool_cognitive_pulse,\n    "session_end": tool_session_end,'
)
print('3. HANDLERS mapping added')

with open(P, 'w') as f:
    f.write(c)

try:
    py_compile.compile(P, doraise=True)
    print('4. SYNTAX OK!')
except py_compile.PyCompileError as e:
    print(f'4. ERROR: {e}')
