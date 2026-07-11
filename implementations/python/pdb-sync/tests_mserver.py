"""Tests MSERVER v2: Lifecycle + validate + retcodes."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_mserver import *

p = f = 0
def t(n,o):
    global p,f
    if o: p+=1; print(f"  ✅ {n}")
    else: f+=1; print(f"  ❌ {n}")

print('🧪 TESTS MSERVER v2\n')

mserver_init()

# Registry
svc = mserver_list()
t("list services", len(svc) >= 5)
s = mserver_get('orchestrator')
t("get service", s is not None and 'entry' in s)

# Lifecycle
r = mserver_start('orchestrator')
t("start success", r.get('success'))
t("start retcode 1", r.get('retcode') == 1)
r2 = mserver_stop('orchestrator')
t("stop success", r2.get('success'))
t("stop retcode 1", r2.get('retcode') == 1)

# Start non-existent
r3 = mserver_start('no-svc')
t("start bad service", not r3.get('success'))

# Validate
t("validate OK", mserver_validate('help','c1')['success'])
t("validate no token", not mserver_validate('orchestrator','c2',None)['success'])
t("validate bad svc", not mserver_validate('bad','c1')['success'])
t("validate +token", mserver_validate('orchestrator','c3','tok')['success'])

# Reply
r4 = mserver_reply('OK', 1)
t("reply has retcode", r4.get('retcode') == 1)
t("reply has desc", 'desc' in r4)
r5 = mserver_reply('ERROR', 43)
t("reply error 43", r5.get('retcode') == 43)

# Register/Unregister
mserver_register('test-x', 'lumen://x')
t("register adds", mserver_get('test-x') is not None)
mserver_unregister('test-x')
t("unregister removes", mserver_get('test-x') is None)

print(f"\n📊 {p}/{p+f} tests passed")
sys.exit(0 if f==0 else 1)
