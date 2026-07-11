"""Tests MSERVER: Service Registry + LUMEN auth."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_mserver import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MSERVER\n')

mserver_init()
n = mserver_init()
test("init completes", n >= 0)

# List
svc = mserver_list()
test("list has services", len(svc) >= 5)
names = [s['name'] for s in svc]
test("orchestrator in list", 'orchestrator' in names)
test("knowledge in list", 'knowledge' in names)
test("analyzer in list", 'analyzer' in names)

# Get
s = mserver_get('orchestrator')
test("get returns service", s is not None)
test("get has entry", 'entry' in s)
test("get has auth", s.get('auth') == 'HMAC')

# Register new
mserver_register('test-svc', 'lumen://test/v1', 'HMAC')
svc2 = mserver_list()
test("register adds service", len(svc2) >= len(svc))

# Unregister
mserver_unregister('test-svc')
svc3 = mserver_list()
test("unregister removes", len(svc3) == len(svc))

# Auth
test("public auth OK", mserver_auth('help', 'c1')['success'])
test("HMAC no token denied", not mserver_auth('orchestrator', 'c2')['success'])
test("HMAC+token allowed", mserver_auth('orchestrator', 'c3', 'tok')['success'])

# Status
st = mserver_status()
test("status has count", st['total_services'] >= 5)
test("status has HMAC count", st['by_auth']['HMAC'] >= 4)
test("status has public count", st['by_auth']['public'] >= 1)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
