"""Tests MSM-04: Error Catalog."""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
from pdb_error_catalog import error_catalog_init, error_catalog_lookup, MSM_ERRORS, AGENT_ERRORS

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1
    else: failed += 1
    print(f"  {'✅' if ok else '❌'} {name}")

print('🧪 TESTS Error Catalog\n')

n = error_catalog_init()
test("init returns total", n >= len(AGENT_ERRORS))
test("has MSM errors", len(MSM_ERRORS) > 200)
test("has agent errors", len(AGENT_ERRORS) == 11)

for code in ['10', 'DSCON', 'UNDEF', 'SYNTX']:
    info = error_catalog_lookup(code)
    test(f"lookup {code}", info.get('description') != f"Unknown: {code}")

for code in ['AG-001', 'H-001', 'ML-001']:
    info = error_catalog_lookup(code)
    test(f"lookup {code}", info is not None and info.get('source') != 'unknown')

info = error_catalog_lookup('NOEXISTE')
test("unknown code", info is None or 'Unknown' in info.get('description',''))

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
