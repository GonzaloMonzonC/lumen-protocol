"""Tests MSM-01: BIJ — Before-Image Journal."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_bij import *
from pdb_docs import _get_pdb_tools

t = _get_pdb_tools()
passed = failed = 0

def test(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1
    print(f"  {'✅' if ok else '❌'} {name}")

print('🧪 TESTS BIJ\n')

# Setup — limpiar estado de ejecuciones previas (test autocontenido)
for _tx in ('test-bij-1', 'test-bij-2'):
    t.tool_kill({'ns': 'BIJ', 'subs': ['tx', _tx]})
t.tool_kill({'ns': 'BIJ_TEST', 'subs': []})
bij_init()

# Test 1: Init creates control block
ctrl = t.tool_get({'ns':'BIJ','subs':['control']}).get('value')
test("init creates control", ctrl is not None)
test("control has seq_no", ctrl.get('seq_no', -1) >= 0)

# Test 2: Record before-image
tx = 'test-bij-1'
entry = bij_record('System', ['pulse', 'hermes'], {'tasks': 5}, tx)
test("record returns entry", entry is not None)
test("record has tx_id", entry.get('tx_id') == tx)
test("record has old_value", entry.get('old_value') == {'tasks': 5})

# Test 3: BIJ("file", seq) guardado
seq = entry.get('seq')
r = t.tool_get({'ns':'BIJ','subs':['file',seq]})
test("file entry saved", r.get('success'))

# Test 4: BIJ("tx", tx_id) guardado — encontrar por $ORDER
r = t.tool_order({'ns':'BIJ','subs':['tx',tx,''],'direction':-1})
tx_key = int(r['value']) if r.get('value') else None
r = t.tool_get({'ns':'BIJ','subs':['tx',tx, tx_key]}) if tx_key else {}
test("tx entry saved", r.get('success'))

# Test 5: Commit
bij_commit(tx)
r = t.tool_get({'ns':'BIJ','subs':['tx',tx, tx_key]}) if tx_key else {}
test("entry committed", r.get('value',{}).get('status') == 'committed')

# Test 6: Rollback
tx2 = 'test-bij-2'
old_val = {'tasks': 5, 'status': 'idle'}
t.tool_set({'ns':'BIJ_TEST','subs':['agent'],'value':old_val})
bij_record('BIJ_TEST', ['agent'], old_val, tx2)
t.tool_set({'ns':'BIJ_TEST','subs':['agent'],'value':{'tasks':99,'status':'busy'}})
n = bij_rollback(tx2)
restored = t.tool_get({'ns':'BIJ_TEST','subs':['agent']}).get('value')
test("rollback restores entries", n == 1)
test("rollback restores tasks", restored.get('tasks') == 5)
test("rollback restores status", restored.get('status') == 'idle')

# Test 7: Status report
s = bij_status()
test("status shows seq_no", s.get('seq_no', 0) >= 2)
test("status shows committed", s.get('committed', 0) >= 1)
test("status shows rolled_back", s.get('rolled_back', 0) >= 1)

# Cleanup
t.tool_kill({'ns':'BIJ_TEST','subs':['agent']})

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
