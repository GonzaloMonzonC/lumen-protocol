"""Tests MSAJOB: Agent control (3 kill levels)."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_msajob import *

# Setup autocontenido: los agentes a matar deben existir en ^System("pulse")
import _paths  # noqa: F401
from pdb_tools import tool_set as _seed_set
for _a in ("test-agent", "test-agent2", "old"):
    _seed_set({"ns": "System", "subs": ["pulse", _a],
               "value": {"status": "online", "fixture": True}})

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MSAJOB\n')

# Kill level 1
r1 = agent_kill('test-agent', 1)
test("L1 success", r1.get('success'))
test("L1 level", r1.get('level') == 1)
test("L1 action", 'soft_kill' in r1.get('action', ''))

# Kill level 2
r2 = agent_kill('test-agent2', 2)
test("L2 success", r2.get('success'))
test("L2 level", r2.get('level') == 2)
test("L2 action", 'error_kill' in r2.get('action', ''))

# Kill level 3
r3 = agent_kill('old', 3)
test("L3 success", r3.get('success'))
test("L3 level", r3.get('level') == 3)
test("L3 action", 'hard_kill' in r3.get('action', ''))

# Invalid level
r4 = agent_kill('test-agent', 99)
test("invalid level fails", not r4.get('success'))

# Non-existent agent
r5 = agent_kill('no-existe', 1)
test("missing agent fails", not r5.get('success'))

# History
h = agent_history('test-agent')
test("history returns list", isinstance(h, list))
test("history has entries", len(h) >= 1)

h2 = agent_history()
test("history all returns list", isinstance(h2, list))

# Status
s = agent_status('test-agent')
test("status returns dict", isinstance(s, dict))

# Agent info (MSSJEX)
info = agent_info('hermes')
test("info returns dict", isinstance(info, dict))
test("info has agent", info.get('agent') == 'hermes')
test("info has status", 'status' in info)
test("info has load", 'load' in info)
test("info has micro_status", 'micro_status' in info)
test("info has recent_errors", 'recent_errors' in info)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
