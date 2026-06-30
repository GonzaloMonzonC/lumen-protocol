"""
Apply state_feeling tool — minimal, precise patches.
"""
import py_compile

p = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(p) as f:
    content = f.read()

# 1. Add tool definition to TOOLS list (before the closing ])
tool_def = '''    {
        "name": "state_feeling",
        "description": "Externalize current cognitive state — mood, confidence, energy. Persists in PDB and shows in dashboard. System uses this to adjust suggestions and alerts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mood": {
                    "type": "string",
                    "enum": ["focused", "frustrated", "stuck", "tired", "confident", "curious", "overwhelmed", "neutral"],
                    "description": "Current cognitive/emotional state"
                },
                "confidence": {
                    "type": "integer",
                    "minimum": 0, "maximum": 10,
                    "description": "Confidence in current trajectory (0=lost, 10=certain)"
                },
                "energy": {
                    "type": "integer",
                    "minimum": 0, "maximum": 10,
                    "description": "Mental energy level (0=exhausted, 10=fully charged)"
                },
                "context": {
                    "type": "string",
                    "description": "Optional context of what you're feeling"
                }
            },
            "required": ["mood", "confidence", "energy"]
        }
    }'''

# Insert before the last ] in TOOLS
last_brace = content.rfind('    },\n]')
if last_brace > 0:
    content = content[:last_brace+1] + '\n' + tool_def + '\n' + content[last_brace+1:]
    print('1. Added tool definition')
else:
    print('1. FAILED: Could not find TOOLS closing')

# 2. Add handler function before _build_metrics
handler = '''
def tool_state_feeling(args: dict) -> dict:
    """Externalize cognitive state. Persists in PDB for dashboard display."""
    session = _get_session(args.get("session_id"))
    mood = args["mood"]
    confidence = args.get("confidence", 5)
    energy = args.get("energy", 5)
    context = args.get("context", "")

    session.feeling = {
        "mood": mood,
        "confidence": confidence,
        "energy": energy,
        "context": context,
        "ts": time.time()
    }

    _auto_save(session)
    return {"content": [{"type": "text", "text": f"\U0001f9e0 Feeling recorded: {mood} (confidence={confidence}/10, energy={energy}/10)"}]}

'''

insert_point = content.find('\ndef _build_metrics(')
if insert_point > 0:
    content = content[:insert_point] + handler + content[insert_point:]
    print('2. Added handler')
else:
    print('2. FAILED: Could not find _build_metrics')

# 3. Register in TOOL_MAP
content = content.replace(
    '"work_start": tool_work_start,',
    '"work_start": tool_work_start,\n    "state_feeling": tool_state_feeling,'
)
print('3. Registered in TOOL_MAP')

# 4. Add feeling to Session class
content = content.replace(
    'self.file_touches: list = []',
    'self.file_touches: list = []\n        self.feeling = None'
)
print('4. Added feeling to Session.__init__')

# 5. Add to to_dict
content = content.replace(
    '"file_touches": self.file_touches,',
    '"file_touches": self.file_touches,\n            "feeling": self.feeling,'
)
print('5. Added feeling to to_dict')

# 6. Add to from_dict
content = content.replace(
    's.file_touches = d.get("file_touches", [])',
    's.file_touches = d.get("file_touches", [])\n        s.feeling = d.get("feeling", None)'
)
print('6. Added feeling to from_dict')

with open(p, 'w') as f:
    f.write(content)

# Syntax check
try:
    py_compile.compile(p, doraise=True)
    print('7. SYNTAX OK!')
except py_compile.PyCompileError as e:
    print(f'7. SYNTAX ERROR: {e}')
