"""
post-patch-validator.py — Validate server.py and dashboard.html after patches.

Usage: python post-patch-validator.py [path_to_server.py] [path_to_dashboard.html]

Checks:
1. Python syntax (server.py)
2. Brace balance in JS (dashboard.html)
3. JS element ID consistency ($('id') matches <div id="id">)
4. Duplicate function definitions
5. HTML tag balance
"""

import sys, re, json, os, py_compile
from pathlib import Path

errors = []
warnings = []

def check(title, ok, detail=""):
    if ok:
        print(f"  ✅ {title} {detail}")
    else:
        print(f"  ❌ {title} {detail}")
        errors.append(f"{title}: {detail}")

server_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent / "implementations/mcp-servers/thinking/server.py"
dash_path = Path(sys.argv[2]) if len(sys.argv) > 2 else Path(__file__).parent.parent / "implementations/mcp-servers/thinking/dashboard.html"

print(f"=== Post-Patch Validator ===\n")

# 1. Python syntax
try:
    py_compile.compile(str(server_path), doraise=True)
    check("server.py syntax", True)
except py_compile.PyCompileError as e:
    check("server.py syntax", False, str(e))

# 2. Brace balance in dashboard JS
if dash_path.exists():
    with open(dash_path) as f:
        dash_content = f.read()
    # Find all script blocks
    script_blocks = re.findall(r'<script>(.*?)</script>', dash_content, re.DOTALL)
    if script_blocks:
        for i, block in enumerate(script_blocks):
            opens = block.count('{')
            closes = block.count('}')
            if opens != closes:
                check(f"dashboard.html JS script #{i}: brace balance", False, f"{opens}/{closes}")
            else:
                check(f"dashboard.html JS script #{i}: brace balance", True, f"{opens}/{closes}")
        
        # JS element ID consistency
        js_refs = set(re.findall(r"\$\(['\"]([^'\"]+)['\"]\)", dash_content))
        html_ids = set(re.findall(r'id="([^"]+)"', dash_content))
        missing = js_refs - html_ids
        if missing:
            check("JS references match HTML IDs", False, f"Missing: {', '.join(sorted(missing))}")
        else:
            check("JS references match HTML IDs", True)
    else:
        print("  ⚠️  No inline script blocks found in dashboard.html")

# 3. Duplicate functions in server.py
funcs = []
with open(server_path) as f:
    server_lines = f.readlines()
for i, line in enumerate(server_lines):
    m = re.match(r'^def (\w+)\(', line)
    if m:
        funcs.append(m.group(1))
from collections import Counter
dupes = [(n, c) for n, c in Counter(funcs).items() if c > 1]
if dupes:
    check("Duplicate function definitions", False, f"{len(dupes)} duplicates: {', '.join(n for n,c in dupes)}")
else:
    check("Duplicate function definitions", True, f"{len(funcs)} functions")

# 4. HTML tag balance
if dash_path.exists():
    opens = dash_content.count('<div')
    closes = dash_content.count('</div>')
    if opens != closes:
        check("Dashboard HTML div balance", False, f"{opens} open / {closes} close (diff: {opens-closes})")
    else:
        check("Dashboard HTML div balance", True)
    
    script_open = dash_content.count('<script')
    script_close = dash_content.count('</script>')
    if script_open != script_close:
        check("Dashboard script tags", False, f"{script_open} / {script_close}")
    else:
        check("Dashboard script tags", True)

# Summary
print(f"\n=== Results: {len(errors)} errors ===")
if errors:
    for e in errors:
        print(f"  ❌ {e}")
    sys.exit(1)
else:
    print("  ✅ All checks passed!")
