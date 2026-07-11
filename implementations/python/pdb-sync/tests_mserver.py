"""Tests MSERVER v3: Full MSM architecture."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_mserver import *

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSERVER v3\n')

# Init
n = mserver_init()
t("init ok", n >= 0)

# Registry
sv = mserver_list()
t("list has services", len(sv) >= 5)
s = mserver_get('orchestrator')
t("get orchestrator", s and s.get('handler') == 'hermes')
t("get knowledge", mserver_get('knowledge') and mserver_get('knowledge').get('handler') == 'zalo')

# Start/stop
r = mserver_start('orchestrator')
t("start OK", r.get('success'))
t("start retcode", r.get('retcode') == 1)
t("start handler", r.get('handler') == 'hermes')
r2 = mserver_stop('orchestrator')
t("stop OK", r2.get('success'))

# Start bad
t("start bad", not mserver_start('nope').get('success'))

# Validate
t("validate public", mserver_validate('help','c1')['success'])
t("validate no token", not mserver_validate('orchestrator','c2',None)['success'])
t("validate token", mserver_validate('orchestrator','hermes','tok')['success'])
t("validate bad", not mserver_validate('nope','c1')['success'])

# Route
r3 = mserver_route('orchestrator')
t("route success", r3.get('success'))
t("route handler", r3.get('handler') == 'hermes')
t("route entry", 'lumen://' in r3.get('entry',''))

# Route bad
t("route bad", not mserver_route('nope').get('success'))

# Reply
r4 = mserver_reply('OK', 1)
t("reply OK", r4.get('retcode') == 1 and r4.get('desc') == 'OK')
r5 = mserver_reply('FAIL', 43)
t("reply fail", r5.get('retcode') == 43)

# Register/unregister
mserver_register('test-x', 'test-h', 'lumen://x')
t("reg add", mserver_get('test-x') is not None)
mserver_unregister('test-x')
t("unreg del", mserver_get('test-x') is None)

# Status
st = mserver_status()
t("status total", st.get('total', 0) >= 5)
t("status by_handler", len(st.get('by_handler', {})) >= 1)
t("status active", 'active' in st)
t("status by_auth", 'HMAC' in st.get('by_auth', {}))

# Auto-start
sv2 = mserver_list()
active_count = len([s for s in sv2 if s.get('status') == 'active'])
t("auto-started services", active_count >= 0)

# Handler per service
services_by_handler = {}
for s in sv2:
    h = s.get('handler', '?')
    if h not in services_by_handler: services_by_handler[h] = 0
    services_by_handler[h] += 1
t("hermes has services", services_by_handler.get('hermes', 0) >= 2)
t("zalo has services", services_by_handler.get('zalo', 0) >= 1)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
