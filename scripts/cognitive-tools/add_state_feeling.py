import py_compile

p = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(p) as f:
    content = f.read()

# 1. Find where TOOLS list ends and TOOL_MAP starts
tools_end = content.rfind('    },\n]')
if tools_end > 0:
    feeling_tool = '''    },
    {
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
                    "minimum": 0,
                    "maximum": 10,
                    "description": "Confidence in current trajectory"
                },
                "energy": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 10,
                    "description": "Mental energy level"
                },
                "context": {
                    "type": "string",
                    "description": "Optional context of what you're feeling"
                },
                "session_id": {
                    "type": "string",
                    "description": "Session ID (optional)"
                }
            },
            "required": ["mood", "confidence", "energy"]
        }
    }'''
    content = content[:tools_end+1] + feeling_tool + content[tools_end+1:]
    print('Added state_feeling tool definition')

# 2. Add handler
handler = '''


def tool_state_feeling(args: dict) -> dict:
    """Externalize cognitive state. Persists in PDB for dashboard."""
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

insert_point = content.find('def _build_metrics')
if insert_point > 0:
    content = content[:insert_point] + handler + '\n\n' + content[insert_point:]
    print('Added handler')

# 3. Register in TOOL_MAP
content = content.replace(
    '    "work_start": tool_work_start,',
    '    "work_start": tool_work_start,\n    "state_feeling": tool_state_feeling,'
)
print('Registered in TOOL_MAP')

# 4. Add feeling field to Session
content = content.replace(
    'self.file_touches: list = []',
    'self.file_touches: list = []\n        self.feeling = None'
)
print('Added feeling to Session.__init__')

# 5. Add to to_dict
content = content.replace(
    '"file_touches": self.file_touches,',
    '"file_touches": self.file_touches,\n            "feeling": self.feeling,'
)
print('Added feeling to to_dict')

# 6. Add to from_dict
content = content.replace(
    's.file_touches = d.get("file_touches", [])',
    's.file_touches = d.get("file_touches", [])\n        s.feeling = d.get("feeling", None)'
)
print('Added feeling to from_dict')

with open(p, 'w') as f:
    f.write(content)

py_compile.compile(p, doraise=True)
print('Syntax OK!')
