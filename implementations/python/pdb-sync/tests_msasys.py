"""Tests MSASYS: Unified config system."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_msasys import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MSASYS\n')

n = msasys_init()
test("init returns count", n >= 5)

v = msasys_get('watchdog', 'interval_sec')
test("get returns default", v == 30)

v2 = msasys_get('agents', 'heartbeat_interval')
test("get agents param", v2 == 30)

v3 = msasys_get('ddp', 'max_links')
test("get ddp param", v3 == 16)

# Set + verify
msasys_set('watchdog', 'interval_sec', 60)
v4 = msasys_get('watchdog', 'interval_sec')
test("set changes value", v4 == 60)

# Reset
msasys_reset('watchdog')
v5 = msasys_get('watchdog', 'interval_sec')
test("reset restores default", v5 == 30)

# Non-existent fallback
v6 = msasys_get('nonexistent', 'param')
test("non-existent returns None", v6 is None)

# Report
r = msasys_report()
test("report has watchdog", 'watchdog' in r)
test("report has agents", 'agents' in r)
test("report has ddp", 'ddp' in r)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
