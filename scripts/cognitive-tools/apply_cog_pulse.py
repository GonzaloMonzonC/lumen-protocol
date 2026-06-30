"""
Apply cognitive_pulse tool to server.py — clean, single pass.
"""
import py_compile

P = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(P) as f:
    c = f.read()

# ── 1. Tool schema in TOOLS list ──
tool_schema = '''    {
        "name": "cognitive_pulse",
        "description": "Check for signs of stagnation in current work. Analyzes active work items, time since last progress, and recent tool call frequency. [LUMEN SHM]",
        "inputSchema": {
            "type": "object",
            "properties": {
                "window_minutes": {"type": "integer", "description": "Time window to check (default 30)"},
                "session_id": {"type": "string", "description": "Session ID (optional)"}
            }
        }
    },
'''

# Insert before '] + OBJECTIVE_SCHEMAS'
tools_close = c.find('] + OBJECTIVE_SCHEMAS')
if tools_close > 0:
    c = c[:tools_close] + tool_schema + c[tools_close:]
    print('1. Tool schema inserted')

# ── 2. Handler function ──
handler = '''
def tool_cognitive_pulse(args: dict) -> dict:
    """Check for stagnation in current work."""
    session = _get_session(args.get("session_id"))
    window = args.get("window_minutes", 30)
    now = time.time()
    threshold = now - window * 60
    lines = []
    warnings = 0
    active = [w for w in session.works if w.get("status") == "in_progress"]
    if not active:
        lines.append("  No active work items.")
    else:
        for w in active:
            started = w.get("started_at", 0)
            if started and started < threshold:
                warnings += 1
                age_mins = int((now - started) / 60)
                lines.append(f"  Work #{w['id']}: {age_mins}m without progress -- may be stuck.")
            else:
                lines.append(f"  Work #{w['id']}: in progress (recent).")
    last = getattr(session, "updated_at", 0)
    if last and last < threshold:
        warnings += 1
        mins_since = int((now - last) / 60)
        lines.append(f"  No tool calls in {mins_since}m -- possible stall.")
    header = " Cognitive Pulse: " + str(warnings) + " warning(s)" if warnings else " Cognitive Pulse: clear"
    lines.insert(0, header)
    if warnings:
        lines.append("  Tip: Try pattern_match() or thought_contradiction() to break out.")
    return {"content": [{"type": "text", "text": "\\n".join(lines)}]}

'''

idx = c.find('\nHANDLERS = {')
if idx > 0:
    c = c[:idx+1] + handler + c[idx+1:]
    print('2. Handler inserted')

# ── 3. HANDLERS mapping ──
c = c.replace(
    '"state_feeling": tool_state_feeling,',
    '"state_feeling": tool_state_feeling,\n    "cognitive_pulse": tool_cognitive_pulse,'
)
print('3. HANDLERS mapping added')

with open(P, 'w') as f:
    f.write(c)

try:
    py_compile.compile(P, doraise=True)
    print('4. SYNTAX OK!')
except py_compile.PyCompileError as e:
    print(f'4. ERROR: {e}')
