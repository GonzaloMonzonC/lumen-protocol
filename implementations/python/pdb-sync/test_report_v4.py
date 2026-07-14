"""Final test: REPORT.m from ^ROUTINE."""
import sys, os
import _paths  # noqa: F401  # sys.path del stack PDB

from pdb_tools import tool_set, tool_kill
from m_routines import RoutineExecutor

# Load REPORT.m
with open(_paths.REPORT_M) as f:
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
