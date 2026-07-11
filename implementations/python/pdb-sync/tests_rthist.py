"""Tests RTHIST: Historical performance monitoring."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_rthist import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS RTHIST\n')

# Record ops
rthist_record_ops(5, 1, 0)
rthist_record_ops(3, 0, 1)
test("record ops completes", True)

# Record agent
rthist_record_agent('test-a', 100, 2)
rthist_record_agent('test-a', 50, 1)
rthist_record_agent('test-b', 200, 1)
test("record agent completes", True)

# Record namespace
rthist_record_namespace('System', 10)
rthist_record_namespace('DDP', 5)
test("record namespace completes", True)

# Snapshot
s = rthist_snapshot()
test("snapshot returns dict", isinstance(s, dict))
test("snapshot has ops", 'ops' in s)

# Query ops 24h
ops = rthist_ops_last_24h()
test("ops returns list", isinstance(ops, list))
test("ops has data", len(ops) >= 1)

# Query agents
agents = rthist_agents_last_24h()
test("agents returns dict", isinstance(agents, dict))
test("test-a in agents", 'test-a' in agents)
test("test-b in agents", 'test-b' in agents)

if 'test-a' in agents:
    test("test-a calls >=3", agents['test-a']['calls'] >= 3)
    test("test-a avg_ms > 0", agents['test-a']['avg_ms'] > 0)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
