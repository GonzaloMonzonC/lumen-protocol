"""Final test: REPORT.m from ^ROUTINE."""
import sys, os
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/mcp-servers/pdb"))
sys.path.insert(0, os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync"))

from pdb_tools import tool_set, tool_kill
from m_routines import RoutineExecutor

# Load REPORT.m
with open(os.path.expanduser("~/Documents/GitHub/lumen-protocol/implementations/python/pdb-sync/routines/REPORT.m")) as f:
    code = f.read()

# Store in ^ROUTINE
tool_kill({"ns": "ROUTINE", "subs": ["REPORT"]})
for i, line in enumerate(code.split('\n'), 1):
    if line.strip():
        tool_set({"ns": "ROUTINE", "subs": ["REPORT", str(i)], "value": line})

# Execute
executor = RoutineExecutor()
result = executor.exec("REPORT")

if "error" in result:
    print(f"❌ Error: {result['error']}")
else:
    print("✅ DO ^REPORT completado")
    print(f"   Vars: {list(result.get('vars', {}).keys())}")
