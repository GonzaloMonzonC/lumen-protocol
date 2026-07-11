"""Tests CSFMON: Watchdog + failover."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_watchdog import *
from pdb_docs import _get_pdb_tools; t = _get_pdb_tools()

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS CSFMON: Watchdog\n')

# Config
c = watchdog_config(10, 30)
test("config returns dict", isinstance(c, dict))
test("config has interval", c.get('interval_sec') == 10)

# Heartbeat
watchdog_heartbeat('hermes')
s = watchdog_status()
test("heartbeat sets active", s.get('active_agent') == 'hermes')
test("status alive", s.get('status') == 'alive')

# Check
check = watchdog_check()
test("check ok", check.get('ok'))
test("check healthy", 'healthy' in check.get('reason', ''))

# Failover
r = watchdog_failover()
test("failover works", r.get('to') == 'lisa')
test("failover counts", r.get('count', 0) >= 1)

s2 = watchdog_status()
test("active after failover", s2.get('active_agent') == 'lisa')
test("failover in status", s2.get('failover_count', 0) >= 1)

# Recovery
t.tool_set({"ns": "CSFMON", "subs": ["watchdog"], "value": {"active": "hermes", "status": "alive", "heartbeat": "2026-07-12T10:00:00Z", "last_seen": "2026-07-12T10:00:00Z"}})
s3 = watchdog_status()
test("recovery sets hermes", s3.get('active_agent') == 'hermes')

# Get config back
c2 = watchdog_get_config()
test("get config returns interval", c2.get('interval_sec', 0) > 0)
test("get config has primary", c2.get('primary') == 'hermes')

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
