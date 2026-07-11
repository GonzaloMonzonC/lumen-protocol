"""Tests CC4: Micro-status agents."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from cc4_micro_status import *
from pdb_docs import _get_pdb_tools; t = _get_pdb_tools()

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS CC4: Micro-status\n')

# Test update
r = micro_status_update('test-agent', 'online', 'testing', 5)
test("update returns pulse", r is not None)
test("update sets status", r.get('status') == 'online')
test("update sets task", r.get('micro_status') == 'testing')
test("update sets load", r.get('load') == 5)

# Test multiple status values
micro_status_update('test-agent', 'busy', 'working hard', 8)
r2 = t.tool_get({"ns": "System", "subs": ["pulse", "test-agent"]})
p = r2.get("value") if r2.get("success") else {}
test("status changed to busy", p.get('status') == 'busy')
test("task updated", p.get('micro_status') == 'working hard')
test("load updated", p.get('load') == 8)

# Test idle
micro_status_update('test-agent', 'idle', 'waiting', 0)
p2 = t.tool_get({"ns": "System", "subs": ["pulse", "test-agent"]}).get("value")
test("idle status", p2.get('status') == 'idle')

# Test all
all_ = micro_status_all()
test("all returns dict", isinstance(all_, dict))
test("test-agent in all", 'test-agent' in all_)
test("all has zalo", 'zalo' in all_)
test("zalo has status", all_.get('zalo', {}).get('status', '') != '')
test("zalo has micro_status", 'micro_status' in all_.get('zalo', {}))

# Test agents have loads
for agent in ['hermes', 'zalo', 'lisa', 'tom']:
    if agent in all_:
        test(f"{agent} has load", 'load' in all_[agent])
        break

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
