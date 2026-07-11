"""Tests MSM-03: System Startup (CSSTART)."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_system_startup import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1
    print(f"  {'✅' if ok else '❌'} {name}")

print('🧪 TESTS CSSTART\n')

# Test init
s = startup_init()
test("init creates state", s is not None)
test("init status BOOTING", s.get('status') == 'BOOTING')

# Test service ready — sin pulse, debe dar False
test("service not ready (no pulse)", not startup_service_ready('noexiste'))

# Test startup run
from pdb_docs import _get_pdb_tools
t = _get_pdb_tools()

# Pulse para hermes
t.tool_set({'ns':'System','subs':['pulse','hermes'],'value':{'status':'online','last_activity':'2026-07-12T10:00:00Z'}})

result = startup_run()
test("startup returns status", result.get('status') in ('READY', 'DEGRADED'))
test("startup started hermes", 'hermes' in result.get('started', []))
test("startup started zalo", 'zalo' in result.get('started', []))
test("startup all 5 services", len(result.get('started', [])) == 5)

# Test startup status
s2 = startup_status()
test("status returns dict", s2 is not None)
test("status has services_ok", 'services_ok' in s2)

# Test service ready — con pulse reciente
t.tool_set({'ns':'System','subs':['pulse','hermes'],'value':{'status':'online','last_activity':'2026-07-12T10:00:00Z'}})
test("service ready (with pulse)", startup_service_ready('hermes'))

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
