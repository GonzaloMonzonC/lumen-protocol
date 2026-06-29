"""Fix %GL handler in server.py"""
import re, json

path = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# The marker we need to replace starts at the %GL handler
marker1 = 'if code.upper().startswith("D ^%GL") or code.upper() in ("^%GL", "%GL"):'
marker1b = "if code.upper().startswith('D ^%GL') or code.upper() in ('^%GL', '%GL'):"

# Try to find it
for marker in [marker1, marker1b]:
    idx = content.find(marker)
    if idx >= 0:
        break

if idx < 0:
    print('ERROR: marker not found')
    # Try to find any line with ^%GL
    for i, line in enumerate(content.split('\n')):
        if '^%GL' in line and ('if' in line or 'elif' in line):
            print(f'Line {i+1}: {line[:100]}')
    exit(1)

# Find the end: next indented if/elif at same level
lines = content.split('\n')
start_line = content[:idx].count('\n')
base_indent = len(lines[start_line]) - len(lines[start_line].lstrip())

# Find the matching 'except Exception' or next handler
end = start_line + 1
found_except = False
while end < len(lines):
    s = lines[end].strip()
    indent = len(lines[end]) - len(lines[end].lstrip())
    if s.startswith('except ') and indent == base_indent:
        found_except = True
        break
    end += 1

if not found_except:
    print('ERROR: could not find end of handler')
    exit(1)

# Read the entire new handler from a template file
template_path = r'C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\new_gl_handler.py'
with open(template_path, 'r', encoding='utf-8') as f:
    new_handler = f.read()

# Replace
new_content = '\n'.join(lines[:start_line]) + '\n' + new_handler + '\n' + '\n'.join(lines[end:])
with open(path, 'w', encoding='utf-8') as f:
    f.write(new_content)

print(f'Replaced handler at line {start_line+1}-{end+1}')
print('OK')
