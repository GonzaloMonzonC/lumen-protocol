"""Tests MSM-02: Journal Daemon."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_journal_daemon import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1
    print(f"  {'✅' if ok else '❌'} {name}")

print('🧪 TESTS Journal Daemon\n')

# Init
daemon_init()
s = daemon_status()
test("daemon initializes", s is not None)
test("daemon status ACTIVE", s.get('status') == 'ACTIVE')
test("daemon has batch_size", s.get('batch_size', 0) > 0)

# Cycle
r = daemon_cycle()
test("cycle completes", 'flushed' in r)
test("cycle returns status", 'status' in r)

# Pause/Resume
daemon_set_status('SUSPENDED')
test("daemon paused", daemon_status().get('status') == 'SUSPENDED')
daemon_set_status('ACTIVE')
test("daemon resumed", daemon_status().get('status') == 'ACTIVE')

# Daemon thread
d = JournalDaemon(interval=1)
test("daemon thread created", d is not None)
d.start()
import time; time.sleep(0.5)
test("daemon thread running", d.is_alive())
d.stop()
time.sleep(0.3)
test("daemon thread stopped", not d.is_alive())

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
