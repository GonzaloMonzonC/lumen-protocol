"""Tests MAPFCB: PDB Map Viewer."""
import sys, os; sys.path.insert(0, os.path.dirname(__file__))
from pdb_map_viewer import *

passed = failed = 0
def test(name, ok):
    global passed, failed
    if ok: passed += 1; print(f"  ✅ {name}")
    else: failed += 1; print(f"  ❌ {name}")

print('🧪 TESTS MAPFCB: PDB Map\n')

results = map_scan_all()
test("scan returns list", isinstance(results, list))
test("scan finds namespaces", len(results) >= 10)

info = map_get_namespace('System')
test("get namespace returns info", info is not None)
test("get has entries", info.get('entries', 0) > 0)

report = map_report()
test("report returns list", isinstance(report, list))
test("report has entries", len(report) >= 10)

# Check specific namespaces we know exist
ns_names = [r['ns'] for r in report]
test("System in report", 'System' in ns_names)
test("CHANGES in report", 'CHANGES' in ns_names)
test("DDP in report", 'DDP' in ns_names)

print(f"\n📊 {passed}/{passed+failed} tests passed")
sys.exit(0 if failed == 0 else 1)
