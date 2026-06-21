#!/usr/bin/env python3
"""Add arg extraction to PDB tool functions."""
with open('pdb_tools.py', 'r') as f:
    content = f.read()

# Each extraction line to insert after the def line
extractions = {
    'tool_set': '    a = args[0] if args else kwargs; ns = a["ns"]; subs = a["subs"]; value = a["value"]\n',
    'tool_get': '    a = args[0] if args else kwargs; ns = a["ns"]; subs = a["subs"]; default = a.get("default")\n',
    'tool_order': '    a = args[0] if args else kwargs; ns = a["ns"]; subs = a["subs"]; direction = a.get("direction", 1)\n',
    'tool_data': '    a = args[0] if args else kwargs; ns = a["ns"]; subs = a["subs"]\n',
    'tool_kill': '    a = args[0] if args else kwargs; ns = a["ns"]; subs = a["subs"]\n',
    'tool_incr': '    a = args[0] if args else kwargs; ns = a["ns"]; subs = a["subs"]; increment = a.get("increment", 1.0)\n',
    'tool_merge': '    a = args[0] if args else kwargs; target_ns = a["target_ns"]; target_subs = a["target_subs"]; source_ns = a["source_ns"]; source_subs = a["source_subs"]\n',
    'tool_query': '    a = args[0] if args else kwargs; sql = a["sql"]; params = a.get("params"); limit = a.get("limit", 100)\n',
}

lines = content.split('\n')
result = []
skip_next = False

for i, line in enumerate(lines):
    result.append(line)
    for fn, ext in extractions.items():
        if line.strip().startswith(f'def {fn}(*args, **kwargs) -> dict:'):
            # Find the next non-empty, non-comment, non-docstring line
            for j in range(i+1, len(lines)):
                s = lines[j].strip()
                if s.startswith('"""') or s.startswith("'''") or s == '' or s.startswith('#'):
                    continue
                if s.startswith('try:'):
                    # Insert after try:
                    result.append('    try:')
                    result.append('        ' + ext.strip())
                    skip_next = True
                    break
                else:
                    # Insert before this line
                    result.append('    ' + ext.strip())
                    break
            break

content = '\n'.join(result)
with open('pdb_tools.py', 'w') as f:
    f.write(content)
print('Extractions added')
