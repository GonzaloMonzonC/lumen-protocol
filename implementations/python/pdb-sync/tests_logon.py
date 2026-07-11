"""Tests LOGON: Session Audit."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_session_audit import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS LOGON: Session Audit\n')

# Session start
s = session_start('test-agent', 'test-circuit')
test("start returns session", s is not None)
test("start sets agent", s.get('agent') == 'test-agent')
test("start sets status active", s.get('status') == 'active')
test("start has origin", s.get('origin') == 'test-circuit')

# Session start without origin
s2 = session_start('test-agent2')
test("start without origin", s2.get('origin') == 'unknown')

# Session end
d = session_end('test-agent')
test("end returns duration", d >= 0)
test("end closed session", d >= 0)

# Session fail
c = session_fail('test-agent', 'bad auth')
test("fail returns count", c >= 1)
c2 = session_fail('test-agent', 'timeout')
test("fail increments", c2 >= 2)

# Session active
active = session_active()
test("active returns list", isinstance(active, list))
test("test-agent2 still active", any(s['agent'] == 'test-agent2' for s in active))
test("test-agent closed", not any(s['agent'] == 'test-agent' and s['status']=='active' for s in active))

# Session report
report = session_report(limit=10)
test("report returns list", isinstance(report, list))
test("report has sessions", len(report) >= 2)

# Report by agent
rep_agent = session_report('test-agent')
test("report by agent", len(rep_agent) >= 1)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
