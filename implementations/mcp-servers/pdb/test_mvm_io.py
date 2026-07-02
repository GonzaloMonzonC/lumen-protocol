import sys, os, tempfile, time
sys.path.insert(0, '.')
import importlib.util
spec = importlib.util.spec_from_file_location('pdb_tools', 'pdb_tools.py')
pdb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pdb)

import mvm
vm = mvm.MVM(pdb)

tmp = tempfile.mktemp(suffix='.txt').replace('\\', '/')
print(f'Temp: {tmp}')

code = 'O 5:"' + tmp + '"\nU 5\nW "hello from MVM"\nC 5\nU 0\nW "done"'
print(f'Code: {repr(code)}')

pid = vm.spawn(code, name='io_test')
print(f'Spawned PID: {pid}')

proc = vm.get_process(pid)
if proc:
    for d in proc.devices.devices.values():
        print(f'  Device {d.num}: {d.name}')

vm.tick_all(10)
time.sleep(0.3)

try:
    with open(tmp, 'r') as f:
        content = f.read()
        print(f'FILE CONTENT ({len(content)} chars):')
        print(content)
except FileNotFoundError:
    print('File NOT created')

try:
    os.unlink(tmp)
except:
    pass
print('DONE')
