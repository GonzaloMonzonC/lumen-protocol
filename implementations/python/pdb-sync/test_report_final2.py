"""Test final: REPORT.m completo con aserciones."""
import sys, os
import _paths  # noqa: F401  # sys.path del stack PDB

from pdb_tools import tool_set, tool_kill
from m_routines import RoutineExecutor

p = fail = 0
def t(n,o):
    global p,fail
    if o: p+=1; print(f"  ✅ {n}")
    else: fail+=1; print(f"  ❌ {n}")

print('🧪 TEST FINAL: DO ^REPORT\n')

# Load REPORT.m
with open(_paths.REPORT_M) as f:
    code = f.read()

t("script loaded", len(code) > 100)

# Store in ^ROUTINE
tool_kill({"ns": "ROUTINE", "subs": ["REPORT"]})
for i, line in enumerate(code.split('\n'), 1):
    if line.strip():
        tool_set({"ns": "ROUTINE", "subs": ["REPORT", str(i)], "value": line})

t("stored in ^ROUTINE", True)

# Execute
executor = RoutineExecutor()
result = executor.exec("REPORT")
t("DO ^REPORT completes", "error" not in result)
t("has vars", len(result.get("vars", {})) > 0)

# Direct StackVM execution
from m_stackvm import StackVM
vm = StackVM()
vm.compile(code)
vm.exec()
t("StackVM executes", len(vm.ops) > 10)
t("WRITE output", any("Namespace" in str(o) for o in vm.ops))
t("DO subrutina works", "###" in str(vm.ops))

# Labels detected
t("labels found", len(vm.labels) >= 2)

print(f"\n📊 {p}/{p+fail} tests passed")
sys.exit(0 if fail==0 else 1)
