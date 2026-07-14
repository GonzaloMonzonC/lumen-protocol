"""Run all test suites."""
import os, subprocess, sys
import _paths  # rutas repo-relativas

tests_dir = os.path.dirname(os.path.abspath(__file__))

tests = [
    'tests_compiler.py',
    'tests_compiler_full.py', 
    'tests_bytecode_vm.py',
    'tests_funcs.py',
    'tests_routines.py',
    'tests_stackvm.py',
    'tests_imp01_write.py',
    'tests_imp02_arith.py',
    'tests_imp03_global.py',
    'tests_imp04_do.py',
    'tests_imp05_for_order.py',
    'test_report_final2.py',
    'test_bc_cache.py',
    'test_bc_inval.py',
    'tests_ddp_client.py',
    'tests_sync_engine.py',
    'tests_ddp_integration.py',
]

env = os.environ.copy()
env['PYTHONPATH'] = _paths.PDB_DIR_S

passed = 0
failed = 0
results = []

for t in tests:
    path = os.path.join(tests_dir, t)
    if not os.path.exists(path):
        results.append((t, 'NOT FOUND'))
        failed += 1
        continue
    try:
        r = subprocess.run([sys.executable, path], capture_output=True, text=True, timeout=30, env=env)
        if r.returncode == 0:
            passed += 1
            results.append((t, 'OK', r.stdout.strip().split('\n')[-1]))
        else:
            failed += 1
            err_lines = r.stderr.strip().split('\n')[-3:]
            results.append((t, 'FAIL', err_lines))
    except subprocess.TimeoutExpired:
        failed += 1
        results.append((t, 'TIMEOUT', []))
    except Exception as e:
        failed += 1
        results.append((t, 'ERROR', [str(e)]))

print('=' * 55)
print(f'🧪 M-LIGHT v2 + DDP — TEST SUITE COMPLETE')
print('=' * 55)
total_p = 0
total_f = 0
for r in results:
    if r[1] == 'OK':
        print(f'  ✅ {r[0]:35s} {r[2]}')
    elif r[1] == 'NOT FOUND':
        print(f'  ⚠️  {r[0]:35s} FILE MISSING')
    else:
        print(f'  ❌ {r[0]:35s} FAILED')
        for e in r[1:]:
            if isinstance(e, list):
                for line in e:
                    print(f'     {line}')

print('=' * 55)
print(f'  ✅ Suites passed: {passed}')
print(f'  ❌ Suites failed: {failed}')
print(f'  📊 Total suites:  {passed + failed}')
print('=' * 55)
