"""
Apply ALL state_feeling changes in one clean pass.
"""
import py_compile

P = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(P) as f:
    c = f.read()

# ── 1. TOOL SCHEMA in TOOLS list ──
tool_schema = '''    {
        "name": "state_feeling",
        "description": "Externalize current cognitive state — mood, confidence, energy. Persists and shows in dashboard.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["focused", "frustrated", "stuck", "tired", "confident", "curious", "overwhelmed", "neutral"],
                    "description": "Current cognitive/emotional state"
                },
                "confidence": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Confidence in current trajectory"},
                "energy": {"type": "integer", "minimum": 0, "maximum": 10, "description": "Mental energy level"},
                "context": {"type": "string", "description": "Optional context of what you're feeling"}
            },
            "required": ["mood", "confidence", "energy"]
        }
    },
'''

tools_close = c.find('] + OBJECTIVE_SCHEMAS')
if tools_close > 0:
    # Add comma after the previous tool (wiki_list ends with '}' no comma)
    # The insertion point is right before ']'
    # Look backwards for the last '}' and check if it already has a comma
    prev_end = c.rfind('}', 0, tools_close)
    if prev_end > 0:
        after_brace = c[prev_end:prev_end+5]
        if not after_brace.startswith('},'):
            # Need to insert comma after the '}'
            comma_pos = prev_end + 1
            # But don't add a second comma if there's already one somewhere nearby
            c = c[:comma_pos] + ',' + c[comma_pos:]
            # tools_close shifted by 1
            tools_close += 1
    
    c = c[:tools_close] + tool_schema + c[tools_close:]
    print('1. Tool schema inserted')
else:
    print('1. FAILED')

# ── 2. HANDLER FUNCTION ──
handler = '''
def tool_state_feeling(args: dict) -> dict:
    """Externalize current cognitive state."""
    session = _get_session(args.get("session_id"))
    mood = args["mood"]
    confidence = args.get("confidence", 5)
    energy = args.get("energy", 5)
    context = args.get("context", "")
    session.feeling = {"mood": mood, "confidence": confidence, "energy": energy, "context": context, "ts": time.time()}
    _auto_save(session)
    return {"content": [{"type": "text", "text": f"\U0001f9e0 Feeling recorded: {mood} (confidence={confidence}/10, energy={energy}/10)"}]}

'''

# Insert before TOOL_MAP
idx = c.find('TOOL_MAP = {')
if idx > 0:
    line_start = c.rfind('\n', 0, idx) + 1
    c = c[:line_start] + handler + c[line_start:]
    print('2. Handler inserted')
else:
    print('2. FAILED')

# ── 3. TOOL_MAP MAPPING ──
c = c.replace(
    '"cognitive_integrity": tool_cognitive_integrity,',
    '"cognitive_integrity": tool_cognitive_integrity,\n    "state_feeling": tool_state_feeling,'
)
print('3. Tool map entry added')

# ── 4. Session class ──
c = c.replace(
    'self.file_touches: list = []',
    'self.file_touches: list = []\n        self.feeling = None'
)
print('4. Session.__init__ field added')

c = c.replace(
    '"file_touches": self.file_touches,',
    '"file_touches": self.file_touches,\n            "feeling": self.feeling,'
)
print('5. Session.to_dict field added')

c = c.replace(
    's.file_touches = d.get("file_touches", [])',
    's.file_touches = d.get("file_touches", [])\n        s.feeling = d.get("feeling", None)'
)
print('6. Session.from_dict field added')

with open(P, 'w') as f:
    f.write(c)

try:
    py_compile.compile(P, doraise=True)
    print('7. ✅ SYNTAX OK!')
except py_compile.PyCompileError as e:
    print(f'7. ❌ {e}')
