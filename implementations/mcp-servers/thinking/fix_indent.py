import re

path = r"C:\Users\gonzalo\Documents\GitHub\lumen-protocol\implementations\mcp-servers\thinking\server.py"
with open(path, 'r') as f:
    content = f.read()

# Fix: add 4 spaces to lines 315-364 (they need to be inside the try block, which is inside with)
lines = content.split('\n')
# Line numbers are 0-indexed in the array, file line 315 = array index 314
# Line 315 "        pairs = []" needs to become "            pairs = []"
# We need to shift lines 315-364 by +4 spaces

for i in range(314, min(364, len(lines))):
    if lines[i].strip():  # non-empty
        lines[i] = '    ' + lines[i]

# Also fix the except line
if lines[364].strip().startswith('except'):
    pass  # already at correct level (8 spaces)

content = '\n'.join(lines)
with open(path, 'w') as f:
    f.write(content)

print("DONE - re-indented lines 315-364")
