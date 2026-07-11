"""Tests C1: Service Manager."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_service_manager import get_agents, check_agent_health, dispatch_cycle, manager_run
from pdb_docs import _get_pdb_tools

t = _get_pdb_tools()
passed = failed = 0

def test(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1
    print(f"  {'✅' if ok else '❌'} {name}")

# Setup: 5 agents
agents_data = {
    'hermes': {'status':'online','last_activity':'2026-07-12T10:00:00Z','load':3},
    'zalo':   {'status':'online','last_activity':'2026-07-12T10:00:00Z','load':5},
    'lisa':   {'status':'busy',  'last_activity':'2026-07-12T10:00:00Z','load':8},
    'tom':    {'status':'online','last_activity':'2026-07-12T09:55:00Z','load':2},
    'old':    {'status':'online','last_activity':'2026-07-10T10:00:00Z','load':0},
}
for a, d in agents_data.items():
    t.tool_set({'ns':'System','subs':['pulse',a],'value':d})

print('🧪 TESTS C1: Service Manager\n')

# Test 1: List agents
agents = get_agents()
test("get_agents() returns 5", len(agents) >= 5)

# Test 2: Health checks
test("hermes online", check_agent_health('hermes') == 'online')
test("lisa busy", check_agent_health('lisa') == 'busy')
test("old offline", check_agent_health('old') == 'offline')

# Test 3: Dispatch cycle
result = dispatch_cycle('hermes')
test("dispatch hermes returns dict", isinstance(result, dict))
test("dispatch has action", 'action' in result)

# Test 4: Full manager cycle
cycle = manager_run()
test("manager_run returns dict", isinstance(cycle, dict))
test("manager_run scans agents", cycle.get('agents_scanned', 0) >= 5)

# Test 5: Unknown agent
test("unknown agent health", check_agent_health('noexiste') == 'unknown')

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
