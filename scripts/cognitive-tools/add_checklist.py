"""Add checklist tool to objective_loop.py"""
import py_compile

p = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\objective_loop.py'
with open(p) as f:
    content = f.read()

# Find the EXPORT section
insert_point = content.find('# ── Export for server.py ──')

if insert_point < 0:
    print('✗ Insert point not found')
    exit(1)

checklist_tool = '''

def tool_checklist(args: dict) -> dict:
    """Pilot checklist: retrieve, mark, or check status of task-type checklists."""
    action = args.get("action", "get")
    task_type = args.get("task_type", "")
    item_tool = args.get("tool", "")

    if not task_type and action != "status":
        return {"content": [{"type": "text", "text": "task_type required. Options: bug_fix, feature, research, audit"}]}

    try:
        import sqlite3, json as _j, os, time as _t
        db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pdb", "lumen-pdb.db")
        conn = sqlite3.connect(db_path)

        if action == "get":
            # Try raw JSON at def:{task_type}
            rows = conn.execute("SELECT value FROM _globals WHERE ns='CHECKLIST' AND subkey=?", (f'def:{task_type}',)).fetchall()
            if not rows:
                conn.close()
                return {"content": [{"type": "text", "text": f"No checklist defined for '{task_type}'."}]}
            items = _j.loads(rows[0][0])

            # Get session usage
            session_id = args.get("session", "default")
            used_rows = conn.execute(
                "SELECT subkey FROM _globals WHERE ns='CHECKLIST' AND subkey LIKE ?",
                (f'session:{session_id}:{task_type}:%',)).fetchall()
            used_tools = set()
            for (sk,) in used_rows:
                sk = sk.decode() if isinstance(sk, bytes) else sk
                parts = sk.split(':')
                if len(parts) >= 5:
                    used_tools.add(parts[4])

            lines = [f'🧾 Checklist — {task_type}']
            for item in items:
                status = '✅' if item['tool'] in used_tools else ('⬜' if item.get('required') else '◽')
                phase_icon = {'before': '📋', 'during': '🔧', 'after': '✅'}.get(item.get('phase', ''), '>')
                lines.append(f'  {status} {phase_icon} {item["desc"]}')
                lines.append(f'     -> {item["tool"]}')

            required_total = sum(1 for i in items if i.get('required'))
            required_done = sum(1 for i in items if i.get('required') and i['tool'] in used_tools)
            lines.append(f'')
            lines.append(f'  Compliance: {required_done}/{required_total} required items')

            conn.close()
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        elif action == "mark":
            if not item_tool:
                conn.close()
                return {"content": [{"type": "text", "text": "tool required for mark action."}]}
            session_id = args.get("session", "default")
            subkey = f'session:{session_id}:{task_type}:{item_tool}:{int(_t.time())}'
            conn.execute("INSERT OR REPLACE INTO _globals (ns, subkey, value) VALUES (?, ?, ?)",
                        ('CHECKLIST', subkey.encode(), _j.dumps({"tool": item_tool, "ts": _t.time()}).encode()))
            conn.commit()
            conn.close()
            return {"content": [{"type": "text", "text": f'Marked {item_tool} as done for {task_type}.'}]}

        elif action == "status":
            session_id = args.get("session", "default")
            rows = conn.execute(
                "SELECT subkey FROM _globals WHERE ns='CHECKLIST' AND subkey LIKE ? ORDER BY subkey",
                (f'session:{session_id}:%',)).fetchall()
            if not rows:
                conn.close()
                return {"content": [{"type": "text", "text": "No checklist activity this session."}]}
            by_type = {}
            for (sk,) in rows:
                sk = sk.decode() if isinstance(sk, bytes) else sk
                parts = sk.split(':')
                if len(parts) >= 4:
                    ttype = parts[2]
                    by_type.setdefault(ttype, []).append(parts[3] if len(parts) > 3 else sk)
            lines = ['Checklist Status - This Session']
            for ttype, tools in sorted(by_type.items()):
                lines.append(f'  {ttype}: {len(tools)} items marked')
                for t in tools:
                    lines.append(f'    [x] {t}')
            conn.close()
            return {"content": [{"type": "text", "text": "\n".join(lines)}]}

        conn.close()
        return {"content": [{"type": "text", "text": f"Unknown action: {action}"}]}
    except Exception as e:
        return {"content": [{"type": "text", "text": f"Checklist error: {e}"}]}


'''

content = content[:insert_point] + checklist_tool + content[insert_point:]

# Add to HANDLERS
content = content.replace(
    'OBJECTIVE_HANDLERS = {',
    'OBJECTIVE_HANDLERS = {\n    "checklist": tool_checklist,'
)

# Add schema - find the closing bracket of the schemas array and add before it
old_close = '    },\n]'
new_close = '''    },
    {
        "name": "checklist",
        "description": "Pilot checklist: get task checklist, mark tools as used, or view session compliance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["get", "mark", "status"], "description": "get, mark, or status"},
                "task_type": {"type": "string", "description": "Task type: bug_fix, feature, research, audit"},
                "tool": {"type": "string", "description": "Tool name to mark as done (for action=mark)"},
                "session": {"type": "string", "description": "Session identifier (default: default)"}
            },
            "required": ["action"]
        }
    },
]'''

# Be more precise: find the last schema closing
last_schema = '        }\n    },\n]'
content = content.replace(last_schema, new_close, 1)

with open(p, 'w') as f:
    f.write(content)

py_compile.compile(p, doraise=True)
print('checklist tool added + syntax OK')
